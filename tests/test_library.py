"""Kiwix library: catalog parsing, verified resumable downloads, duplicate rules, ZIM ingestion."""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest

from openatlas.kb import library, retrieve, store

libzim = pytest.importorskip("libzim")
from libzim.writer import Creator, Hint, Item, StringProvider  # noqa: E402

KIWIX = "https://download.kiwix.org/zim/wikipedia/"


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    from openatlas.config import Config

    monkeypatch.setattr(Config.files, "brain_dir", tmp_path / "brain")
    store.reset_init_cache()
    yield tmp_path
    store.reset_init_cache()


class _Html(Item):
    def __init__(self, path, title, body, mime="text/html"):
        super().__init__()
        self.p, self.t, self.b, self.m = path, title, body, mime

    def get_path(self):
        return self.p

    def get_title(self):
        return self.t

    def get_mimetype(self):
        return self.m

    def get_contentprovider(self):
        return StringProvider(self.b)

    def get_hints(self):
        return {Hint.FRONT_ARTICLE: True}


def make_zim(path: Path, articles: dict, redirects: dict = None, name="wikipedia_en_test") -> Path:
    with Creator(str(path)).config_indexing(False, "eng") as c:
        c.set_mainpath(next(iter(articles)).replace(" ", "_"))
        for title, text in articles.items():
            c.add_item(_Html(title.replace(" ", "_"), title,
                             f"<html><body><p>{text}</p><script>junk()</script></body></html>"))
        c.add_item(_Html("s.css", "", "body{}", "text/css"))
        for src, dst in (redirects or {}).items():
            c.add_redirection(src, src, dst.replace(" ", "_"), {Hint.FRONT_ARTICLE: True})
        for k, v in {"Title": "Test wiki", "Name": name, "Language": "eng", "Creator": "t",
                     "Publisher": "t", "Date": "2026-01-01", "Description": "t"}.items():
            c.add_metadata(k, v)
    return path


LONG = " ".join(["World War II was a global conflict from 1939 to 1945."] * 10)


def book(filename: str, size: int = 0, uuid: str = "") -> dict:
    b, v = library.split_filename(filename)
    return {"uuid": uuid or filename, "title": "Test", "name": b, "flavour": "", "language": "eng",
            "articles": 2, "size": size, "url": KIWIX + filename, "meta4": KIWIX + filename + ".meta4",
            "filename": filename, "book": b, "version": v}


class FakeKiwix:
    """download.kiwix.org stand-in: Range support, .meta4 with SHA-256, request log."""

    def __init__(self, files: dict, wrong_sha: bool = False):
        self.files, self.wrong_sha, self.requests = files, wrong_sha, []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requests.append((str(req.url), req.headers.get("range")))
        name = str(req.url).rsplit("/", 1)[-1]
        if name.endswith(".meta4"):
            data = self.files[name[:-6]]
            sha = "0" * 64 if self.wrong_sha else hashlib.sha256(data).hexdigest()
            xml = (f'<?xml version="1.0"?><metalink xmlns="urn:ietf:params:xml:ns:metalink">'
                   f'<file name="{name[:-6]}"><size>{len(data)}</size><hash type="sha-256">{sha}</hash>'
                   f'<url priority="1">{KIWIX}{name[:-6]}</url></file></metalink>')
            return httpx.Response(200, content=xml.encode())
        data = self.files.get(name)
        if data is None:
            return httpx.Response(404)
        rng = req.headers.get("range")
        if rng:
            start = int(rng.split("=")[1].rstrip("-"))
            return httpx.Response(206, content=data[start:],
                                  headers={"content-length": str(len(data) - start)})
        return httpx.Response(200, content=data, headers={"content-length": str(len(data))})


def serve(monkeypatch, files, **kw) -> FakeKiwix:
    fake = FakeKiwix(files, **kw)
    monkeypatch.setattr(library, "TRANSPORT", httpx.MockTransport(fake))
    return fake


# ------------------------------------------------------------------ catalog
OPDS = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:dc="http://purl.org/dc/terms/">
 <entry>
  <id>urn:uuid:11111111-2222-3333-4444-555555555555</id>
  <title>Wikipedia</title><summary>The free encyclopedia</summary>
  <language>eng</language><name>wikipedia_en_all</name><flavour>nopic</flavour>
  <category>wikipedia</category><articleCount>6900000</articleCount>
  <updated>2026-05-01T00:00:00Z</updated>
  <link rel="http://opds-spec.org/acquisition/open-access" type="application/x-zim"
        href="{KIWIX}wikipedia_en_all_nopic_2026-05.zim.meta4" length="54000000000"/>
 </entry>
