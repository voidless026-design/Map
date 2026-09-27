"""Kiwix library: whole offline encyclopedias (ZIM files) for the brain - never twice.

* **Catalog** - the official Kiwix OPDS feed (public, free, no key).
* **Downloads** - multi-GB, streamed to disk, resumable with HTTP Range (a ``.part`` file),
  SHA-256 checked against Kiwix's published checksum before the file becomes live. One
  download at a time, pause/resume/cancel, disk-space checked up front.
* **No duplicates** - a file with the same UUID, file name or checksum, or the same book at
  the same or a newer version, is refused. A *newer* version of a book you have is an update:
  it downloads, verifies and feeds the brain, and only then the old file is deleted.
* **Feeding the brain** - articles are read with ``libzim`` (``pip install libzim``) and stored
  under the same keys the Wikipedia API uses, so nothing is stored twice; redirects become
  search aliases. Resumable, batched, low priority, honours the pause flag and disk floor.

Network: plain unauthenticated HTTPS to library.kiwix.org / download.kiwix.org with the honest
OpenAtlas User-Agent (no cookies, no auth). Tests install ``TRANSPORT`` (an httpx mock).
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import threading
import time
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import httpx

from openatlas.config import Config
from openatlas.kb import store
from openatlas.logger import get_logger

log = get_logger("openatlas.library")

CATALOG = "https://library.kiwix.org/catalog/v2/entries"
TRANSPORT: Optional[httpx.BaseTransport] = None  # tests install an httpx.MockTransport
CHUNK = 1 << 20            # 1 MiB network reads
BATCH = 500                # articles per brain transaction
MARGIN_GB = 5.0            # free space kept on top of the file size
_FILE = re.compile(r"^(?P<book>.+?)_(?P<version>\d{4}-\d{2})\.zim$")
_ATOM = {"a": "http://www.w3.org/2005/Atom", "dc": "http://purl.org/dc/terms/"}
_ACTIVE = ("queued", "downloading", "paused")


class Duplicate(Exception):
    """Refused: the library already has this file (or a newer version of the book)."""


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def library_dir() -> Path:
    override = store._OVERRIDE.get()  # the doctor's throwaway brain gets a throwaway library
    d = (override.parent if override is not None else Path(Config.files.brain_dir).parent) / "library"
    return store.ensure_dir(d)


def _client(timeout: float = 30.0) -> httpx.Client:
    return httpx.Client(headers={"User-Agent": Config.services.user_agent}, timeout=timeout,
                        follow_redirects=True, transport=TRANSPORT)


def is_kiwix_url(url: str) -> bool:
    """Downloads are limited to Kiwix's own servers (https)."""
    from urllib.parse import urlsplit

    u = urlsplit(url)
    host = (u.hostname or "").lower()
    return u.scheme == "https" and (host == "kiwix.org" or host.endswith(".kiwix.org"))


def split_filename(filename: str) -> Tuple[str, str]:
    """``wikipedia_en_all_nopic_2026-01.zim`` -> (``wikipedia_en_all_nopic``, ``2026-01``)."""
    m = _FILE.match(Path(filename).name)
    return (m["book"], m["version"]) if m else (Path(filename).stem, "")


def free_gb(path: Optional[Path] = None) -> float:
    return shutil.disk_usage(path or library_dir()).free / 1e9


def rows(status: Optional[str] = None) -> List[Dict[str, Any]]:
    with store.connect() as con:
        q = "SELECT * FROM library" + (" WHERE status=?" if status else "") + " ORDER BY id"
        return [dict(r) for r in con.execute(q, (status,) if status else ())]


def get(row_id: int) -> Optional[Dict[str, Any]]:
    with store.connect() as con:
        r = con.execute("SELECT * FROM library WHERE id=?", (row_id,)).fetchone()
        return dict(r) if r else None


def _set(row_id: int, **fields: Any) -> None:
    fields["updated_at"] = store.now()
    cols = ", ".join(f"{k}=?" for k in fields)
    with store.connect() as con:
        con.execute(f"UPDATE library SET {cols} WHERE id=?", [*fields.values(), row_id])


