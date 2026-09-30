"""Lint the Claude Code agents and commands adapted from everything-claude-code: valid frontmatter,
a source line, nothing left over from the npm/TypeScript original, no paid services, no
placeholders in commands, and every documented ``openatlas`` command runs."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import List, Tuple

import pytest

from openatlas.skills import linter
from openatlas.utils.secret_lint import scan_text

ROOT = Path(__file__).resolve().parent.parent
AGENTS = sorted((ROOT / ".claude" / "agents").glob("*.md"))
COMMANDS = sorted((ROOT / ".claude" / "commands").glob("*.md"))
ALL = AGENTS + COMMANDS
TOOLS = {"Read", "Write", "Edit", "Bash", "Grep", "Glob"}
SOURCE = re.compile(r"^<!-- Adapted from everything-claude-code \S.* \(MIT, \(c\) 2026 Affaan Mustafa\) at 432485b"
                    r" - see \.claude/ECC-NOTICE\.md -->$")
LEFTOVER = re.compile(r"\b(npm (?:run|test|audit)|pnpm|yarn|tsc|jest|vitest|next build|tsconfig|knip|ts-prune|"
                      r"depcheck|eslint|console\.log|\.tsx?\b)", re.I)
PAID = re.compile(r"\b(openai|supabase|vercel|upstash|pinecone|railway|cloud run|stripe|sentry|datadog|redis|"
                  r"clickhouse|github copilot)\b", re.I)
SHELL = ("", "bash", "sh", "shell", "console")


def _fences(body: str) -> List[Tuple[str, str]]:
    """(language, text) for each fenced block - tracks open/close so prose is never mistaken for code."""
    blocks, lang, buf = [], None, []
    for ln in body.splitlines():
        if ln.lstrip().startswith("```"):
            if lang is None:
                lang, buf = ln.strip()[3:].strip().lower(), []
            else:
                blocks.append((lang, "\n".join(buf)))
                lang = None
        elif lang is not None:
            buf.append(ln)
    return blocks


def _commands(body: str) -> List[str]:
    return [ln.split(" #")[0].strip() for lang, text in _fences(body) if lang in SHELL for ln in text.splitlines()
            if ln.strip().startswith(("python -m openatlas", "python3 -m openatlas", "python openatlas.py", "openatlas "))]


def test_the_expected_agents_and_commands_are_there():
    assert {p.stem for p in AGENTS} == {"planner", "architect", "code-reviewer", "security-reviewer", "tdd-guide",
                                         "refactor-cleaner", "doc-updater", "build-error-resolver", "e2e-runner"}
    assert {p.stem for p in COMMANDS} == {f"oa-{n}" for n in ("plan", "tdd", "verify", "review", "checkpoint", "learn",
                                                                "refactor-clean", "test-coverage", "update-docs",
                                                                "eval", "orchestrate", "build-fix", "e2e")}


@pytest.mark.parametrize("path", AGENTS, ids=lambda p: p.stem)
def test_agent_frontmatter(path):
    meta, body, err = linter.split_frontmatter(path.read_text())
    assert err is None, err
    assert meta["name"] == path.stem and linter.NAME_RE.match(meta["name"])
    assert 40 <= len(meta["description"]) <= 1024
    assert set(t.strip() for t in meta["tools"].split(",")) <= TOOLS


@pytest.mark.parametrize("path", COMMANDS, ids=lambda p: p.stem)
def test_command_frontmatter(path):
    meta, body, err = linter.split_frontmatter(path.read_text())
    assert err is None, err
    assert 20 <= len(meta["description"]) <= 1024 and "$ARGUMENTS" in body


@pytest.mark.parametrize("path", ALL, ids=lambda p: p.stem)
def test_house_rules(path):
    text = path.read_text()
    meta, body, _ = linter.split_frontmatter(text)
    assert SOURCE.match(body.strip().splitlines()[0]), "first line after the frontmatter must name its source"
    assert not LEFTOVER.search(text), f"npm/TypeScript leftover: {LEFTOVER.search(text).group(0)}"
    assert not PAID.search(text), f"mentions a hosted/paid service: {PAID.search(text).group(0)}"
    assert not scan_text(text), "contains a secret or paid-key literal"
    for lang, block in _fences(body):
        if lang in SHELL:
            assert not re.search(r"<[A-Za-z][^>]*>", block), f"placeholder in a command block:\n{block}"
    for ref in re.findall(r"`((?:openatlas|tests)/[\w/.-]+\.(?:py|js|yaml|html))`", body):
        assert (ROOT / ref).exists(), f"references missing file {ref}"
    for mod in set(re.findall(r"`(openatlas(?:\.\w+)+)", body)):
        assert linter._is_module(mod) or linter._is_module(mod.rsplit(".", 1)[0]), f"no such module {mod}"


def test_every_documented_openatlas_command_runs():
    probes = {tuple(linter.help_command(c)) for p in ALL for c in _commands(p.read_text())}
    assert len(probes) >= 5
    bad = [" ".join(pr[1:]) for pr in sorted(probes)
           if subprocess.run(list(pr), capture_output=True, timeout=120, cwd=ROOT).returncode != 0]
    assert bad == []


def test_the_notice_carries_the_mit_licence():
    notice = (ROOT / ".claude" / "ECC-NOTICE.md").read_text()
    assert "Copyright (c) 2026 Affaan Mustafa" in notice and "Permission is hereby granted" in notice
    assert "432485b" in notice and "left out" in notice
    assert "everything-claude-code" in (ROOT / "NOTICE").read_text()
