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
    monkeypatch.setattr(library, "TRANSPORT", httpx.MockTransport(
        lambda req: httpx.Response(200, content=OPDS.encode())))
    assert library.catalog()[0]["status"] == "new"
    library.enqueue(book("wikipedia_en_all_nopic_2026-01.zim"))
    library._set(1, status="ingested")
    assert library.catalog()[0]["status"] == "update"  # newer version available
    rid = library.enqueue(library.parse_catalog(OPDS)[0])
    assert library.catalog()[0]["status"] == "resume"  # half-downloaded: offer to carry on
    library._set(rid, status="ready")
    assert library.catalog()[0]["status"] == "have"


# ------------------------------------------------------------------ downloads
def _entry(i: int, filename: str, title: str = "Wikipedia", lang: str = "eng") -> str:
    name, flavour, _ = filename.rsplit("_", 2)  # like Kiwix: name wikipedia_en_all + flavour nopic
    return (f"<entry><id>urn:uuid:{i:08d}-0000-0000-0000-000000000000</id><title>{title}</title>"
            f"<summary>Offline {title}</summary><language>{lang}</language><name>{name}</name>"
            f"<flavour>{flavour}</flavour><updated>2026-01-01T00:00:00Z</updated>"
            f'<link type="application/x-zim" href="{KIWIX}{filename}.meta4" length="{1000 + i}"/></entry>')


class FakeCatalog:
    """library.kiwix.org stand-in: like the real server, ``q`` only searches titles and
    summaries (never file names) and results come in pages of ``count`` from ``start``."""

    def __init__(self, entries):
        self.entries, self.requests = list(enumerate(entries)), []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        p = req.url.params
        self.requests.append(dict(p))
        hits = [(i, e) for i, e in self.entries
                if (not p.get("q") or p["q"].lower() in ("offline " + e[1]).lower())
                and (not p.get("lang") or p["lang"] == e[2])]
        start, count = int(p.get("start", 0)), int(p.get("count", 10))
        body = "".join(_entry(i, *e) for i, e in hits[start:start + count])
        return httpx.Response(200, content=f'<feed xmlns="http://www.w3.org/2005/Atom">{body}</feed>'.encode())


def big_catalog():
    """150 Wikipedia books; the full English ones only appear on the second page."""
    filler = [(f"wikipedia_en_topic{i}_nopic_2026-07.zim", "Wikipedia", "eng") for i in range(120)]
    wanted = [(f"wikipedia_en_all_{f}_{v}.zim", "Wikipedia", "eng")
              for f in ("maxi", "nopic", "mini") for v in ("2026-03", "2026-06")]
    french = [("wikipedia_fr_all_nopic_2026-06.zim", "Wikipédia", "fra")]
    other = [(f"gutenberg_en_all_{i}_2026-01.zim", "Project Gutenberg", "eng") for i in range(23)]
    return FakeCatalog([(fn, t, lg) for fn, t, lg in filler + wanted + french + other])


def test_get_by_name_finds_the_newest_file_even_past_the_first_page(monkeypatch):
    fake = big_catalog()
    monkeypatch.setattr(library, "TRANSPORT", httpx.MockTransport(fake))
    b = library.resolve("wikipedia_en_all_nopic")
    assert b["filename"] == "wikipedia_en_all_nopic_2026-06.zim"
    assert fake.requests[0]["q"] == "wikipedia" and fake.requests[0]["lang"] == "eng"
    assert any(r["start"] != "0" for r in fake.requests)  # it paged
    assert library.resolve("wikipedia_en_all_nopic_2026-03.zim")["version"] == "2026-03"
    assert library.resolve("wikipedia_fr_all_nopic")["language"] == "fra"  # language from the name


def test_get_with_an_ambiguous_or_unknown_name_says_what_to_pick(monkeypatch):
    monkeypatch.setattr(library, "TRANSPORT", httpx.MockTransport(big_catalog()))
    with pytest.raises(library.NotFound) as exc:
        library.resolve("wikipedia_en_all")
    assert exc.value.choices == ["wikipedia_en_all_maxi", "wikipedia_en_all_mini", "wikipedia_en_all_nopic"]
    with pytest.raises(library.NotFound) as exc:
        library.resolve("wikipedia_en_nothing_like_this")
    assert exc.value.choices == []


