"""Serve the real OpenAtlas app against a fake web, for the GUI e2e check (no network)."""

import hashlib
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


KIWIX = "https://download.kiwix.org/zim/wikipedia/"


def build_zim() -> bytes:
    """A real, tiny Wikipedia-style ZIM (needs ``pip install libzim``), padded to ~3 MB."""
    import os
    import tempfile

    from libzim.writer import Creator, Hint, Item, StringProvider

    class Page(Item):
        def __init__(self, path, title, html):
            super().__init__()
            self.p, self.t, self.h = path, title, html

        def get_path(self): return self.p
        def get_title(self): return self.t
        def get_mimetype(self): return "text/html"
        def get_contentprovider(self): return StringProvider(self.h)
        def get_hints(self): return {Hint.FRONT_ARTICLE: True}

    filler = os.urandom(1_500_000).hex()  # incompressible, so the download takes a moment
    fd, path = tempfile.mkstemp(suffix=".zim")
    os.close(fd)
    os.unlink(path)
    with Creator(path).config_indexing(False, "eng") as c:
        c.set_mainpath("Offline_reading")
        c.add_item(Page("Offline_reading", "Offline reading",
                        "<p>Offline reading lets you read web content without a connection. " * 20
                        + "</p>"))
        c.add_item(Page("Padding", "Padding", f"<p>{filler}</p>"))
        for k, v in {"Title": "Wikipedia (test)", "Name": "wikipedia_en_test", "Language": "eng",
                     "Creator": "t", "Publisher": "t", "Date": "2026-05-01", "Description": "t"}.items():
            c.add_metadata(k, v)
    with open(path, "rb") as fh:
        data = fh.read()
    os.unlink(path)
    return data


ZIM = build_zim()
OPDS = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><entry>
 <id>urn:uuid:aaaaaaaa-0000-0000-0000-000000000001</id><title>Wikipedia (test)</title>
 <summary>Offline encyclopedia, no pictures</summary><language>eng</language>
 <name>wikipedia_en_test</name><flavour>nopic</flavour><articleCount>1234</articleCount>
 <updated>2026-05-01T00:00:00Z</updated>
 <link type="application/x-zim" href="{KIWIX}wikipedia_en_test_nopic_2026-05.zim.meta4" length="{len(ZIM)}"/>
</entry></feed>"""


def kiwix(req: httpx.Request) -> httpx.Response:
    url = str(req.url)
    if url.startswith("https://library.kiwix.org/catalog/v2/entries"):
        return httpx.Response(200, content=OPDS.encode())
    if url.endswith(".meta4"):
        xml = ('<metalink xmlns="urn:ietf:params:xml:ns:metalink"><file name="f"><hash type="sha-256">'
               f'{hashlib.sha256(ZIM).hexdigest()}</hash><url>{url[:-6]}</url></file></metalink>')
        return httpx.Response(200, content=xml.encode())
    if url.endswith(".zim"):
        return httpx.Response(200, content=ZIM)
    return httpx.Response(404)


def synthetic_brain(n: int) -> None:
    """Seed topics from the real taxonomy (tagged like the ingester does), for the brain graph."""
    import random

    from openatlas.kb import store, taxonomy

    rnd = random.Random(7)
    seeds = taxonomy.parse()
    docs = []
    for i, s in enumerate(seeds[:n]):
        tier = 0 if i % 5 else rnd.choice([1, 2, 3])
        tags = list(s["namespaces"]) + (["seed"] if tier == 0 else []) + [f"tier:{tier}"]
        docs.append({"key": f"wikipedia:{s['title']}", "source": "wikipedia", "title": s["title"],
                     "text": f"{s['title']} is a field of study in {', '.join(s['divisions'])}. " * 3,
                     "url": "https://en.wikipedia.org/wiki/" + s["title"].replace(" ", "_"),
                     "license": "CC BY-SA 4.0", "tags": tags})
    store.upsert_many(docs)


def handler(req: httpx.Request) -> httpx.Response:
    url = str(req.url)
    if url.startswith("https://keybase.io/_/api/1.0/user/lookup.json"):
        return httpx.Response(200, json=KEYBASE)
    if url.startswith("https://api.github.com/users/jdoe_42"):
        return httpx.Response(200, json=GITHUB)
    return httpx.Response(404, content=b"not found")


if __name__ == "__main__":
    from openatlas.kb import evaluate, library

    net_client.TRANSPORT = httpx.MockTransport(handler)
    library.TRANSPORT = httpx.MockTransport(kiwix)
    evaluate.load_fixture_corpus()  # a small brain with look-alike articles
    synthetic_brain(1500)  # ...plus real taxonomy seeds, so the brain graph has something to show
    robots._fetch_text = lambda *a, **k: None
    sys.exit(serve(port=8611, open_browser=False))
