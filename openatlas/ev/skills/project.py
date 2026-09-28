"""Project Setup: propose a folder layout, README and checklist for a new project; create it
(with your approval) without ever overwriting an existing file."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict

from openatlas.ev.tools import tool

KINDS = ("python", "web", "research", "osint-case", "notes")


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:50] or "project"


def template(name: str, kind: str, goal: str) -> Dict[str, str]:
    kind = kind if kind in KINDS else "notes"
    slug, pkg = _slug(name), _slug(name).replace("-", "_")
    readme = f"# {name}\n\n{goal or 'What this project is for.'}\n\n## Next steps\n\n- [ ] ...\n"
    files: Dict[str, str] = {"README.md": readme, "CHECKLIST.md":
                             "# Checklist\n\n- [ ] Define done\n- [ ] First milestone\n- [ ] Review\n"}
    if kind == "python":
        files.update({
            ".gitignore": "__pycache__/\n*.pyc\n.venv/\ndist/\nbuild/\n.pytest_cache/\n",
            "pyproject.toml": (f'[project]\nname = "{slug}"\nversion = "0.1.0"\nrequires-python = ">=3.10"\n'
                               f'dependencies = []\n\n[project.optional-dependencies]\ndev = ["pytest", "ruff"]\n'),
            f"src/{pkg}/__init__.py": f'"""{name}."""\n\n__version__ = "0.1.0"\n',
            "tests/test_smoke.py": f"import {pkg}\n\n\ndef test_version():\n    assert {pkg}.__version__\n",
        })
        files["README.md"] += ("\n## Setup\n\n```bash\npython3 -m venv .venv && source .venv/bin/activate\n"
                               "pip install -e '.[dev]'\npytest\n```\n")
    elif kind == "web":
        files.update({"index.html": f"<!doctype html>\n<meta charset='utf-8'>\n<title>{name}</title>\n"
                                    "<link rel='stylesheet' href='style.css'>\n<h1>" + name + "</h1>\n<script src='app.js'></script>\n",
                      "style.css": "body { font-family: system-ui, sans-serif; margin: 2rem; }\n",
                      "app.js": "// your code\n"})
    elif kind == "research":
        files.update({"questions.md": f"# Questions\n\n1. {goal or '...'}\n",
                      "sources.md": "# Sources\n\n| # | Source | Why it matters | Verified |\n|---|---|---|---|\n",
                      "notes/.keep": ""})
    elif kind == "osint-case":
        files.update({"PURPOSE.md": "# Purpose\n\nWhy this investigation is legitimate (self-audit, due "
                                    "diligence, authorised engagement). Public, unauthenticated data only.\n",
                      "evidence/.keep": "", "report.md": f"# Report: {name}\n\n## Findings\n\n## Sources\n"})
    return files


@tool("plan_project", kind="read", skill="Project Setup",
      description="Propose a project layout (files and folders) for a new project, to review before creating.",
      params={"name": {"type": "string"}, "kind": {"type": "string", "enum": list(KINDS)},
              "goal": {"type": "string"}}, required=["name"])
def plan_project(name: str, kind: str = "notes", goal: str = "") -> Dict[str, Any]:
    files = template(name, kind, goal)
    return {"card": "project", "name": name, "kind": kind if kind in KINDS else "notes",
            "folder": str(Path.home() / "Projects" / _slug(name)), "files": sorted(files)}


@tool("create_project", kind="write", skill="Project Setup",
      description="Create the project folder and starter files on disk (needs approval; never overwrites).",
      params={"name": {"type": "string"}, "kind": {"type": "string", "enum": list(KINDS)},
              "goal": {"type": "string"}, "path": {"type": "string", "description": "parent folder (default ~/Projects)"}},
      required=["name"])
def create_project(name: str, kind: str = "notes", goal: str = "", path: str = "") -> Dict[str, Any]:
    root = (Path(path).expanduser() if path else Path.home() / "Projects") / _slug(name)
    written, skipped = [], []
    for rel, body in template(name, kind, goal).items():
        dest = root / rel
        if dest.exists():
            skipped.append(rel)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(body)
        written.append(rel)
    return {"folder": str(root), "written": written, "skipped_existing": skipped}
