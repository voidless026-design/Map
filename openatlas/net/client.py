"""Bounded async HTTP client shared by investigations and the knowledge base.

Why this exists: the old code made requests one at a time with no body limit, so a
username sweep could hang for many minutes and a huge page could balloon memory.

Guarantees:
* at most ``concurrency`` requests in flight overall and ``per_host`` per host;
* per-request timeout and a body cap (default 2 MB, read as a stream and cut off);
* honest User-Agent, no cookies, no auth headers;
* ``page=True`` requests are robots.txt-gated and never touch data-broker sites.
"""

from __future__ import annotations

import asyncio
import json as _json
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import httpx

from openatlas.config import Config
from openatlas.logger import get_logger
from openatlas.runtime import profiles

log = get_logger("openatlas.net")

DEFAULT_MAX_BYTES = 2 * 1024 * 1024

#: Optional httpx transport override (tests install an ``httpx.MockTransport`` here).
TRANSPORT: Optional[httpx.AsyncBaseTransport] = None

# People-search / data-broker sites: their terms forbid automated access and they sell
# personal data. OpenAtlas never fetches them (search results may still link to them).
DATA_BROKERS = {
    "spokeo.com", "whitepages.com", "beenverified.com", "truepeoplesearch.com",
    "fastpeoplesearch.com", "intelius.com", "radaris.com", "mylife.com", "peoplefinders.com",
    "instantcheckmate.com", "truthfinder.com", "zabasearch.com", "peekyou.com",
    "thatsthem.com", "clustrmaps.com", "familytreenow.com", "usphonebook.com",
}


def host_of(url: str) -> str:
    return (urllib.parse.urlsplit(url).hostname or "").lower()


def is_data_broker(url: str) -> bool:
    h = host_of(url)
    return any(h == d or h.endswith("." + d) for d in DATA_BROKERS)


@dataclass
class Resp:
    status_code: int
    url: str
    headers: Dict[str, str]
    content: bytes
    truncated: bool = False
    error: Optional[str] = None
    _text: Optional[str] = field(default=None, repr=False)

    @property
    def ok(self) -> bool:
        return self.error is None and 200 <= self.status_code < 300

    @property
    def text(self) -> str:
        if self._text is None:
            self._text = self.content.decode("utf-8", errors="replace")
        return self._text

    def json(self) -> Any:
        try:
            return _json.loads(self.text)
        except ValueError:
            return None


def _failed(url: str, error: str) -> Resp:
    return Resp(status_code=-1, url=url, headers={}, content=b"", error=error)


class Net:
    """Use as ``async with Net() as net: r = await net.get(url)``."""

    def __init__(self, *, concurrency: Optional[int] = None, per_host: Optional[int] = None,
                 timeout: float = 10.0, max_bytes: int = DEFAULT_MAX_BYTES,
                 transport: Optional[httpx.AsyncBaseTransport] = None,
                 robots_check: Optional[Any] = None):
        prof = profiles.active()
        self.concurrency = concurrency or prof.net_concurrency
        self.per_host = per_host or prof.per_host
        self.timeout = timeout
        self.max_bytes = max_bytes
        self._sem = asyncio.Semaphore(self.concurrency)
        self._host_sems: Dict[str, asyncio.Semaphore] = {}
        self._client: Optional[httpx.AsyncClient] = None
        self.in_flight = 0
        self.peak_in_flight = 0
        self._transport = transport  # per-instance override (self-tests); else module TRANSPORT
        self._robots_check = robots_check  # per-instance robots override (self-tests)

    async def __aenter__(self) -> "Net":
        self._client = httpx.AsyncClient(
            headers={"User-Agent": Config.services.user_agent, "Accept": "*/*"},
            follow_redirects=True,
            timeout=self.timeout,
            limits=httpx.Limits(max_connections=self.concurrency,
                                max_keepalive_connections=self.concurrency),
            transport=self._transport or TRANSPORT,
        )
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._client is not None:
            await self._client.aclose()

    def _host_sem(self, url: str) -> asyncio.Semaphore:
        h = host_of(url)
        if h not in self._host_sems:
            self._host_sems[h] = asyncio.Semaphore(self.per_host)
        return self._host_sems[h]

    async def request(self, method: str, url: str, *, params: Optional[Dict[str, Any]] = None,
                      headers: Optional[Dict[str, str]] = None, data: Any = None,
                      content: Any = None, json: Any = None, page: bool = False,
                      max_bytes: Optional[int] = None) -> Resp:
        """Make a bounded request. Never raises; failures come back as ``Resp.error``."""
        if self._client is None:
            raise RuntimeError("use 'async with Net() as net'")
        if page:
            if is_data_broker(url):
                return _failed(url, "data-broker site - not fetched by policy")
            from openatlas.utils.robots import can_fetch

            check = self._robots_check or can_fetch
            if not await asyncio.to_thread(check, url):
                return _failed(url, "robots.txt disallows this URL")
        # Never forward credentials, whatever the caller passed.
        safe_headers = {k: v for k, v in (headers or {}).items()
                        if k.lower() not in {"authorization", "cookie"}}
        cap = max_bytes or self.max_bytes
        async with self._sem, self._host_sem(url):
            self.in_flight += 1
            self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
            try:
                async with self._client.stream(method, url, params=params, headers=safe_headers,
                                               data=data, content=content, json=json) as r:
                    chunks, size, truncated = [], 0, False
                    async for chunk in r.aiter_bytes():
                        chunks.append(chunk)
                        size += len(chunk)
                        if size >= cap:
                            truncated = True
                            break
                    return Resp(status_code=r.status_code, url=str(r.url),
                                headers=dict(r.headers), content=b"".join(chunks)[:cap],
                                truncated=truncated)
            except (httpx.HTTPError, OSError) as exc:
                return _failed(url, f"{type(exc).__name__}: {exc}")
            finally:
                self.in_flight -= 1

    async def get(self, url: str, **kw: Any) -> Resp:
        return await self.request("GET", url, **kw)

    async def post(self, url: str, **kw: Any) -> Resp:
        return await self.request("POST", url, **kw)

    async def get_json(self, url: str, **kw: Any) -> Any:
        r = await self.get(url, **kw)
        return r.json() if r.ok else None
