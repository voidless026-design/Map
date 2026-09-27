"""The action catalog: every button in the GUI and every `openatlas run` command.

Two kinds of actions:
* **sources** - evidence-producing investigation sources (``openatlas.investigate``);
* **tools** - the original OAtlas-style engine functions (``openatlas.tools``).

Each action has a human title (no snake_case), a filter chip, an input type, a stable
kebab-case slug, and the exact CLI command the button runs.
"""

from __future__ import annotations

import shlex
from typing import Any, Dict, List, Optional, Tuple

from openatlas.investigate.sources import FILTERS
from openatlas.investigate.sources import load as load_sources

# (engine class, function) -> (slug, title, filter, input type, primary argument)
TOOL_TITLES: Dict[Tuple[str, str], Tuple[str, str, str, str, str]] = {
    ("EmailCheckEngine", "verify_email_address"): ("verify-email", "Verify email address", "email", "email", "email"),
    ("StaticImageExtractionEngine", "extract_metadata"): ("photo-metadata", "Photo metadata (EXIF / C2PA)", "images", "image", "image_path"),
    ("StaticImageExtractionEngine", "scan_firmware"): ("scan-firmware", "Find embedded files & firmware", "code", "file", "image_path"),
    ("StaticImageExtractionEngine", "extract_firmware"): ("carve-bytes", "Carve bytes out of a file", "code", "file", "input_path"),
    ("StaticImageExtractionEngine", "extract_strings"): ("file-strings", "Readable text inside a file", "code", "file", "input_path"),
    ("RedditKnownEngine", "fetch_comments"): ("reddit-comments", "Reddit comments by user", "username", "username", "username"),
    ("RedditKnownEngine", "fetch_about"): ("reddit-account", "Reddit account details", "username", "username", "username"),
    ("RedditKnownEngine", "fetch_user_posts"): ("reddit-posts", "Reddit posts by user", "username", "username", "username"),
    ("RedditUnknownEngine", "search_reddit_posts"): ("reddit-search", "Search Reddit posts", "people", "text", "query"),
    ("RedditUnknownEngine", "fetch_post_details"): ("reddit-post", "Reddit post details", "web", "text", "post_id"),
    ("DeepScanEngine", "OCR_analysis"): ("image-ocr", "Read text in an image (OCR)", "images", "image", "image_path"),
    ("DeepScanEngine", "verify_similar_faces"): ("face-compare", "Compare two faces", "images", "image", "image_path_1"),
    ("DeepScanEngine", "face_attribute_analysis"): ("face-attributes", "Estimate face attributes", "images", "image", "image_path"),
    ("InstagramEngine", "fetch_account_information"): ("instagram-profile", "Instagram public profile", "username", "username", "username"),
    ("InstagramEngine", "fetch_public_account_posts"): ("instagram-posts", "Instagram public posts", "username", "username", "username"),
    ("ImageGeolocationEngine", "geolocate_local_image"): ("photo-gps", "Locate a photo from its GPS", "images", "image", "image_path"),
    ("ImageGeolocationEngine", "geolocate_online_image"): ("online-photo-gps", "Locate an online photo from its GPS", "images", "url", "image_url"),
    ("ImageGeolocationEngine", "geolocate_using_LLMs"): ("photo-guess-location", "Guess where a photo was taken (local AI)", "images", "image", "image_path"),
    ("ImageGeolocationEngine", "combined_llm_deeplearning_analysis"): ("photo-locate", "Locate a photo (GPS + local AI)", "images", "image", "image_path"),
    ("IPinfoEngine", "basic_ip_lookup"): ("ip-lookup", "IP location & owner", "network", "ip", "ipaddress"),
    ("IPinfoEngine", "core_api_lookups"): ("ip-details", "IP details (two sources)", "network", "ip", "ipaddress"),
    ("IPinfoEngine", "core_api_lookups_asn"): ("asn-lookup", "Autonomous system (ASN) details", "network", "text", "asn_number"),
    ("PerplexityEngine", "search_perplexity_text"): ("web-summary", "Web search with summary", "web", "text", "search_request"),
    ("PerplexityEngine", "search_perplexity_images"): ("image-search", "Image search", "images", "text", "search_request"),
    ("UsernameCheckEngine", "check_usernames"): ("username-sweep", "Username across 700+ sites", "username", "username", "username"),
    ("GitHubEngine", "fetch_about"): ("github-profile", "GitHub profile", "code", "username", "username"),
    ("GitHubEngine", "fetch_repos"): ("github-repos", "GitHub repositories", "code", "username", "username"),
    ("GitHubEngine", "get_repo_secrets"): ("repo-secrets", "Leaked secrets in public repos", "code", "url", "repository_names"),
    ("NettackerEngine", "nettacker_run"): ("port-scan", "Port scan (authorized targets only)", "network", "ip", "targets"),
    ("HaveIBeenPwnedEngine", "check_email_against_breach_data"): ("breach-check", "Breach exposure", "breach", "email", "email"),
    ("ProfessionalEmailFinderEngine", "find_emails_for_domain"): ("domain-emails", "Common email addresses for a domain", "email", "domain", "domain_name"),
    ("ProfessionalEmailFinderEngine", "find_emails_for_person"): ("person-email", "Likely email for a person", "email", "domain", "domain_name"),
    ("GetPagesEngine", "fetch_get_page"): ("fetch-page", "Fetch a web page", "web", "url", "url"),
    ("GetPagesEngine", "fetch_get_pages_bulk"): ("fetch-pages", "Fetch several web pages", "web", "url", "urls"),
    ("HyperlinkExtractEngine", "hyperlinks_for_single_url"): ("page-links", "Links on a page", "web", "url", "url"),
    ("HyperlinkExtractEngine", "hyperlinks_for_multiple_urls"): ("pages-links", "Links on several pages", "web", "url", "urls"),
    ("VerifyAIGeneratedImageEngine", "metadata_analysis"): ("ai-image-hints", "AI-image hints in metadata", "images", "image", "image_path"),
    ("VerifyAIGeneratedImageEngine", "deepscan_fake_image_verification"): ("ai-image-model", "AI-image detector (local model)", "images", "image", "image_path"),
    ("VerifyAIGeneratedImageEngine", "isgenAI"): ("ai-image-check", "AI-image check (isgen replacement)", "images", "image", "image_path"),
    ("VerifyAIGeneratedImageEngine", "combined_AI_image_verification"): ("ai-image-verdict", "AI-generated image verdict", "images", "image", "image_path"),
    ("OathNetEngine", "get_breached_data"): ("breach-analytics", "Breach analytics", "breach", "email", "query"),
    ("OathNetEngine", "get_stealer_logs"): ("stealer-logs", "Stealer logs (disabled by policy)", "breach", "email", "query"),
    ("OathNetEngine", "combined_oathnet_search"): ("breach-search", "Breach search (combined)", "breach", "email", "query"),
    ("BrowserAutomationEngine", "run_automated_browser_instance"): ("browser-task", "Browser task on public pages (local AI)", "web", "text", "prompt"),
}