</feed>"""


def test_parse_catalog():
    (b,) = library.parse_catalog(OPDS)
    assert b["uuid"] == "11111111-2222-3333-4444-555555555555"
    assert b["filename"] == "wikipedia_en_all_nopic_2026-05.zim" and b["url"].endswith(".zim")
    assert b["book"] == "wikipedia_en_all_nopic" and b["version"] == "2026-05"
    assert b["size"] == 54_000_000_000 and b["articles"] == 6_900_000


def test_catalog_marks_books_you_have(monkeypatch):
    monkeypatch.setattr(library, "fetch_catalog", lambda *a, **k: library.parse_catalog(OPDS))
    assert library.catalog()[0]["status"] == "new"
    library.enqueue(book("wikipedia_en_all_nopic_2026-01.zim"))
    library._set(1, status="ingested")
    assert library.catalog()[0]["status"] == "update"  # newer version available
    library.enqueue(library.parse_catalog(OPDS)[0])
    assert library.catalog()[0]["status"] == "have"


# ------------------------------------------------------------------ downloads
def test_download_verifies_checksum(monkeypatch):
    data = make_zim(Path(store.db_path()).parent / "src.zim", {"World War II": LONG}).read_bytes()
    serve(monkeypatch, {"wikipedia_en_test_2026-01.zim": data})
    rid = library.enqueue(book("wikipedia_en_test_2026-01.zim", len(data)))
    assert library.download(rid) == "ready"
    row = library.get(rid)
    assert row["sha256"] == hashlib.sha256(data).hexdigest() and row["note"] == "verified"
    assert Path(row["path"]).read_bytes() == data and not Path(row["path"] + ".part").exists()
    assert library.verify(rid)["ok"] is True


def test_resume_uses_range_and_gives_identical_file(monkeypatch):
    data = bytes(range(256)) * 20_000  # ~5 MB
    fake = serve(monkeypatch, {"wikipedia_en_test_2026-01.zim": data})
    rid = library.enqueue(book("wikipedia_en_test_2026-01.zim", len(data)))
    part = Path(library.get(rid)["path"] + ".part")
    part.write_bytes(data[:1_234_567])  # an interrupted earlier download
    assert library.download(rid) == "ready"
    assert ("bytes=1234567-" in [r for _, r in fake.requests])
    assert hashlib.sha256(Path(library.get(rid)["path"]).read_bytes()).hexdigest() == \
        hashlib.sha256(data).hexdigest()


def test_checksum_mismatch_deletes_the_file(monkeypatch):
    serve(monkeypatch, {"wikipedia_en_test_2026-01.zim": b"x" * 1000}, wrong_sha=True)
    rid = library.enqueue(book("wikipedia_en_test_2026-01.zim", 1000))
    assert library.download(rid) == "failed"
    row = library.get(rid)
    assert "checksum mismatch" in row["note"]
    assert not Path(row["path"]).exists() and not Path(row["path"] + ".part").exists()


def test_disk_space_is_checked_first(monkeypatch):
    fake = serve(monkeypatch, {})
    monkeypatch.setattr(library, "free_gb", lambda *a: 10.0)
    rid = library.enqueue(book("wikipedia_en_all_maxi_2026-01.zim", 110 * 10**9))
    assert library.download(rid) == "failed"
    assert "disk space" in library.get(rid)["note"] and not fake.requests


def test_only_kiwix_https_urls(monkeypatch):
    b = book("wikipedia_en_test_2026-01.zim")
    for bad in ("https://evil.example/x.zim", "http://download.kiwix.org/zim/x.zim"):
        with pytest.raises(ValueError):
            library.enqueue({**b, "url": bad})
    with pytest.raises(ValueError):
        library.enqueue({**b, "filename": "../../etc/passwd_2026-01.zim"})


# ------------------------------------------------------------------ duplicates
def test_duplicates_are_refused_and_newer_is_an_update():
    old = library.enqueue(book("wikipedia_en_test_2026-01.zim", uuid="u1"))
    for dup in (book("wikipedia_en_test_2026-01.zim", uuid="other"),  # same file name
                {**book("wikipedia_en_test_2025-12.zim"), "uuid": "u9"},  # older version
                {**book("x_2026-01.zim"), "uuid": "u1"}):  # same content id
        with pytest.raises(library.Duplicate):
            library.check_duplicate(dup)
    with pytest.raises(library.Duplicate):  # a newer one while the old is still downloading
        library.check_duplicate(book("wikipedia_en_test_2026-05.zim"))
    library._set(old, status="ingested")
    assert library.check_duplicate(book("wikipedia_en_test_2026-05.zim")) == old


def test_failed_or_cancelled_downloads_can_be_retried():
    rid = library.enqueue(book("wikipedia_en_test_2026-01.zim"))
    library.control(rid, "cancel")
    assert library.check_duplicate(book("wikipedia_en_test_2026-01.zim", uuid="new")) is None


# ------------------------------------------------------------------ feeding the brain
def test_ingest_real_zim_with_aliases_and_no_duplicate_articles(data_dir):
    lib = library.library_dir()
    make_zim(lib / "wikipedia_en_test_2026-01.zim",
             {"World War II": LONG, "Photosynthesis": " ".join(["Plants turn sunlight into energy."] * 12)},
             {"WWII": "World War II"})
    # the same article already learned from the Wikipedia API must be updated, not duplicated
    store.upsert_document(key="wikipedia:World War II", source="wikipedia", title="World War II",
                          text="old api text " * 50, url="u")
    (rid,) = library.adopt_existing()
    assert library.adopt_existing() == []  # never registered twice
    assert library.ingest(rid) == "ingested"
    with store.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM documents WHERE key='wikipedia:World War II'").fetchone()[0] == 1
        text = " ".join(r[0] for r in con.execute("SELECT text FROM chunks"))
    assert "junk()" not in text and "old api text" not in text
    (hit,) = retrieve.search("WWII", use_vectors=False)
    assert hit["title"] == "World War II" and "alias" in hit["why"]
    assert hit["url"] == "https://en.wikipedia.org/wiki/World_War_II"


def test_ingest_resumes_from_cursor(monkeypatch):
    lib = library.library_dir()
    arts = {f"Topic {i}": " ".join([f"Topic {i} is about subject number {i}."] * 12) for i in range(12)}
    make_zim(lib / "wikipedia_en_test_2026-01.zim", arts)
    (rid,) = library.adopt_existing()
    monkeypatch.setattr(library, "BATCH", 5)
    assert library.ingest(rid, max_batches=1) == "ready"  # stopped after one batch
    first = library.get(rid)
    assert 0 < first["cursor"] < first["entries"] and first["ingested"] == 5
    assert library.ingest(rid) == "ingested"
    assert library.get(rid)["ingested"] == 12


def test_update_replaces_old_file_only_after_verify_and_ingest(monkeypatch):
    lib = library.library_dir()
    old_path = make_zim(lib / "wikipedia_en_test_2026-01.zim", {"World War II": LONG})
    (old,) = library.adopt_existing()
    library.ingest(old)
    new_bytes = make_zim(Path(store.db_path()).parent / "n.zim",
                         {"World War II": LONG + " Updated edition."}).read_bytes()
    serve(monkeypatch, {"wikipedia_en_test_2026-05.zim": new_bytes})
    new = library.enqueue(book("wikipedia_en_test_2026-05.zim", len(new_bytes), uuid="new"))
    assert library.get(new)["replaces"] == old
    assert library.download(new) == "ready"
    assert old_path.exists()  # not deleted before the new one is fed into the brain
    assert library.ingest(new) == "ingested"
    assert not old_path.exists() and library.get(old) is None
    with store.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1


def test_html_to_text_drops_noise():
    t = library.html_to_text("<p>Hello <b>world</b><sup>[1]</sup></p><table><tr><td>box</td></tr>"
                             "</table><script>x()</script><p>Second &amp; last</p>")
    assert t == "Hello world\n\nSecond & last"


# ------------------------------------------------------------------ web
def test_web_library_api(monkeypatch):
    from fastapi.testclient import TestClient

    from openatlas.kb import kiwix
    from openatlas.web.server import create_app

    monkeypatch.setattr(kiwix, "binary", lambda: None)
    monkeypatch.setattr(library, "start_background", lambda: True)
    with TestClient(create_app()) as c:
        b = book("wikipedia_en_test_2026-01.zim")
        assert c.post("/api/library/get", json=b).status_code == 200
        r = c.post("/api/library/get", json=b)
        assert r.status_code == 409 and "already" in r.json()["detail"]
        assert c.post("/api/library/get", json={**b, "url": "https://evil.example/x.zim"}).status_code == 422
        state = c.get("/api/library").json()
        assert state["books"][0]["status"] == "queued" and state["kiwix"]["installed"] is False
        r = c.get("/kiwix/")
        assert r.status_code == 503 and "dnf install kiwix-tools" in r.text
        assert c.post(f"/api/library/{state['books'][0]['id']}/pause").json()["status"] == "paused"


def test_unreadable_file_is_marked_failed_not_crashing(monkeypatch):
    serve(monkeypatch, {"wikipedia_en_test_2026-01.zim": b"not a zim" * 1000})
    rid = library.enqueue(book("wikipedia_en_test_2026-01.zim", 9000))
    library.work()  # downloads (checksum OK), then tries to feed it in: must not raise
    row = library.get(rid)
    assert row["status"] == "failed" and "not a readable ZIM" in row["note"]
