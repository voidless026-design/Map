"""Document Intelligence: read your PDFs, Word files, text and web pages; answer with page cites.

Only folders you allow are readable (default: ~/Documents, ~/Downloads, ~/Desktop and
E.V's own uploads folder). Set ``OPENATLAS_EV_DOC_ROOTS`` (``:``-separated) to change that.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from openatlas.ev import db
from openatlas.ev.tools import tool

SUPPORTED = (".pdf", ".docx", ".txt", ".md", ".markdown", ".html", ".htm", ".csv", ".json", ".rst")
MAX_BYTES = 80 * 1024 * 1024
MAX_PAGES = 3000
_WORD = re.compile(r"[a-z0-9]{3,}")


def uploads_dir() -> Path:
    d = db.ev_dir() / "documents"
    d.mkdir(parents=True, exist_ok=True)
    return d


def roots() -> List[Path]:
    env = os.getenv("OPENATLAS_EV_DOC_ROOTS")
    if env:
        base = [Path(p).expanduser() for p in env.split(os.pathsep) if p]
    else:
        home = Path.home()
        base = [home / "Documents", home / "Downloads", home / "Desktop"]
    return [p.resolve() for p in base + [uploads_dir()] if p.exists()]


def _allowed(p: Path) -> bool:
    rp = p.resolve()
    return any(rp == r or r in rp.parents for r in roots())


def resolve(path: str) -> Path:
    """An allowed document by path, or found by (part of) its file name in the allowed folders."""
    p = Path(path).expanduser()
    if p.is_absolute() or p.exists():
        if not _allowed(p):
            raise PermissionError(f"{p} is outside the folders E.V may read ({', '.join(map(str, roots()))})")
        if not p.is_file():
            raise FileNotFoundError(str(p))
        return p
    needle = path.lower()
    for r in roots():
        for f in r.rglob("*"):
            if f.is_file() and f.suffix.lower() in SUPPORTED and needle in f.name.lower():
                return f
    raise FileNotFoundError(f"no document matching '{path}' in {', '.join(map(str, roots()))}")


def extract(p: Path) -> List[Dict[str, Any]]:
    """[{page, text}] - PDF pages are real pages; other formats are split into ~1,500-char parts."""
    if p.stat().st_size > MAX_BYTES:
        raise ValueError(f"{p.name} is larger than {MAX_BYTES // 1024**2} MB")
    ext = p.suffix.lower()
    if ext == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(p))
        return [{"page": i + 1, "text": (pg.extract_text() or "").strip()}
                for i, pg in enumerate(reader.pages[:MAX_PAGES])]
    if ext == ".docx":
        import docx

        text = "\n".join(par.text for par in docx.Document(str(p)).paragraphs)
    elif ext in (".html", ".htm"):
        from openatlas.kb.library import html_to_text

        text = html_to_text(p.read_text(errors="replace"))
    else:
        text = p.read_text(errors="replace")
    parts, buf, n = [], "", 1
    for para in re.split(r"\n\s*\n|\n", text):
        if len(buf) + len(para) > 1500 and buf:
            parts.append({"page": n, "text": buf.strip()})
            buf, n = "", n + 1
        buf += para + "\n"
    if buf.strip():
        parts.append({"page": n, "text": buf.strip()})
    return parts[:MAX_PAGES]


def passages(pages: List[Dict[str, Any]], question: str, k: int = 4) -> List[Dict[str, Any]]:
    """Best-matching sentences windows for ``question`` with their page numbers."""
    from openatlas.kb.retrieve import STOPWORDS, _stem

    q = {_stem(w) for w in _WORD.findall(question.lower()) if w not in STOPWORDS}
    if not q:
        return []
    scored = []
    for pg in pages:
        sents = re.split(r"(?<=[.!?])\s+", pg["text"])
        for i in range(len(sents)):
            window = " ".join(sents[i:i + 3])
            words = {_stem(w) for w in _WORD.findall(window.lower())}
            hit = len(q & words) / len(q)
            if hit:
                scored.append((hit, pg["page"], window[:700]))
    scored.sort(key=lambda x: -x[0])
    out, seen = [], set()
    for score, page, text in scored:
        if (page, text[:60]) in seen:
            continue
        seen.add((page, text[:60]))
        out.append({"page": page, "text": text, "score": round(score, 2)})
        if len(out) == k:
            break
    return out


@tool("list_documents", kind="read", skill="Document Intelligence",
      description="List the documents E.V may read (PDF, Word, text, Markdown, HTML), newest first.",
      params={"folder": {"type": "string", "description": "optional sub-folder or name filter"}})
def list_documents(folder: str = "") -> Dict[str, Any]:
    files = []
    for r in roots():
        for f in r.rglob("*"):
            if f.is_file() and f.suffix.lower() in SUPPORTED and (not folder or folder.lower() in str(f).lower()):
                files.append((f.stat().st_mtime, f))
    files.sort(reverse=True)
    return {"documents": [{"name": f.name, "path": str(f), "kb": round(f.stat().st_size / 1024)}
                          for _, f in files[:40]], "folders": [str(r) for r in roots()]}


@tool("read_document", kind="read", skill="Document Intelligence",
      description="Read a document and return the passages that answer a question (with page numbers), "
                  "or an overview when no question is given.",
      params={"path": {"type": "string", "description": "file path or part of the file name"},
              "question": {"type": "string", "description": "what to look for"}},
      required=["path"])
def read_document(path: str, question: str = "") -> Dict[str, Any]:
    p = resolve(path)
    pages = extract(p)
    words = sum(len(pg["text"].split()) for pg in pages)
    base = {"document": p.name, "path": str(p), "pages": len(pages), "words": words}
    if question:
        found = passages(pages, question)
        return {**base, "passages": found,
                "sources": [{"title": f"{p.name}, p. {x['page']}", "text": x["text"], "url": str(p)} for x in found]}
    head = "\n".join(pg["text"] for pg in pages[:3])[:3500]
    headings = [ln.strip() for pg in pages[:20] for ln in pg["text"].splitlines()
                if 3 < len(ln.strip()) < 80 and (ln.isupper() or ln.strip().startswith("#"))][:15]
    return {**base, "opening": head, "headings": headings,
            "sources": [{"title": f"{p.name}, p. 1-{min(3, len(pages))}", "text": head, "url": str(p)}]}


def save_upload(name: str, data: bytes) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._ -]", "_", Path(name).name)[:120] or "document"
    if Path(safe).suffix.lower() not in SUPPORTED:
        raise ValueError(f"unsupported file type - E.V reads {', '.join(SUPPORTED)}")
    if len(data) > MAX_BYTES:
        raise ValueError("file too large")
    dest = uploads_dir() / safe
    dest.write_bytes(data)
    return dest


def maybe_path(text: str) -> Optional[str]:
    m = re.search(r"([~/\w.\- ]+\.(?:pdf|docx|txt|md|html?|csv))", text, re.I)
    return m.group(1).strip() if m else None
