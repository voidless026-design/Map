"""Verify a SKILL.md: spec-valid frontmatter, required sections, and runnable commands.

Checks (the "verify" half of skill-forge for *skills*):
 1. frontmatter: YAML, ``name`` 1-64 chars lowercase/digits/hyphens (no leading, trailing
    or double hyphens) matching its folder, ``description`` 1-1024 chars, optional
    ``compatibility`` <= 500 chars (agentskills.io / OpenJarvis rules);
 2. sections: "When to trigger" with >= 3 examples, a "Verification" section, and a
    "Tools" section (what the skill needs and why);
 3. commands: every ``openatlas`` command in a code block actually exists (``--help``
    exits 0);
 4. references: every ``openatlas/…`` path and ``openatlas.…`` module it names exists;
 5. no secrets or paid-API-key literals in the text.
"""

from __future__ import annotations

import importlib.util
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from openatlas.config import Config

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
ALLOWED_KEYS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
_FENCE = re.compile(r"```(?:bash|sh|shell|console)?\n(.*?)```", re.S)
_HEADING = re.compile(r"^(#{2,3})\s+(.*)$", re.M)


def split_frontmatter(text: str) -> Tuple[Optional[Dict[str, Any]], str, Optional[str]]:
    if not text.startswith("---"):
        return None, text, "missing YAML frontmatter (--- ... ---)"
    end = text.find("\n---", 3)
    if end == -1:
        return None, text, "frontmatter is not closed with ---"
    try:
        meta = yaml.safe_load(text[3:end]) or {}
    except yaml.YAMLError as exc:
        return None, text, f"frontmatter is not valid YAML: {exc}"
    if not isinstance(meta, dict):
        return None, text, "frontmatter must be a mapping"
    return meta, text[end + 4:], None


def sections(body: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    marks = list(_HEADING.finditer(body))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        out[m.group(2).strip()] = body[m.end():end]
    return out


def _find(secs: Dict[str, str], *needles: str) -> Optional[str]:
    for title, content in secs.items():
        if any(n in title.lower() for n in needles):
            return content
    return None


def triggers(body: str) -> List[str]:
    sec = _find(sections(body), "when to trigger", "triggers")
    if not sec:
        return []
    return [re.sub(r"^[-*]\s+", "", ln).strip() for ln in sec.splitlines()
            if re.match(r"^\s*[-*]\s+\S", ln) and not ln.strip().lower().startswith(("- do not", "* do not"))]


def commands(body: str) -> List[str]:
    cmds = []
    for block in _FENCE.findall(body):
        joined = re.sub(r"\\\n\s*", " ", block)
        for ln in joined.splitlines():
            ln = ln.split(" #")[0].strip()
            if ln.startswith(("python -m openatlas", "python3 -m openatlas", "python3 openatlas.py",
                              "python openatlas.py", "openatlas ")):
                cmds.append(ln)
    return cmds


def help_command(cmd: str) -> List[str]:
    """Turn a documented command into its ``--help`` probe (placeholders dropped)."""
    try:
        toks = shlex.split(cmd)
    except ValueError:
        toks = cmd.split()
    if toks[0] == "openatlas":
        base, rest = [sys.executable, "-m", "openatlas"], toks[1:]
    elif toks[0].startswith("python") and len(toks) > 2 and toks[1] == "-m":
        base, rest = [sys.executable, "-m", toks[2]], toks[3:]
    else:  # python3 openatlas.py ...
        base, rest = [sys.executable, str(Path(Config.files.project_root) / "openatlas.py")], []
    subs = []
    for t in rest:
        if not re.fullmatch(r"[a-z][a-z0-9-]*", t):
            break
        subs.append(t)
    return base + subs[:2] + ["--help"]


def lint_skill(path: str, *, run_commands: bool = True) -> Dict[str, Any]:
    p = Path(path)
    skill_md = p / "SKILL.md" if p.is_dir() else p
    errors: List[str] = []
    warnings: List[str] = []
    text = skill_md.read_text(encoding="utf-8") if skill_md.exists() else ""
    if not text:
        return {"ok": False, "errors": [f"{skill_md} not found"], "warnings": [], "name": p.name}
    meta, body, err = split_frontmatter(text)
    if err:
        errors.append(err)
        meta = {}
    name = str(meta.get("name", ""))
    desc = str(meta.get("description", ""))
    folder = skill_md.parent.name
    if not (1 <= len(name) <= 64) or not NAME_RE.match(name):
        errors.append(f"name '{name}' must be 1-64 chars of lowercase letters/digits/single hyphens")
    elif name != folder:
        errors.append(f"name '{name}' must match its folder '{folder}'")
    if not (1 <= len(desc) <= 1024):
        errors.append(f"description must be 1-1024 characters (got {len(desc)})")
    if len(str(meta.get("compatibility", ""))) > 500:
        errors.append("compatibility must be <= 500 characters")
    extra = set(meta) - ALLOWED_KEYS
    if extra:
        warnings.append(f"non-standard frontmatter keys: {sorted(extra)}")

    secs = sections(body)
    trig = triggers(body)
    if len(trig) < 3:
        errors.append(f"'When to trigger' needs at least 3 examples (found {len(trig)})")
    if _find(secs, "verif") is None:
        errors.append("missing a Verification section")
    if _find(secs, "tool") is None:
        errors.append("missing a Tools section (what the skill needs and why)")

    checked = []
    for cmd in commands(body):
        probe = help_command(cmd)
        if not run_commands:
            checked.append({"command": cmd, "ok": None})
            continue
        try:
            rc = subprocess.run(probe, capture_output=True, timeout=60,
                                cwd=Config.files.project_root).returncode
        except (OSError, subprocess.TimeoutExpired) as exc:
            rc, _ = 1, exc
        checked.append({"command": cmd, "ok": rc == 0})
        if rc != 0:
            errors.append(f"command does not run: {cmd}  (probe: {' '.join(probe[1:])})")

    root = Path(Config.files.project_root)
    for ref in sorted(set(re.findall(r"`(openatlas/[\w/.-]+\.(?:py|yaml|html))[`:]", body))):
        if not (root / ref).exists():
            errors.append(f"references missing file {ref}")
    for mod in sorted(set(re.findall(r"`(openatlas(?:\.\w+)+)", body))):
        mod = mod.split(":")[0]
        target = mod if _is_module(mod) else mod.rsplit(".", 1)[0]  # module or module.attr
        if not _is_module(target):
            errors.append(f"references missing or unimportable module {mod}")

    from openatlas.utils.secret_lint import scan_text

    if scan_text(text):
        errors.append("contains a secret or paid-API-key literal")
    return {"ok": not errors, "name": name or folder, "description": desc, "triggers": trig,
            "commands": checked, "errors": errors, "warnings": warnings, "path": str(skill_md)}


def _is_module(dotted: str) -> bool:
    try:
        return importlib.util.find_spec(dotted) is not None
    except (ImportError, ValueError):
        return False
