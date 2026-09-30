"""Engineering: review code, verify a project, learn from a session, checkpoint a long chat,
plan a feature test-first, and measure how reliable an answer is.

Adapted from everything-claude-code (MIT, github.com/affaan-m/everything-claude-code): its
code-reviewer / security-reviewer agents, verification-loop, continuous-learning,
strategic-compact, planner / tdd-guide and eval-harness - rebuilt as local, key-free E.V tools.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from openatlas.ev import db, memory
from openatlas.ev.skills import documents
from openatlas.ev.tools import tool

SKILL = "Engineering"
CODE_EXT = (".py", ".js", ".ts", ".tsx", ".jsx", ".sh", ".rb", ".go", ".rs", ".java", ".php", ".sql",
            ".html", ".yml", ".yaml", ".toml", ".cfg", ".ini", ".env")
MAX_FILES, MAX_BYTES = 200, 400_000
SEVERITY = ("critical", "high", "medium", "low")

# ------------------------------------------------------------------ code review
# (pattern, severity, what it is, why it matters) - checked line by line
_RULES: List[Tuple[re.Pattern, str, str, str]] = [
    (re.compile(r"\b(eval|exec)\s*\("), "high", "eval/exec", "runs text as code - injection risk"),
    (re.compile(r"shell\s*=\s*True"), "high", "shell=True", "a shell parses the command - injection risk"),
    (re.compile(r"\bos\.system\s*\("), "high", "os.system", "a shell parses the command - use subprocess with a list"),
    (re.compile(r"\bpickle\.loads?\s*\("), "high", "pickle.load", "unpickling untrusted data runs code"),
    (re.compile(r"\byaml\.load\s*\((?![^)]*Loader\s*=\s*yaml\.SafeLoader)"), "high", "yaml.load", "use yaml.safe_load"),
    (re.compile(r"verify\s*=\s*False"), "high", "verify=False", "TLS certificate checks switched off"),
    (re.compile(r"""(execute|executemany|raw)\s*\(\s*(f["']|["'][^"']*["']\s*(%|\+|\.format))""", re.I), "critical",
     "SQL built from strings", "SQL injection - use parameters (?, %s)"),
    (re.compile(r"^\s*except\s*:\s*$|^\s*except\s+(Base)?Exception\s*:\s*pass\b"), "medium", "swallowed exception",
     "errors disappear silently"),
    (re.compile(r"\bdebug\s*=\s*True\b|DEBUG\s*=\s*True"), "medium", "debug on", "debug mode leaks internals in production"),
    (re.compile(r"\b(md5|sha1)\s*\("), "medium", "weak hash", "md5/sha1 are broken for security uses"),
    (re.compile(r"\bTODO\b|\bFIXME\b|\bXXX\b"), "low", "TODO", "unfinished work left in the code"),
    (re.compile(r"\bprint\s*\(.*(password|token|secret)", re.I), "high", "secret printed", "secrets end up in logs"),
]
_DEF = re.compile(r"^(\s*)(async\s+)?def\s+(\w+)|^(\s*)function\s+(\w+)|^\s*(const|let)\s+(\w+)\s*=\s*(async\s*)?\(")
LONG_FUNCTION = 60


def _files(target: Path) -> List[Path]:
    if target.is_file():
        return [target]
    skip = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".tox"}
    out = []
    for f in sorted(target.rglob("*")):
        if any(p in skip for p in f.parts):
            continue
        if f.is_file() and f.suffix.lower() in CODE_EXT and f.stat().st_size <= MAX_BYTES and documents._allowed(f):
            out.append(f)  # _allowed resolves symlinks, so a link out of the allowed folders is skipped
            if len(out) >= MAX_FILES:
                break
    return out


def _allowed_path(path: str) -> Path:
    p = Path(path).expanduser()
    if p.is_absolute() or p.exists():
        if not documents._allowed(p):
            raise PermissionError(f"{p} is outside the folders E.V may read ({', '.join(map(str, documents.roots()))})")
        if not p.exists():
            raise FileNotFoundError(str(p))
        return p
    for r in documents.roots():  # a name: search the allowed folders
        for f in r.rglob("*"):
            if path.lower() in f.name.lower() and (f.is_dir() or f.suffix.lower() in CODE_EXT) and documents._allowed(f):
                return f
    raise FileNotFoundError(f"no file or folder matching '{path}' in {', '.join(map(str, documents.roots()))}")


