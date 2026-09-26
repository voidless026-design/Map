"""GitHub public user search + profile (unauthenticated REST API, keyless)."""

from __future__ import annotations

from openatlas.investigate.models import Evidence, SourceResult, Target
from openatlas.investigate.sources import source
from openatlas.net.client import Net

API = "https://api.github.com"
FIELDS = ("name", "company", "blog", "location", "email", "bio", "twitter_username",
          "public_repos", "followers", "created_at")


@source("github", title="GitHub profiles", filters=("people", "username", "email", "code"),
        description="Public GitHub users matching the target, with profile details",
        applies_to=("name", "username", "email"))
async def github(t: Target, net: Net) -> SourceResult:
    if t.type == "username":
        logins = [t.value]
        searched = f"GitHub user '{t.value}'"
    else:
        qualifier = "in:email" if t.type == "email" else "in:name"
        data = await net.get_json(f"{API}/search/users",
                                  params={"q": f"{t.value} {qualifier}", "per_page": 5},
                                  headers={"Accept": "application/vnd.github+json"})
        if data is None:
            return SourceResult("github", ok=False, searched="GitHub user search",
                                error="GitHub API unreachable or rate-limited (60/h unauthenticated)")
        logins = [u["login"] for u in data.get("items", [])[:3]]
        searched = f"GitHub users matching '{t.value}' ({data.get('total_count', 0)} total)"
    res = SourceResult("github", ok=True, searched=searched)
    for login in logins:
        u = await net.get_json(f"{API}/users/{login}",
                               headers={"Accept": "application/vnd.github+json"})
        if not u or "login" not in u:
            continue
        details = {k: u.get(k) for k in FIELDS if u.get(k) not in (None, "")}
        summary = ", ".join(f"{k}: {v}" for k, v in details.items()
                            if k in ("name", "company", "location", "blog", "twitter_username"))
        res.evidence.append(Evidence(
            source="github", kind="profile", title=f"GitHub: {u['login']}"
            + (f" ({u['name']})" if u.get("name") else ""),
            url=u.get("html_url"), snippet=summary or (u.get("bio") or ""),
            entity_type="username", entity_value=u["login"], confidence=0.75,
            verified=True, verification={"method": "first-party API", "source": "api.github.com"},
            data=details,
        ))
        for key, etype in (("email", "email"), ("blog", "url"), ("twitter_username", "username")):
            if u.get(key):
                res.evidence.append(Evidence(
                    source="github", kind="entity",
                    title=f"{key.replace('_', ' ')} listed on GitHub profile {u['login']}",
                    url=u.get("html_url"), snippet=str(u[key]), entity_type=etype,
                    entity_value=str(u[key]).lower(), confidence=0.7, verified=True,
                    verification={"method": "first-party API"}))
    return res
