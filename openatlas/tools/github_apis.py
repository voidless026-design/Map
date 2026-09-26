"""GitHubEngine (ghE) - public GitHub profile/repo info + secret scanning.

* ``fetch_about`` / ``fetch_repos`` hit the public GitHub REST API unauthenticated
  (no token; subject to the low anonymous rate limit).
* ``get_repo_secrets`` clones/reads PUBLIC repositories and applies gitleaks-style
  regexes to surface accidentally-committed secrets. This is a defensive/remediation
  capability, restricted to public repositories only.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List

import yaml

from openatlas.config import Config
from openatlas.core.registry import BaseTool, ToolRegistry, ToolResult, ToolSpec
from openatlas.logger import get_logger
from openatlas.utils.http import api_get_json

log = get_logger("openatlas.tools.github")


def _load_rules() -> List[Dict[str, re.Pattern]]:
    try:
        data = yaml.safe_load(Path(Config.files.secret_rules).read_text(encoding="utf-8"))
        return [{"id": r["id"], "regex": re.compile(r["regex"])} for r in data.get("rules", [])]
    except Exception as exc:  # pragma: no cover
        log.debug("could not load secret rules: %s", exc)
        return []


@ToolRegistry.register("github-search")
class GitHubEngine(BaseTool):
    abbrev = "ghE"
    description = "Public GitHub profile/repo info + gitleaks-style secret scanning."

    specs = {
        "fetch_about": ToolSpec(
            name="fetch_about",
            description="Fetch a public GitHub user's profile details.",
            parameters={"username": {"type": "string", "required": True, "description": "GitHub username"}},
            backend="github public REST", network=True,
        ),
        "fetch_repos": ToolSpec(
            name="fetch_repos",
            description="Fetch a public GitHub user's repositories and metadata.",
            parameters={"username": {"type": "string", "required": True, "description": "GitHub username"}},
            backend="github public REST", network=True,
        ),
        "get_repo_secrets": ToolSpec(
            name="get_repo_secrets",
            description="Scan PUBLIC GitHub repositories for accidentally committed secrets.",
            parameters={"repository_names": {"type": "array", "required": True,
                                             "description": "Public repo URLs to scan"}},
            backend="local git + regex", network=True,
            metadata={"scope": "public repositories only; defensive/remediation use"},
        ),
    }

    @staticmethod
    def fetch_about(username: str) -> ToolResult:
        data = api_get_json(Config.services.github_user.format(username=username))
        if not data or "login" not in data:
            return ToolResult.failure("fetch_about", f"user '{username}' not found or rate-limited")
        keep = {k: data.get(k) for k in ("login", "name", "company", "blog", "location", "bio",
                                         "public_repos", "followers", "following", "created_at",
                                         "updated_at", "avatar_url")}
        return ToolResult(tool_name="fetch_about", content=keep, success=True)

    @staticmethod
    def fetch_repos(username: str) -> ToolResult:
        data = api_get_json(Config.services.github_repos.format(username=username))
        if not isinstance(data, list):
            return ToolResult.failure("fetch_repos", f"no repos for '{username}' or rate-limited")
        repos = {
            r["name"]: {
                "is_fork": r.get("fork"), "stars": r.get("stargazers_count"),
                "language": r.get("language"), "created_at": r.get("created_at"),
                "updated_at": r.get("updated_at"), "html_url": r.get("html_url"),
            }
            for r in data
        }
        return ToolResult(tool_name="fetch_repos", content=repos, success=True)

    @staticmethod
    def get_repo_secrets(repository_names) -> ToolResult:
        if isinstance(repository_names, str):
            repository_names = [r.strip() for r in repository_names.split(",") if r.strip()]
        rules = _load_rules()
        findings: Dict[str, List[Dict[str, str]]] = {}

        for url in repository_names or []:
            # Only public repos, only over https (no credentials embedded).
            if not url.startswith("https://github.com/"):
                findings[url] = [{"error": "only public https github.com URLs are scanned"}]
                continue
            repo_hits: List[Dict[str, str]] = []
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    subprocess.run(
                        ["git", "clone", "--depth", "1", "--quiet", url, tmp + "/repo"],
                        check=True, capture_output=True, timeout=120,
                    )
                except Exception as exc:
                    findings[url] = [{"error": f"clone failed: {exc}"}]
                    continue
                for f in Path(tmp + "/repo").rglob("*"):
                    if not f.is_file() or ".git" in f.parts or f.stat().st_size > 1_000_000:
                        continue
                    try:
                        text = f.read_text(encoding="utf-8", errors="ignore")
                    except OSError:
                        continue
                    for lineno, line in enumerate(text.splitlines(), 1):
                        for rule in rules:
                            if rule["regex"].search(line):
                                repo_hits.append({
                                    "file": str(f.relative_to(tmp + "/repo")),
                                    "line": str(lineno), "rule": rule["id"],
                                    "snippet": line.strip()[:120],
                                })
            findings[url] = repo_hits
        return ToolResult(tool_name="get_repo_secrets", content=findings, success=True)
