"""OSINT engines. Importing this package registers every engine in the ToolRegistry.

Each submodule defines one (or more) BaseTool subclass(es) decorated with
``@ToolRegistry.register(...)``. All backends are free/keyless/local; every
web-scraping call is robots-gated via openatlas.utils.http.scrape_get.
"""

from __future__ import annotations

# Order doesn't matter; importing each module runs its @register decorator.
# DeepScan lives with image_analysis's neighbours but ships its own module.
from openatlas.tools import (  # noqa: F401
    ai_image_detector,
    browser_automation,
    deep_scan,  # noqa: F401,E402
    email_checker,
    geolocation,
    get_pages,
    github_apis,
    haveibeenpwned,
    hunt_emails,
    hyperlink_extractor,
    image_analysis,
    ip_lookups,
    nettacker,
    oathnet,
    perplexity,
    reddit_lookup,
    reverse_instagram_lookup,
    username_search,
)