# --------------------------------------------------------------------------- #
# catalog (OPDS)
# --------------------------------------------------------------------------- #
def parse_catalog(xml_text: str) -> List[Dict[str, Any]]:
    """Books from a Kiwix OPDS v2 Atom feed."""
    root = ET.fromstring(xml_text)
    out = []
    for e in root.findall("a:entry", _ATOM):
        def t(tag: str) -> str:
            el = e.find(tag, _ATOM)
            return (el.text or "").strip() if el is not None and el.text else ""
        link = next((ln for ln in e.findall("a:link", _ATOM)
                     if ln.get("type") == "application/x-zim"), None)
        if link is None:
            continue
        href = link.get("href", "")
        url = href[:-len(".meta4")] if href.endswith(".meta4") else href
        filename = url.rsplit("/", 1)[-1]
        book, version = split_filename(filename)
        out.append({
            "uuid": t("a:id").replace("urn:uuid:", ""), "title": t("a:title"),
            "summary": t("a:summary"), "language": t("a:language"), "name": t("a:name"),
            "flavour": t("a:flavour"), "category": t("a:category"),
            "articles": int(t("a:articleCount") or 0), "size": int(link.get("length") or 0),
            "url": url, "meta4": href if href.endswith(".meta4") else url + ".meta4",
            "filename": filename, "book": book, "version": version or t("a:updated")[:7],
        })
    return out


def fetch_catalog(q: str = "", lang: str = "eng", count: int = 40) -> List[Dict[str, Any]]:
    params = {"count": str(count)}
    if q:
        params["q"] = q
    if lang:
        params["lang"] = lang
    with _client() as c:
        r = c.get(CATALOG, params=params)
        r.raise_for_status()
        return parse_catalog(r.text)


PAGE = 100
MAX_ENTRIES = 1000
# ISO 639-1 codes used in Kiwix file names -> the ISO 639-3 codes the catalog filters on
_LANG3 = {"en": "eng", "fr": "fra", "de": "deu", "es": "spa", "it": "ita", "pt": "por", "ru": "rus",
          "zh": "zho", "ja": "jpn", "ar": "ara", "nl": "nld", "pl": "pol", "sv": "swe", "uk": "ukr",
          "fa": "fas", "tr": "tur", "ko": "kor", "hi": "hin", "he": "heb", "cs": "ces", "fi": "fin",
          "vi": "vie", "id": "ind", "el": "ell", "hu": "hun", "ro": "ron", "da": "dan", "no": "nor"}


class NotFound(LookupError):
    """No catalog book matches; ``choices`` lists the nearest names (maybe several to pick from)."""

    def __init__(self, msg: str, choices: Optional[List[str]] = None):
        super().__init__(msg)
        self.choices = choices or []


def _name_like(q: str) -> bool:
    return "_" in q or q.endswith(".zim")


def _names(b: Dict[str, Any]) -> List[str]:
    full = f"{b['name']}_{b['flavour']}" if b.get("flavour") and not b["name"].endswith(b["flavour"]) \
        else b.get("name", "")
    return [n.lower() for n in (b["filename"], b["book"], b.get("name", ""), full, b.get("uuid", "")) if n]