def review_text(text: str, name: str = "<code>") -> List[Dict[str, Any]]:
    """Graded findings for one file's text (deterministic; no model needed)."""
    from openatlas.utils.secret_lint import scan_text

    found: List[Dict[str, Any]] = []
    for f in scan_text(text, name):
        found.append({"file": name, "line": int(f.get("line") or 0), "severity": "critical", "what": "hardcoded secret",
                      "why": f"looks like a secret ({f.get('rule', 'key')}) - move it to an environment variable"})
    lines = text.splitlines()
    for i, ln in enumerate(lines, 1):
        for rx, sev, what, why in _RULES:
            if rx.search(ln):
                found.append({"file": name, "line": i, "severity": sev, "what": what, "why": why})
    # long functions: from a def to the next line at the same or lower indent
    starts = [(i, len(m.group(1) or m.group(4) or ""), m.group(3) or m.group(5) or m.group(7))
              for i, ln in enumerate(lines) if (m := _DEF.match(ln))]
    for k, (i, ind, fname) in enumerate(starts):
        end = len(lines)
        for j in range(i + 1, len(lines)):
            s = lines[j]
            if s.strip() and len(s) - len(s.lstrip()) <= ind and not s.lstrip().startswith((")", "]", "}")):
                end = j
                break
        if end - i > LONG_FUNCTION:
            found.append({"file": name, "line": i + 1, "severity": "low", "what": f"long function {fname}",
                          "why": f"{end - i} lines - split it so it can be tested and read"})
    return found


@tool("review_code", kind="read", skill=SKILL,
      description="Review a code file or folder (in the folders you allow) for security and quality problems: "
                  "hardcoded secrets, injection risks, unsafe calls, swallowed errors, long functions, missing tests. "
                  "Findings are graded critical/high/medium/low with file and line.",
      params={"path": {"type": "string", "description": "file or folder path, or part of its name"},
              "focus": {"type": "string", "description": "optional: security | quality | all"}},
      required=["path"])
def review_code(path: str, focus: str = "all") -> Dict[str, Any]:
    target = _allowed_path(path)
    files = _files(target)
    findings: List[Dict[str, Any]] = []
    for f in files:
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        findings += review_text(text, str(f.relative_to(target.parent) if target.is_dir() else f.name))
    if focus == "security":
        findings = [x for x in findings if x["severity"] in ("critical", "high")]
    elif focus == "quality":
        findings = [x for x in findings if x["severity"] in ("medium", "low")]
    code = [f for f in files if f.suffix == ".py" and not f.name.startswith("test_")]
    has_tests = any(f.name.startswith("test_") or "/tests/" in str(f) for f in files)
    if target.is_dir() and code and not has_tests and focus != "security":
        findings.append({"file": target.name, "line": 0, "severity": "medium", "what": "no tests",
                         "why": "nothing checks this code - write a test first (tdd)"})
    findings.sort(key=lambda x: (SEVERITY.index(x["severity"]), x["file"], x["line"]))
    counts = {s: sum(1 for x in findings if x["severity"] == s) for s in SEVERITY}
    verdict = "block" if counts["critical"] or counts["high"] else "fix soon" if counts["medium"] else "ok"
    return {"card": "review", "path": str(target), "files": len(files), "counts": counts, "verdict": verdict,
            "findings": findings[:80], "truncated": len(findings) > 80}