def test_catalog_search_by_words_or_name(monkeypatch):
    monkeypatch.setattr(library, "TRANSPORT", httpx.MockTransport(big_catalog()))
    books, total = library.find_books("wikipedia", "eng", 40)
    assert len(books) == 40 and total >= 40
    books, total = library.find_books("wikipedia_en_all", "eng", 60)
    assert total == 6 and {b["book"] for b in books} == {
        "wikipedia_en_all_maxi", "wikipedia_en_all_mini", "wikipedia_en_all_nopic"}


def test_cli_get_and_catalog_by_name(monkeypatch, capsys):
    from openatlas import cli

    monkeypatch.setattr(library, "TRANSPORT", httpx.MockTransport(big_catalog()))
    monkeypatch.setattr(library, "enqueue", lambda b: (_ for _ in ()).throw(library.Duplicate("already have it")))
    assert cli.main(["kb", "library", "get", "wikipedia_en_all_nopic"]) == 0
    assert "already have it" in capsys.readouterr().out
    assert cli.main(["kb", "library", "get", "wikipedia_en_all"]) == 1
    out = capsys.readouterr().out
    assert "openatlas kb library get wikipedia_en_all_nopic" in out
    assert cli.main(["kb", "library", "catalog", "wikipedia_en_all"]) == 0
    out = capsys.readouterr().out
    assert "wikipedia_en_all_nopic_2026-06.zim" in out and "MB" in out and "0.0 GB" not in out


def test_cli_pause_resume_take_an_optional_id(capsys):
    from openatlas import cli

    rid = library.enqueue(book("wikipedia_en_x_2026-01.zim"))
    assert cli.main(["kb", "library", "pause", str(rid)]) == 0
    assert library.get(rid)["status"] == "paused"
    assert cli.main(["kb", "library", "pause"]) == 0 and store.get_meta("library_paused")
    assert cli.main(["kb", "library", "verify", "99"]) == 1
    assert "no book with id 99" in capsys.readouterr().out


def test_unwritable_data_dir_gives_a_clear_message(monkeypatch, tmp_path, capsys):
    from openatlas import cli
    from openatlas.config import Config

    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")  # a file where the folder should be: mkdir fails like an unmounted drive
    monkeypatch.setattr(Config.files, "brain_dir", blocker / "brain")
    monkeypatch.setenv("OPENATLAS_DATA_DIR", str(blocker))
    store.reset_init_cache()
    assert cli.main(["kb", "library", "list"]) == 2
    err = capsys.readouterr().err
    assert f"OPENATLAS_DATA_DIR={blocker}" in err and "openatlas kb where" in err


def test_where_lists_mounted_drives_with_a_ready_line(monkeypatch, tmp_path):
    from collections import namedtuple

    import psutil

    Part = namedtuple("Part", "device mountpoint fstype opts")
    parts = [Part("/dev/sdb1", "/run/media/me/BigHDD", "ext4", "rw"),
             Part("/dev/loop0", "/run/media/me/cdrom", "iso9660", "ro"),
             Part("/dev/sda1", "/", "btrfs", "rw")]
    monkeypatch.setattr(psutil, "disk_partitions", lambda all=False: parts)
    monkeypatch.setattr("shutil.disk_usage", lambda p: type("U", (), {"free": 500e9})())
    monkeypatch.setattr("os.access", lambda p, m: True)
    w = store.where()
    assert [d["mount"] for d in w["drives"]] == ["/run/media/me/BigHDD"]
    assert w["drives"][0]["export"] == "export OPENATLAS_DATA_DIR='/run/media/me/BigHDD/openatlas'"


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


# ------------------------------------------------- closed the terminal mid-download
def _half_done(monkeypatch, name="wikipedia_en_all_nopic_2026-06.zim"):
    """A download interrupted by closing the terminal: row left 'downloading', .part kept."""
    data = bytes(range(256)) * 20_000
    fake = FakeKiwix({name: data})
    entry = _entry(1, name).replace(f'length="{1001}"', f'length="{len(data)}"')
    feed = f'<feed xmlns="http://www.w3.org/2005/Atom">{entry}</feed>'.encode()

    def handler(req):
        if str(req.url).startswith(library.CATALOG):
            return httpx.Response(200, content=feed)
        return fake(req)

    monkeypatch.setattr(library, "TRANSPORT", httpx.MockTransport(handler))
    rid = library.enqueue(library.resolve(name[:-len("_2026-06.zim")]))
    Path(library.get(rid)["path"] + ".part").write_bytes(data[:777_777])
    library._set(rid, status="downloading", bytes_done=777_777)
    return rid, data, fake