def find_books(q: str = "", lang: str = "eng", limit: int = 40) -> Tuple[List[Dict[str, Any]], int]:
    """Search the catalog the way people type: words, or a book/file name like
    ``wikipedia_en_all_nopic``. Kiwix's own search only matches titles and descriptions, so a
    name is searched by its first word and language, then matched on file names here.
    Pages through the results (the server returns at most ``count`` per request).
    Returns (books, total matching)."""
    q = q.strip()
    server_q, want, found = q, "", []
    if _name_like(q):
        want = split_filename(q)[0].lower() if q.endswith(".zim") else q.lower()
        parts = want.split("_")
        server_q = parts[0]
        if len(parts) > 1:  # the name says which language (wikipedia_fr_...): trust it
            lang = _LANG3.get(parts[1].split("-")[0], lang)
    with _client() as c:
        # a local title (e.g. "Wikipédia") can hide a name from the word search: then scan the language
        for sq in ([server_q, ""] if want and server_q else [server_q]):
            start = 0
            while start < MAX_ENTRIES:
                params = {"count": str(PAGE), "start": str(start)}
                if sq:
                    params["q"] = sq
                if lang:
                    params["lang"] = lang
                r = c.get(CATALOG, params=params)
                r.raise_for_status()
                page = parse_catalog(r.text)
                found += [b for b in page if not want or any(n.startswith(want) for n in _names(b))]
                if len(page) < PAGE or (not want and limit and len(found) >= limit):
                    break
                start += PAGE
            if found or not lang:
                break
    return (found[:limit] if limit else found), len(found)


def resolve(name: str, lang: str = "") -> Dict[str, Any]:
    """The newest catalog book whose file/book name, catalog name or uuid is exactly ``name``.
    Several different books starting with ``name`` -> NotFound listing them to pick from."""
    books, _ = find_books(name, lang, 0)
    low = name.lower()
    key = split_filename(low)[0] if low.endswith(".zim") else low
    same_file = [b for b in books if b["filename"].lower() == low]
    same_book = same_file or [b for b in books if b["book"].lower() == key]
    if not same_book:  # catalog name / uuid: fine only if it means one book
        same_book = [b for b in books if key in _names(b)]
        if len({b["book"] for b in same_book}) > 1:
            same_book = []
    if same_book:
        return sorted(same_book, key=lambda b: b["version"])[-1]
    choices = sorted({b["book"] for b in books})
    if choices:
        raise NotFound(f"'{name}' matches {len(choices)} books - pick one", choices)
    raise NotFound(f"nothing in the Kiwix catalog is called '{name}'")


