"""Discover the project's skills (``.claude/skills/*/SKILL.md``) for the CLI and GUI."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from openatlas.config import Config
from openatlas.skills import linter


def skills_dir() -> Path:
    return Path(Config.files.project_root) / ".claude" / "skills"


def list_skills(run_commands: bool = False) -> List[Dict[str, Any]]:
    out = []
    for d in sorted(p for p in skills_dir().glob("*") if (p / "SKILL.md").exists()):
        r = linter.lint_skill(str(d), run_commands=run_commands)
        desc = r.get("description", "")
        out.append({"name": r["name"], "summary": desc.split(". ")[0][:220],
                    "description": desc, "triggers": r.get("triggers", []),
                    "lint_ok": r["ok"], "errors": r["errors"], "path": r["path"]})
    return out