@pytest.mark.parametrize("argv", [["get", "wikipedia_en_all_nopic", "--no-ingest"], ["resume"], ["resume", "1"]])
def test_closed_terminal_download_resumes(monkeypatch, capsys, argv):
    from openatlas import cli

    rid, data, fake = _half_done(monkeypatch)
    assert rid == 1
    monkeypatch.setattr(library, "libzim_available", lambda: False)  # just the download here
    assert cli.main(["kb", "library", *argv]) == 0
    row = library.get(rid)
    assert row["status"] == "ready" and row["note"] == "verified", capsys.readouterr().out
    assert ("bytes=777777-" in [r for _, r in fake.requests])  # continued, not restarted
    assert Path(row["path"]).read_bytes() == data
    assert "not downloading" not in capsys.readouterr().out


def test_finished_book_is_still_refused(monkeypatch, capsys):
    from openatlas import cli

    rid, _, _ = _half_done(monkeypatch)
    library._set(rid, status="ingested")
    assert cli.main(["kb", "library", "get", "wikipedia_en_all_nopic"]) == 0
    assert "not downloading: already in library" in capsys.readouterr().out


def test_second_process_cannot_append_to_the_same_part_file(monkeypatch):
    rid, _, _ = _half_done(monkeypatch)
    with library._exclusive(Path(library.get(rid)["path"])) as mine:
        assert mine
        assert library.download(rid) == "busy"  # another Atlas window holds it
    assert library.download(rid) == "ready"


def test_app_resumes_a_left_over_download(monkeypatch):
    from fastapi.testclient import TestClient

    from openatlas.kb import kiwix
    from openatlas.web.server import create_app

    rid, _, _ = _half_done(monkeypatch)
    started = []
    monkeypatch.setattr(kiwix, "binary", lambda: None)
    monkeypatch.setattr(library, "start_background", lambda: started.append(1) or True)
    with TestClient(create_app()) as c:
        c.get("/api/library")
    assert started
    library._set(rid, status="paused")
    store.set_meta("library_paused", True)
    started.clear()
    with TestClient(create_app()) as c:
        c.get("/api/library")
    assert not started  # paused on purpose: leave it


def test_progress_line_shows_eta():
    line = library.progress_line({"filename": "w.zim", "bytes_done": 12_400_000_000,
                                  "size": 52_700_000_000, "speed": 8_100_000, "status": "downloading"})
    assert "12.4 GB / 52.7 GB" in line and "23.5%" in line and "ETA 1h22m" in line


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
        r = c.post("/api/library/get", json=b)  # still unfinished: resumes, not refused
        assert r.status_code == 200 and r.json()["resumed"] is True
        library._set(r.json()["id"], status="ready")
        r = c.post("/api/library/get", json=b)
        assert r.status_code == 409 and "already" in r.json()["detail"]
        library._set(r_id := library.rows()[0]["id"], status="queued")
        assert c.post("/api/library/get", json={**b, "url": "https://evil.example/x.zim"}).status_code == 422
        state = c.get("/api/library").json()
        assert state["books"][0]["status"] == "queued" and state["kiwix"]["installed"] is False
        assert r_id == state["books"][0]["id"]
        r = c.get("/kiwix/")
        assert r.status_code == 503 and "dnf install kiwix-tools" in r.text
        assert c.post(f"/api/library/{state['books'][0]['id']}/pause").json()["status"] == "paused"


def test_unreadable_file_is_marked_failed_not_crashing(monkeypatch):
    serve(monkeypatch, {"wikipedia_en_test_2026-01.zim": b"not a zim" * 1000})
    rid = library.enqueue(book("wikipedia_en_test_2026-01.zim", 9000))
    library.work()  # downloads (checksum OK), then tries to feed it in: must not raise
    row = library.get(rid)
    assert row["status"] == "failed" and "not a readable ZIM" in row["note"]