def annotate(books: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Mark each catalog book new / update / have (with the duplicate reason)."""
    for b in books:
        try:
            dup = check_duplicate(b)
            b["status"] = "update" if dup else "new"
            b["replaces"] = dup
        except Duplicate as exc:
            b["status"], b["reason"] = "have", str(exc)
    return books


def catalog(q: str = "", lang: str = "eng", count: int = 40) -> List[Dict[str, Any]]:
    """Catalog entries annotated with what the library already has."""
    return annotate(find_books(q, lang, count)[0])


def parse_meta4(xml_text: str) -> Dict[str, Any]:
    """SHA-256, size and mirror URLs from a Metalink v4 file."""
    root = ET.fromstring(xml_text)
    ns = {"m": "urn:ietf:params:xml:ns:metalink"}
    f = root.find("m:file", ns)
    if f is None:
        return {}
    sha = next((h.text.strip().lower() for h in f.findall("m:hash", ns)
                if (h.get("type") or "").lower() in ("sha-256", "sha256") and h.text), "")
    size = f.findtext("m:size", default="0", namespaces=ns)
    urls = [u.text.strip() for u in sorted(f.findall("m:url", ns),
                                           key=lambda u: int(u.get("priority") or 99)) if u.text]
    return {"sha256": sha, "size": int(size or 0), "urls": urls}


def expected_checksum(book: Dict[str, Any]) -> Tuple[str, List[str]]:
    """(sha256, mirror urls) from the .meta4, falling back to the .sha256 file."""
    with _client() as c:
        try:
            r = c.get(book["meta4"])
            if r.status_code == 200:
                m = parse_meta4(r.text)
                if m.get("sha256"):
                    return m["sha256"], m.get("urls") or [book["url"]]
        except (httpx.HTTPError, ET.ParseError) as exc:
            log.debug("meta4 unavailable for %s: %s", book["filename"], exc)
        r = c.get(book["url"] + ".sha256")
        if r.status_code == 200 and re.match(r"^[0-9a-fA-F]{64}", r.text.strip()):
            return r.text.strip()[:64].lower(), [book["url"]]
    return "", [book["url"]]


# --------------------------------------------------------------------------- #
# duplicate rules
# --------------------------------------------------------------------------- #
def check_duplicate(book: Dict[str, Any]) -> Optional[int]:
    """Raise :class:`Duplicate` if we have it; return the id of an OLDER version it replaces."""
    adopt_existing()
    replaces = None
    for r in rows():
        if r["status"] in ("failed", "cancelled"):
            continue
        if (book.get("uuid") and r["uuid"] == book["uuid"]) or r["filename"] == book["filename"] \
                or (book.get("sha256") and r["sha256"] == book.get("sha256")):
            raise Duplicate(f"already in library: {r['filename']} ({r['status']})")
        if r["book"] == book["book"]:
            if r["version"] >= book["version"]:
                raise Duplicate(f"you already have {r['filename']} (same or newer version)")
            if r["status"] in _ACTIVE:
                raise Duplicate(f"{r['filename']} of this book is still downloading")
            replaces = r["id"]
    return replaces


def enqueue(book: Dict[str, Any]) -> int:
    """Add a catalog book to the download queue (after the duplicate check)."""
    if not is_kiwix_url(book.get("url", "")) or not _FILE.match(book.get("filename", "")) \
            or "/" in book["filename"] or book["filename"].startswith("."):
        raise ValueError("only .zim files from https://*.kiwix.org can be downloaded")
    replaces = check_duplicate(book)
    path = library_dir() / book["filename"]
    with store.connect() as con:
        cur = con.execute(
            "INSERT INTO library(uuid, book, name, flavour, version, title, language, filename, "
            "path, url, size, articles, status, replaces, note, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (book.get("uuid"), book["book"], book.get("name"), book.get("flavour"), book["version"],
             book.get("title"), book.get("language"), book["filename"], str(path), book["url"],
             book.get("size", 0), book.get("articles", 0), "queued", replaces,
             "update: replaces an older version" if replaces else "", store.now()))
        row_id = int(cur.lastrowid)
    store.set_meta(f"library_meta4:{row_id}", book.get("meta4", ""))
    return row_id


def adopt_existing() -> List[int]:
    """Register .zim files copied into the library folder by hand (so they can't be re-downloaded)."""
    known = {Path(r["path"]).name for r in rows()}
    added = []
    for f in sorted(library_dir().glob("*.zim")):
        if f.name in known:
            continue
        book, version = split_filename(f.name)
        info = zim_info(f)
        with store.connect() as con:
            dup = con.execute("SELECT id FROM library WHERE uuid=? AND uuid IS NOT NULL AND "
                              "status NOT IN ('failed','cancelled')", (info.get("uuid"),)).fetchone()
            if dup:
                continue  # same content under another name: leave it alone, never re-register
            cur = con.execute(
                "INSERT INTO library(uuid, book, name, flavour, version, title, language, filename, "
                "path, size, articles, status, note, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (info.get("uuid"), book, info.get("name"), info.get("flavour"), version,
                 info.get("title") or f.stem, info.get("language"), f.name, str(f), f.stat().st_size,
                 info.get("articles", 0), "ready", "added from the library folder", store.now()))
            added.append(int(cur.lastrowid))
    return added


# --------------------------------------------------------------------------- #
# download (resumable, verified)
# --------------------------------------------------------------------------- #
def _hash_file(path: Path, h: Optional[Any] = None) -> Any:
    h = h or hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(8 * CHUNK), b""):
            h.update(block)
    return h