# ------------------------------------------------------------------ verification loop
# per project type, a fixed list of checks - never arbitrary shell
def _checks(root: Path) -> List[Tuple[str, List[str]]]:
    import shutil
    import sys

    out: List[Tuple[str, List[str]]] = []
    if (root / "pyproject.toml").exists() or (root / "setup.py").exists():
        out.append(("tests", [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider"]))
        if shutil.which("ruff"):
            out.append(("lint", ["ruff", "check", "."]))
        if (root / "openatlas" / "__init__.py").exists():
            out.append(("secrets", [sys.executable, "-m", "openatlas.utils.secret_lint", "openatlas"]))
            out.append(("doctor", [sys.executable, "-m", "openatlas.utils.forge", "doctor"]))
    if (root / "package.json").exists() and shutil.which("npm"):
        out.append(("tests", ["npm", "test", "--silent"]))
    if (root / "Cargo.toml").exists() and shutil.which("cargo"):
        out.append(("tests", ["cargo", "test", "--quiet"]))
    return out


def _run(cmd: List[str], cwd: Path, timeout: int) -> Tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr)
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"
    except OSError as exc:
        return 127, str(exc)


RUNNER: Callable[[List[str], Path, int], Tuple[int, str]] = _run  # tests swap this for a fake


@tool("verify_project", kind="command", skill=SKILL,
      description="Run a project's own checks (tests, lint, secret scan, and for OpenAtlas the doctor) and report "
                  "a pass/fail gate for each - work isn't done until every gate passes.",
      params={"path": {"type": "string", "description": "the project folder"}}, required=["path"])
def verify_project(path: str, timeout: int = 900) -> Dict[str, Any]:
    root = _allowed_path(path)
    if root.is_file():
        root = root.parent
    checks = _checks(root)
    if not checks:
        return {"ok": False, "error": f"no checks known for {root.name} (no pyproject.toml, package.json or Cargo.toml)"}
    gates = []
    for name, cmd in checks:
        code, out = RUNNER(cmd, root, timeout)
        tail = "\n".join(out.strip().splitlines()[-12:])
        shown = " ".join(["python" if i == 0 and "python" in Path(c).name else c for i, c in enumerate(cmd)])
        gates.append({"gate": name, "command": shown, "passed": code == 0, "exit": code, "tail": "" if code == 0 else tail})
    passed = all(g["passed"] for g in gates)
    return {"card": "verify", "path": str(root), "passed": passed, "gates": gates,
            "summary": ("all gates pass - ready" if passed else
                        "not done: " + ", ".join(g["gate"] for g in gates if not g["passed"]) + " failed")}


# ------------------------------------------------------------------ continuous learning
def learned_dir() -> Path:
    d = db.ev_dir() / "learned"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60] or "pattern"


def learned() -> List[Dict[str, Any]]:
    out = []
    for f in sorted(learned_dir().glob("*.md")):
        text = f.read_text(errors="replace")
        out.append({"slug": f.stem, "title": text.splitlines()[0].lstrip("# ").strip() if text else f.stem,
                    "text": text, "path": str(f)})
    return out


@tool("learn_pattern", kind="write", skill=SKILL,
      description="Save a reusable lesson from this conversation (the problem, what solved it, when to use it) so "
                  "you and E.V can reuse it later. Saving waits for approval.",
      params={"title": {"type": "string"}, "problem": {"type": "string"},
              "solution": {"type": "string"}, "when": {"type": "string", "description": "when to use it"}},
      required=["title", "solution"])
def learn_pattern(title: str, solution: str, problem: str = "", when: str = "") -> Dict[str, Any]:
    f = learned_dir() / f"{_slug(title)}.md"
    body = (f"# {title.strip()[:120]}\n\n" + (f"**Problem:** {problem.strip()}\n\n" if problem.strip() else "")
            + f"**What worked:** {solution.strip()}\n\n" + (f"**Use it when:** {when.strip()}\n\n" if when.strip() else "")
            + f"_Learned {db.now()[:10]}_\n")
    f.write_text(body)
    memory.remember(f"Learned pattern '{title.strip()[:80]}': {solution.strip()[:200]}", source="learn_pattern")
    return {"saved": f.name, "path": str(f), "title": title}


@tool("list_learned", kind="read", skill=SKILL,
      description="List the patterns E.V has learned with you (optionally matching some words).",
      params={"query": {"type": "string"}})
def list_learned(query: str = "") -> Dict[str, Any]:
    words = [w for w in query.lower().split() if len(w) > 2]
    items = [x for x in learned() if not words or any(w in x["text"].lower() for w in words)]
    return {"learned": [{"slug": x["slug"], "title": x["title"], "text": x["text"][:600]} for x in items[:30]]}


@tool("forget_learned", kind="read", skill=SKILL,
      description="Forget a learned pattern (by its name or words from its title).",
      params={"what": {"type": "string"}}, required=["what"])
def forget_learned(what: str) -> Dict[str, Any]:
    if len(what.strip()) < 3:
        return {"ok": False, "error": "say which pattern to forget (a few words from its title)"}
    gone = []
    for x in learned():
        if _slug(what) == x["slug"] or what.lower() in x["title"].lower():
            Path(x["path"]).unlink(missing_ok=True)
            memory.forget(f"Learned pattern '{x['title'][:80]}'")
            gone.append(x["title"])
    return {"forgotten": gone}


# ------------------------------------------------------------------ strategic checkpoint
def checkpoint_of(conv_id: int) -> int:
    r = db.one("SELECT value FROM kv WHERE key=?", (f"checkpoint:{conv_id}",))
    return int(r["value"]) if r else 0


@tool("checkpoint", kind="read", skill=SKILL,
      description="Checkpoint a long conversation: fold everything so far into a short summary (goals, decisions, "
                  "open items) so later replies stay quick and focused. Nothing is deleted.",
      params={"note": {"type": "string", "description": "optional: what to carry forward"}})
def checkpoint(note: str = "", _conv_id: int = 0) -> Dict[str, Any]:
    if not _conv_id:
        return {"ok": False, "error": "no conversation to checkpoint"}
    msgs = [m for m in memory.messages(_conv_id, 400) if m["role"] in ("user", "assistant")]
    if not msgs:
        return {"ok": False, "error": "nothing to checkpoint yet"}
    from openatlas.llm import ollama_client

    text = "\n".join(f"{m['role']}: {m['content'][:400]}" for m in msgs[-60:])
    summary = ollama_client.complete(
        "Checkpoint this conversation in at most 8 short bullet points under the headings Goals, Decisions, "
        "Open items. Keep names, numbers and preferences.\n\n" + text, max_tokens=320) if ollama_client.available() else None
    if not summary:
        asked = [m["content"][:90] for m in msgs if m["role"] == "user"][-8:]
        summary = "Goals and questions so far: " + "; ".join(asked)
    if note.strip():
        summary = f"Carry forward: {note.strip()}\n{summary}"
    memory.set_summary(_conv_id, summary)
    last = max(m["id"] for m in msgs)
    with db.connect() as con:
        con.execute("INSERT OR REPLACE INTO kv(key, value) VALUES (?, ?)", (f"checkpoint:{_conv_id}", str(last)))
    return {"checkpointed": len(msgs), "summary": summary}


def suggest_checkpoint(conv_id: int, every: int = 40) -> bool:
    """True when this chat has grown long since its last checkpoint (E.V offers one; never automatic)."""
    since = [m for m in memory.messages(conv_id, 400) if m["role"] == "user" and m["id"] > checkpoint_of(conv_id)]
    return len(since) >= every and len(since) % every == 0


# ------------------------------------------------------------------ feature planning (planner + tdd)
def feature_steps(goal: str) -> List[str]:
    return [f"Requirements: write down what '{goal[:80]}' must do, and what it must not do",
            "Design: which files/modules change, what stays the same, the simplest approach that works",
            "Tests first: write failing tests for the behaviour (happy path, edge cases, errors)",
            "Implement the smallest change that makes the tests pass",
            "Verify: run every gate (tests, lint, secret scan, doctor) - verify_project",
            "Review: security and quality review of the change - review_code",
            "Risks and rollback: what could break, and how to undo it"]


@tool("plan_feature", kind="read", skill=SKILL,
      description="Plan a feature or fix test-first as an editable checklist: requirements, design, tests first, "
                  "implementation, verification, review, risks.",
      params={"goal": {"type": "string"}}, required=["goal"])
def plan_feature(goal: str, _conv_id: int = 0) -> Dict[str, Any]:
    from openatlas.ev.skills import planning

    return planning.make_plan(goal, feature_steps(goal), _conv_id=_conv_id)


# ------------------------------------------------------------------ eval harness (pass@k)
_KEY = re.compile(r"\b[A-Z][\w'-]+|\b\d[\d.,:%]*\b")


def key_terms(expected: str) -> List[str]:
    """Names and numbers a right answer must contain (the words a paraphrase can't change)."""
    from openatlas.kb.retrieve import STOPWORDS

    return sorted({w for m in _KEY.finditer(expected) if len(w := m.group(0).strip(".,").lower()) > 1
                   and w not in STOPWORDS})


def answer_ok(answer: str, expected: str) -> Tuple[bool, List[str]]:
    """Right when every key term of the expected facts is in the answer and the claim checker finds
    nothing in the answer that contradicts them."""
    from openatlas.ev.skills import qa

    low = answer.lower()
    missing = [k for k in key_terms(expected) if k not in low]
    rep = qa.check(expected, [{"title": "answer", "text": answer, "url": ""}], use_model=False)
    return (not missing and rep["counts"]["unsupported"] == 0 and rep["counts"]["supported"] >= 1), missing


def pass_at_k(results: List[bool]) -> Dict[str, Any]:
    """pass@k: at least one of k runs right; pass^k: all k right (consistency)."""
    k = len(results)
    return {"k": k, "passed": sum(results), "pass_at_k": bool(k and any(results)), "pass_all_k": bool(k and all(results))}


@tool("eval_answers", kind="read", skill=SKILL,
      description="Measure how reliable E.V's answer to a question is: ask the local model k times and check each "
                  "answer against the expected facts - reports pass@k (any right) and pass^k (all right).",
      params={"question": {"type": "string"}, "expected": {"type": "string", "description": "the facts a right answer contains"},
              "k": {"type": "integer", "description": "how many runs (1-10, default 3)"}},
      required=["question", "expected"])
def eval_answers(question: str, expected: str, k: int = 3) -> Dict[str, Any]:
    from openatlas.llm import ollama_client

    if not ollama_client.available():
        return {"ok": False, "error": "the local model isn't running - start it with: ollama serve"}
    k = max(1, min(int(k or 3), 10))
    runs = []
    for _ in range(k):
        ans = ollama_client.chat([{"role": "user", "content": question}], temperature=0.7) or ""
        ok, missing = answer_ok(ans, expected)
        runs.append({"answer": ans[:400], "passed": ok, "missing": missing})
    return {"card": "eval", "question": question, **pass_at_k([r["passed"] for r in runs]), "runs": runs}


