"""Static lint that fails if source code hardcodes secrets or paid API keys.

Two jobs:
* Enforce OpenAtlas's "no paid keys" rule: flag any obvious API-key literal or a
  reference to a known paid provider's key variable.
* Power the ``skill-forge`` verifier so newly generated tools can't smuggle in a
  credential.

This is a heuristic regex scanner (gitleaks-style), used both on our own tree and,
in a separate module, on public GitHub repos for the ``get_repo_secrets`` engine.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

# Patterns for *generic* leaked secrets.
SECRET_PATTERNS: Dict[str, re.Pattern[str]] = {
    "aws_access_key_id": re.compile(r"AKIA[0-9A-Z]{16}"),
    "openai_key": re.compile(r"sk-[A-Za-z0-9]{20,}"),
    "google_api_key": re.compile(r"AIza[0-9A-Za-z\-_]{35}"),
    "slack_token": re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}"),
    "generic_bearer": re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}"),
    "private_key_block": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "hex_secret_assign": re.compile(
        r"(?i)(api[_-]?key|secret|token|password)\s*[=:]\s*['\"][0-9a-f]{32,}['\"]"
    ),
}

# Names of paid-provider key variables that must NOT appear as real, populated
# assignments anywhere in OpenAtlas. (Mentions in comments/docs are fine.)
PAID_KEY_NAMES = [
    "openai_api_key",
    "perplexity_default_key",
    "hunter_api_key",
    "hibp_api_key",
    "isgen_api_key",
    "isgen_bearer",
    "oathnet_api_key",
    "picarta_api_key",
]

_ASSIGN = re.compile(
    r"(?i)\b(" + "|".join(map(re.escape, PAID_KEY_NAMES)) + r")\b\s*[=:]\s*['\"]([^'\"]+)['\"]"
)


#: A line ending in this comment is an intentional fixture (e.g. a fake key in a test that
#: proves the lint works) and is not reported.
IGNORE_PRAGMA = "secret-lint: ignore"

#: Folders never scanned: virtualenvs and third-party code are not OpenAtlas source, and
#: their examples/tests are full of sample keys.
SKIP_DIRS = {".git", "__pycache__", "robots_cache", ".venv", "venv", "env", ".env",
             "site-packages", "dist-packages", "node_modules", ".tox", ".nox", "build",
             "dist", ".eggs", ".mypy_cache", ".ruff_cache", ".pytest_cache"}


def default_target() -> Path:
    """The installed ``openatlas`` package itself - never a path relative to the cwd."""
    return Path(__file__).resolve().parent.parent


def scan_text(text: str, source: str = "<string>") -> List[Dict[str, str]]:
    """Return a list of findings for a blob of text."""
    findings: List[Dict[str, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if IGNORE_PRAGMA in line:
            continue
        stripped = line.strip()
        for name, pat in SECRET_PATTERNS.items():
            if pat.search(line):
                findings.append(
                    {"source": source, "line": str(lineno), "rule": name, "snippet": stripped[:120]}
                )
        m = _ASSIGN.search(line)
        if m and m.group(2).strip():
            # A paid key name assigned a non-empty literal value.
            findings.append(
                {
                    "source": source,
                    "line": str(lineno),
                    "rule": f"paid_key_populated:{m.group(1).lower()}",
                    "snippet": stripped[:120],
                }
            )
    return findings


_CHECKOUT_MARKERS = ("pyproject.toml", "setup.py", ".git")
# things that belong to a repository, never inside the installed package folder
_NOT_PACKAGE = {"tests", "test", ".claude", "docs", "packaging"}


def stray_copies(package_root) -> List[Path]:
    """Folders/files inside the *package* folder that belong to a repository, not the package -
    e.g. an older copy of OpenAtlas cloned or unpacked into it. They are not package code, so the
    package scan skips them (the doctor lists them so you can delete them)."""
    root = Path(package_root)
    out: List[Path] = []
    for child in sorted(root.iterdir()) if root.is_dir() else []:
        if child.name in _NOT_PACKAGE and child.is_dir():
            out.append(child)
        elif child.name in _CHECKOUT_MARKERS:
            out.append(child)
        elif child.is_dir() and child.name == root.name and (child / "__init__.py").exists():
            out.append(child)  # the package nested inside itself
        elif child.is_dir() and any((child / m).exists() for m in _CHECKOUT_MARKERS):
            out.append(child)  # another checkout inside the package
    return out


def iter_files(path, exts=(".py", ".yaml", ".yml", ".toml", ".env", ".txt"), *,
               package: bool = False) -> List[Path]:
    """Files under ``path`` that the lint covers (environment/vendored folders skipped).
    ``package=True`` scans only the package's own code, skipping :func:`stray_copies`."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"secret lint target does not exist: {p}")
    if p.is_file():
        return [p]
    root = p.resolve()
    root_parts = len(root.parts)
    skip = {s.resolve() for s in stray_copies(root)} if package else set()
    return [f for f in p.rglob("*") if f.suffix in exts and f.is_file()
            and not SKIP_DIRS.intersection(f.resolve().parts[root_parts:])
            and not any(s == f.resolve() or s in f.resolve().parents for s in skip)]


def scan_path(path, *, exts=(".py", ".yaml", ".yml", ".toml", ".env", ".txt"),
              package: bool = False) -> List[Dict[str, str]]:
    """Recursively scan a file or directory tree for secrets.

    Raises ``FileNotFoundError`` for a missing path, so a typo can never pass as "clean"."""
    findings: List[Dict[str, str]] = []
    for f in iter_files(path, exts, package=package):
        try:
            findings.extend(scan_text(f.read_text(encoding="utf-8", errors="ignore"), str(f)))
        except OSError:
            continue
    return findings


def main(argv=None) -> int:
    """CLI: ``python -m openatlas.utils.secret_lint <path>``. Exit 1 if findings."""
    import json
    import sys

    args = argv if argv is not None else sys.argv[1:]
    target = args[0] if args else str(default_target())
    try:
        findings = scan_path(target, package=not args)
        if not args:
            for stray in stray_copies(target):
                print(f"note: skipped {stray} - not part of the package (an old copy?); safe to delete")
    except FileNotFoundError as exc:
        print(exc)
        return 2
    if findings:
        print(json.dumps(findings, indent=2))
        print(f"\n{len(findings)} finding(s) - FAIL")
        return 1
    print(f"no secrets/paid-keys found in {target} - OK")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(main())