def download(row_id: int, stop: Optional[threading.Event] = None) -> str:
    """Download (or resume) one queued book. Returns the final status."""
    row = get(row_id)
    if row is None:
        return "missing"
    final, part = Path(row["path"]), Path(row["path"] + ".part")
    have = part.stat().st_size if part.exists() else 0
    need_gb = (max(row["size"] - have, 0)) / 1e9 * 1.1 + MARGIN_GB
    if row["size"] and free_gb(final.parent) < need_gb:
        _set(row_id, status="failed", note=f"not enough disk space: need {need_gb:.1f} GB free")
        return "failed"
    book = {**row, "meta4": store.get_meta(f"library_meta4:{row_id}", "") or row["url"] + ".meta4"}
    sha, urls = expected_checksum(book)
    urls = [u for u in urls if u.startswith("https://")] or [row["url"]]  # https mirrors only
    if sha:
        _set(row_id, sha256=sha)
    h = _hash_file(part) if have else hashlib.sha256()  # resume: re-hash what we already have
    _set(row_id, status="downloading", bytes_done=have, note="")
    attempt, url_i = 0, 0
    while True:
        try:
            with _client(timeout=60) as c, c.stream(
                    "GET", urls[url_i % len(urls)],
                    headers={"Range": f"bytes={have}-"} if have else {}) as r:
                if r.status_code == 416:  # nothing left to fetch
                    break
                if r.status_code not in (200, 206):
                    raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
                if have and r.status_code == 200:  # server ignored the range: start over
                    have, h = 0, hashlib.sha256()
                    part.unlink(missing_ok=True)
                total = int(r.headers.get("content-length") or 0) + have
                if total and not row["size"]:
                    _set(row_id, size=total)
                t0, last, since = time.monotonic(), time.monotonic(), have
                with open(part, "ab") as f:
                    for block in r.iter_bytes(CHUNK):
                        f.write(block)
                        h.update(block)
                        have += len(block)
                        now = time.monotonic()
                        if now - last >= 2:
                            speed = (have - since) / max(now - t0, 1e-6)
                            _set(row_id, bytes_done=have, speed=round(speed))
                            last = now
                            cur = get(row_id) or {}
                            if cur.get("status") in ("paused", "cancelled") or (stop and stop.is_set()):
                                return _halt(row_id, part, cur.get("status") or "paused")
            break
        except (httpx.HTTPError, OSError) as exc:
            attempt += 1
            url_i += 1  # next mirror
            if attempt > 5:
                _set(row_id, status="paused", bytes_done=have,
                     note=f"network trouble, will resume: {type(exc).__name__}")
                return "paused"
            time.sleep(min(30, 2 ** attempt) if TRANSPORT is None else 0)
    _set(row_id, bytes_done=have, speed=0)
    if sha and h.hexdigest() != sha:
        part.unlink(missing_ok=True)
        _set(row_id, status="failed", bytes_done=0,
             note="checksum mismatch - corrupted download deleted")
        return "failed"
    part.replace(final)
    info = zim_info(final)
    _set(row_id, status="ready", size=final.stat().st_size, uuid=info.get("uuid") or row["uuid"],
         note="verified" if sha else "no checksum published - size checked only")
    return "ready"


def _halt(row_id: int, part: Path, status: str) -> str:
    if status == "cancelled":
        part.unlink(missing_ok=True)
        _set(row_id, bytes_done=0, speed=0, note="cancelled")
        return "cancelled"
    _set(row_id, status="paused", speed=0)
    return "paused"


def verify(row_id: int) -> Dict[str, Any]:
    """Re-hash a downloaded file and compare with the published checksum."""
    row = get(row_id)
    if not row or not Path(row["path"]).exists():
        return {"ok": False, "reason": "file missing"}
    if not row["sha256"]:
        return {"ok": None, "reason": "no published checksum"}
    got = _hash_file(Path(row["path"])).hexdigest()
    return {"ok": got == row["sha256"], "expected": row["sha256"], "got": got}


