"""Reddit engines (rkE, ruE) - public Reddit JSON, no authentication.

Reddit exposes public ``.json`` endpoints for profiles, submissions and search. We
read only these public endpoints with an honest UA. No login, no OAuth.
"""

from __future__ import annotations

from typing import Any, Dict, List

from openatlas.config import Config
from openatlas.core.registry import BaseTool, ToolRegistry, ToolResult, ToolSpec
from openatlas.utils.http import api_get_json


def _children(payload: Any) -> List[Dict[str, Any]]:
    try:
        return [c["data"] for c in payload["data"]["children"]]
    except (KeyError, TypeError):
        return []


@ToolRegistry.register("reddit-known-username")
class RedditKnownEngine(BaseTool):
    abbrev = "rkE"
    description = "Query public Reddit JSON endpoints for a known username."

    specs = {
        "fetch_comments": ToolSpec(
            name="fetch_comments",
            description="Fetch a Reddit user's recent public comments.",
            parameters={
                "username": {"type": "string", "required": True, "description": "Reddit username"},
                "limit": {"type": "integer", "required": False, "description": "Max comments"},
            },
            backend="reddit public json", network=True,
        ),
        "fetch_about": ToolSpec(
            name="fetch_about",
            description="Fetch public account details for a Reddit user.",
            parameters={"username": {"type": "string", "required": True, "description": "Reddit username"}},
            backend="reddit public json", network=True,
        ),
        "fetch_user_posts": ToolSpec(
            name="fetch_user_posts",
            description="Fetch a Reddit user's recent public submissions.",
            parameters={"username": {"type": "string", "required": True, "description": "Reddit username"}},
            backend="reddit public json", network=True,
        ),
    }

    @staticmethod
    def fetch_about(username: str) -> ToolResult:
        data = api_get_json(Config.services.reddit_about.format(username=username))
        if not data or "data" not in data:
            return ToolResult.failure("fetch_about", f"user '{username}' not found or unavailable")
        d = data["data"]
        keep = {k: d.get(k) for k in ("name", "created_utc", "comment_karma", "link_karma",
                                      "is_gold", "is_mod", "verified", "subreddit")}
        return ToolResult(tool_name="fetch_about", content=keep, success=True)

    @staticmethod
    def fetch_comments(username: str, limit: int = 100) -> ToolResult:
        data = api_get_json(
            Config.services.reddit_comments.format(username=username), params={"limit": limit}
        )
        if data is None:
            return ToolResult.unavailable("fetch_comments", "reddit unreachable or user unavailable")
        rows = [
            {"subreddit": c.get("subreddit"), "body": c.get("body"),
             "score": c.get("score"), "created_utc": c.get("created_utc"),
             "link_title": c.get("link_title")}
            for c in _children(data)
        ]
        return ToolResult(tool_name="fetch_comments", content={"username": username, "comments": rows},
                          success=True)

    @staticmethod
    def fetch_user_posts(username: str) -> ToolResult:
        data = api_get_json(Config.services.reddit_posts.format(username=username))
        if data is None:
            return ToolResult.unavailable("fetch_user_posts", "reddit unreachable or user unavailable")
        rows = [
            {"subreddit": c.get("subreddit"), "title": c.get("title"),
             "score": c.get("score"), "num_comments": c.get("num_comments"),
             "url": c.get("url"), "created_utc": c.get("created_utc")}
            for c in _children(data)
        ]
        return ToolResult(tool_name="fetch_user_posts", content={"username": username, "posts": rows},
                          success=True)


@ToolRegistry.register("reddit-unknown-username")
class RedditUnknownEngine(BaseTool):
    abbrev = "ruE"
    description = "Search public Reddit without a known username."

    specs = {
        "search_reddit_posts": ToolSpec(
            name="search_reddit_posts",
            description="Search public Reddit posts matching a query, optionally within a subreddit.",
            parameters={
                "query": {"type": "string", "required": True, "description": "Keywords"},
                "subreddit": {"type": "string", "required": False, "description": "Restrict to subreddit"},
                "t": {"type": "string", "required": False, "description": "day/week/month/year/all"},
                "limit": {"type": "integer", "required": False, "description": "Max results"},
                "sort": {"type": "string", "required": False, "description": "relevance/new/top/hot"},
                "restrict_sr": {"type": "boolean", "required": False, "description": "Stay in subreddit"},
            },
            backend="reddit public json", network=True,
        ),
        "fetch_post_details": ToolSpec(
            name="fetch_post_details",
            description="Fetch details of a specific public Reddit post.",
            parameters={
                "subreddit": {"type": "string", "required": True, "description": "Subreddit"},
                "post_id": {"type": "string", "required": True, "description": "Post ID"},
            },
            backend="reddit public json", network=True,
        ),
    }

    @staticmethod
    def search_reddit_posts(query: str, subreddit: str = None, t: str = "all", limit: int = 25,
                            sort: str = "relevance", restrict_sr: bool = True) -> ToolResult:
        params = {"q": query, "t": t, "limit": limit, "sort": sort}
        if subreddit:
            url = f"https://www.reddit.com/r/{subreddit}/search.json"
            params["restrict_sr"] = "1" if restrict_sr else "0"
        else:
            url = Config.services.reddit_search
        data = api_get_json(url, params=params)
        if data is None:
            return ToolResult.unavailable("search_reddit_posts", "reddit search unreachable")
        rows = [
            {"subreddit": c.get("subreddit"), "title": c.get("title"), "id": c.get("id"),
             "score": c.get("score"), "url": c.get("url"), "permalink": c.get("permalink")}
            for c in _children(data)
        ]
        return ToolResult(tool_name="search_reddit_posts", content={"query": query, "results": rows},
                          success=True)

    @staticmethod
    def fetch_post_details(subreddit: str, post_id: str) -> ToolResult:
        data = api_get_json(Config.services.reddit_post.format(subreddit=subreddit, post_id=post_id))
        if not data:
            return ToolResult.failure("fetch_post_details", "post not found or unavailable")
        posts = _children(data[0]) if isinstance(data, list) and data else []
        return ToolResult(tool_name="fetch_post_details",
                          content={"post": posts[0] if posts else None}, success=bool(posts))
