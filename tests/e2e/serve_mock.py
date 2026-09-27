"""Serve the real OpenAtlas app against a fake web, for the GUI e2e check (no network)."""

import sys

import httpx

from openatlas.net import client as net_client
from openatlas.utils import robots
from openatlas.web.server import serve

KEYBASE = {"them": [{"basics": {"username": "jdoe_42"}, "profile": {"bio": "security researcher"},
                     "proofs_summary": {"all": [{
                         "proof_type": "github", "nametag": "jdoe_42",
                         "service_url": "https://github.com/jdoe_42",
                         "proof_url": "https://gist.github.com/jdoe_42/1"}]}}]}
GITHUB = {"login": "jdoe_42", "name": "Jane Doe", "html_url": "https://github.com/jdoe_42",
          "location": "Lisbon", "blog": "https://jdoe.example", "public_repos": 12,
          "created_at": "2019-01-01"}


def handler(req: httpx.Request) -> httpx.Response:
    url = str(req.url)
    if url.startswith("https://keybase.io/_/api/1.0/user/lookup.json"):
        return httpx.Response(200, json=KEYBASE)
    if url.startswith("https://api.github.com/users/jdoe_42"):
        return httpx.Response(200, json=GITHUB)
    return httpx.Response(404, content=b"not found")


if __name__ == "__main__":
    net_client.TRANSPORT = httpx.MockTransport(handler)
    robots._fetch_text = lambda *a, **k: None
    sys.exit(serve(port=8611, open_browser=False))