# --------------------------------------------------------------------------- #
# feeding the brain (libzim)
# --------------------------------------------------------------------------- #
class _Text(HTMLParser):
    """Fast HTML -> text for article bodies: drops scripts, styles, reference marks, tables."""

    SKIP = {"script", "style", "sup", "noscript", "table", "figure", "nav", "footer"}
    BLOCK = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "br", "tr", "section", "dd", "dt"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: List[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.out.append(data)


def html_to_text(markup: str) -> str:
    p = _Text()
    p.feed(markup)
    text = html.unescape("".join(p.out))
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def libzim_available() -> bool:
    try:
        import libzim  # noqa: F401
        return True
    except ImportError:
        return False


def zim_info(path: Path) -> Dict[str, Any]:
    """UUID + metadata of a ZIM file ({} if libzim is missing or the file is unreadable)."""
    try:
        from libzim.reader import Archive
    except ImportError:
        return {}
    try:
        a = Archive(str(path))

        def meta(k: str) -> str:
            try:
                return bytes(a.get_metadata(k)).decode("utf-8", "replace")
            except (KeyError, RuntimeError):
                return ""
        return {"uuid": str(a.uuid), "title": meta("Title"), "name": meta("Name"),
                "flavour": meta("Flavour"), "language": meta("Language"),
                "articles": a.article_count, "entries": a.entry_count}
    except (RuntimeError, OSError) as exc:
        log.debug("cannot read %s: %s", path, exc)
        return {}


def _iter_entries(archive: Any, start: int) -> Iterator[Tuple[int, Any]]:
    for i in range(start, archive.entry_count):
        try:
            yield i, archive._get_entry_by_id(i)
        except (RuntimeError, KeyError, IndexError):
            continue


def ingest(row_id: int, stop: Optional[threading.Event] = None, *, max_batches: Optional[int] = None) -> str:
    """Feed a verified ZIM into the brain from its cursor. Returns the status."""
    from openatlas.kb import ingest as kb_ingest

    row = get(row_id)
    if row is None:
        return "missing"
    try:
        from libzim.reader import Archive
    except ImportError:
        _set(row_id, note="install libzim to feed this into the brain: pip install libzim")
        return row["status"]
    try:
        archive = Archive(row["path"])
    except (RuntimeError, OSError) as exc:  # not a ZIM / damaged: never let it stall the worker
        _set(row_id, status="failed", note=f"not a readable ZIM file ({exc}) - delete it and re-download")
        return "failed"
    wiki = (row["book"] or "").startswith("wikipedia_")
    lang = (row["language"] or "eng")[:2] if row["language"] else "en"
    lang = {"en": "en", "fr": "fr", "de": "de", "es": "es"}.get(lang, lang)
    licence = "CC BY-SA 4.0 (Wikipedia contributors, via Kiwix)" if wiki else \
        f"see source ({row['title'] or row['book']}, via Kiwix)"
    _set(row_id, status="ingesting", entries=archive.entry_count)
    cursor, done_articles, batches = row["cursor"], row["ingested"], 0
    docs: List[Dict[str, Any]] = []
    aliases: Dict[str, List[str]] = {}
    tags = [f"kiwix:{row['book']}"]

    def key_for(entry_title: str, path: str) -> str:
        return f"wikipedia:{entry_title}" if wiki else f"kiwix:{row['book']}:{path}"

    def flush() -> None:
        nonlocal docs, aliases, done_articles
        done_articles += store.upsert_many(docs, aliases)
        docs, aliases = [], {}
        _set(row_id, cursor=cursor, ingested=done_articles)

    for cursor, entry in _iter_entries(archive, cursor):
        if entry.is_redirect:
            try:
                target = entry.get_redirect_entry()
                aliases.setdefault(key_for(target.title, target.path), []).append(entry.title)
            except (RuntimeError, KeyError):
                pass
            continue
        try:
            item = entry.get_item()
        except (RuntimeError, KeyError):
            continue
        if not item.mimetype.startswith("text/html"):
            continue
        text = html_to_text(bytes(item.content).decode("utf-8", "replace"))
        if len(text) < kb_ingest.MIN_CHARS:
            continue
        url = (f"https://{lang}.wikipedia.org/wiki/{entry.title.replace(' ', '_')}" if wiki
               else f"/kiwix/content/{Path(row['filename']).stem}/{entry.path}")
        docs.append({"key": key_for(entry.title, entry.path), "source": "wikipedia" if wiki else "kiwix",
                     "title": entry.title, "text": text, "url": url, "license": licence, "tags": tags})
        if len(docs) >= BATCH:
            cursor += 1
            flush()
            batches += 1
            why = kb_ingest.resources_ok()
            if (stop and stop.is_set()) or store.get_meta("paused", False) or why or \
                    (max_batches and batches >= max_batches):
                _set(row_id, status="ready", note=why or "paused - resumes where it stopped")
                return "ready"
    cursor = archive.entry_count
    flush()
    checked = "verified · " if row["sha256"] else ""
    _set(row_id, status="ingested", note=f"{checked}{done_articles:,} articles in the brain")
    if row["replaces"]:
        _retire(row["replaces"])
    return "ingested"


def _retire(old_id: int) -> None:
    """After an update verified and ingested: delete the old file (articles were updated in place)."""
    old = get(old_id)
    if old:
        Path(old["path"]).unlink(missing_ok=True)
        with store.connect() as con:
            con.execute("DELETE FROM library WHERE id=?", (old_id,))


# --------------------------------------------------------------------------- #
# the worker: one download at a time, then feed the brain
# --------------------------------------------------------------------------- #
_thread: Optional[threading.Thread] = None
_stop = threading.Event()


def work(stop: Optional[threading.Event] = None) -> None:
    """Process the queue until nothing is left (or ``stop``)."""
    stop = stop or threading.Event()
    while not stop.is_set():
        if store.get_meta("library_paused", False):
            return
        queued = [r for r in rows() if r["status"] in ("queued", "downloading")]
        if queued:
            try:
                download(queued[0]["id"], stop)
            except Exception as exc:  # e.g. disk full mid-write: report, keep the worker alive
                log.warning("download of %s failed: %s", queued[0]["filename"], exc)
                _set(queued[0]["id"], status="paused", note=f"stopped: {type(exc).__name__} - resume to retry")
                return
            continue
        ready = [r for r in rows() if r["status"] in ("ready", "ingesting")
                 and r["cursor"] < (r["entries"] or 1) and libzim_available()]
        if ready and not store.get_meta("paused", False):
            try:
                status = ingest(ready[0]["id"], stop)
            except Exception as exc:  # one bad book must not stop the library
                log.warning("ingest of %s failed: %s", ready[0]["filename"], exc)
                _set(ready[0]["id"], status="failed", note=f"ingest error: {type(exc).__name__}")
                continue
            if status == "ready" and not stop.is_set():
                return  # paused / out of disk: the next start resumes from the cursor
            continue
        return


def start_background() -> bool:
    global _thread
    if _thread and _thread.is_alive():
        return False
    _stop.clear()
    _thread = threading.Thread(target=work, args=(_stop,), name="kiwix-library", daemon=True)
    _thread.start()
    return True


def running() -> bool:
    return bool(_thread and _thread.is_alive())


def control(row_id: int, action: str) -> Dict[str, Any]:
    """pause | resume | cancel one book."""
    row = get(row_id)
    if row is None:
        raise KeyError(row_id)
    if action == "pause" and row["status"] in ("queued", "downloading"):
        _set(row_id, status="paused")
    elif action == "resume" and row["status"] in ("paused", "failed"):
        _set(row_id, status="queued", note="")
        start_background()
    elif action == "cancel" and row["status"] in _ACTIVE + ("failed",):
        _set(row_id, status="cancelled")
        Path(row["path"] + ".part").unlink(missing_ok=True)
    return get(row_id) or {}


def summary() -> Dict[str, Any]:
    books = rows()
    for b in books:
        b["percent"] = round(100 * b["bytes_done"] / b["size"], 1) if b["size"] else 0.0
        b["ingest_percent"] = round(100 * b["cursor"] / b["entries"], 1) if b["entries"] else 0.0
    return {"books": [b for b in books if b["status"] != "cancelled"], "dir": str(library_dir()),
            "free_gb": round(free_gb(), 1), "libzim": libzim_available(), "worker": running(),
            "paused": bool(store.get_meta("library_paused", False))}


def dumps(obj: Any) -> str:  # CLI helper
    return json.dumps(obj, indent=2, default=str)