HIDDEN = {"stealer-logs"}  # kept for OAtlas parity, never shown as a button


def cli_for(action: Dict[str, Any], value: str = "<target>") -> str:
    return f"openatlas run {action['slug']} {shlex.quote(value)}"


def actions() -> List[Dict[str, Any]]:
    """Every action, sources first. Stable order."""
    from openatlas.core.registry import ToolRegistry, load_all_engines

    out: List[Dict[str, Any]] = []
    for spec in load_sources().values():
        out.append({"slug": spec.id, "kind": "source", "title": spec.title,
                    "description": spec.description, "filters": list(spec.filters),
                    "inputs": list(spec.applies_to), "default": spec.default,
                    "params": {}})
    load_all_engines()
    for engine in ToolRegistry.engines().values():
        for fname, tspec in engine.specs.items():
            slug, title, filt, itype, primary = TOOL_TITLES[(engine.__name__, fname)]
            if slug in HIDDEN:
                continue
            params = {k: v for k, v in tspec.parameters.items() if k != primary}
            out.append({"slug": slug, "kind": "tool", "title": title,
                        "description": tspec.description, "filters": [filt], "inputs": [itype],
                        "default": False, "engine": engine.__name__, "function": fname,
                        "primary": primary, "params": params})
    for a in out:
        a["cli"] = cli_for(a)
    return out


def catalog() -> Dict[str, Any]:
    return {"filters": [{"id": k, "label": v} for k, v in FILTERS.items()], "actions": actions()}


def find(slug: str) -> Optional[Dict[str, Any]]:
    return next((a for a in actions() if a["slug"] == slug), None)


def run_tool(action: Dict[str, Any], value: str, args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Run an engine function by catalog action; returns the ToolResult as a dict."""
    from openatlas.core.registry import ToolRegistry, load_all_engines

    load_all_engines()
    engine = next(e for e in ToolRegistry.engines().values() if e.__name__ == action["engine"])
    fn = engine.get_callable(action["function"])
    kwargs = dict(args or {})
    ptype = engine.specs[action["function"]].parameters.get(action["primary"], {}).get("type")
    kwargs[action["primary"]] = [v.strip() for v in value.split(",") if v.strip()] \
        if ptype == "array" else value
    result = fn(**kwargs)
    return result.to_dict() if hasattr(result, "to_dict") else {"content": result}
