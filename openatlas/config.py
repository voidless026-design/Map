"""Central configuration for OpenAtlas.

This mirrors the shape of upstream OAtlas's ``config.py`` (a ``ConfigBase`` with
nested ``Database``/``Settings``/``Files`` groups and per-service endpoint
blocks) but every backend here is **free, keyless, or local**. There is no place
to put a paid API key, and none is ever read.

Design choices for the free/local stack
----------------------------------------
* LLM/vision/reasoning        -> Ollama (OpenAI-compatible), ``OLLAMA_HOST``.
* Web search (was Perplexity) -> DuckDuckGo via ``ddgs``.
* Breach checks (was HIBP/OathNet paid) -> HIBP *Pwned Passwords* range API
  (keyless) + XposedOrNot email breach API (keyless).
* Email discovery (was Hunter.io) -> Holehe + MX verification.
* Username enumeration         -> WhatsMyName OSS dataset.
* IP lookups (was IPinfo paid) -> ip-api.com / ipapi.co (keyless) + RIPEstat.
* AI-image detection (was isgen.ai) -> local Hugging Face model + C2PA/EXIF.
* Geolocation (was Picarta)    -> EXIF GPS + Ollama vision + Nominatim geocode.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterator

from dotenv import load_dotenv

# Load an optional local .env (never committed). It may hold nothing more than
# tuning knobs like OLLAMA_HOST or a custom DB URL. No paid keys.
load_dotenv(".env")
load_dotenv(".env.private")  # kept for OAtlas parity; still key-free here.


class ConfigBase:
    """Base class giving each config group dict-conversion and iteration."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            k: getattr(self, k)
            for k in dir(self)
            if not k.startswith("_") and not callable(getattr(self, k))
        }

    def __iter__(self) -> Iterator[Any]:
        return iter(self.to_dict().items())


# --------------------------------------------------------------------------- #
# Paths / files
# --------------------------------------------------------------------------- #
_PKG_ROOT = Path(__file__).resolve().parent
_PROJECT_ROOT = _PKG_ROOT.parent


class Files(ConfigBase):
    package_root = _PKG_ROOT
    project_root = _PROJECT_ROOT
    data_dir = _PROJECT_ROOT / "data"
    output_dir = _PROJECT_ROOT / "output"
    robots_cache = _PROJECT_ROOT / "data" / "robots_cache"
    banner = _PKG_ROOT / "banner.txt"
    methods_yaml = _PKG_ROOT / "methods" / "methods.yaml"
    whatsmyname = _PROJECT_ROOT / "data" / "wmn-data.json"
    secret_rules = _PKG_ROOT / "tools" / "secret_rules.yaml"


# --------------------------------------------------------------------------- #
# Database (SQLite default, MySQL / PostgreSQL optional - all free)
# --------------------------------------------------------------------------- #
class Database(ConfigBase):
    # One of: sqlite | mysql | postgres
    backend = os.getenv("OPENATLAS_DB_BACKEND", "sqlite")
    # Full SQLAlchemy URL wins if provided.
    url = os.getenv("OPENATLAS_DB_URL", "")
    sqlite_path = os.getenv(
        "OPENATLAS_SQLITE_PATH", str(_PROJECT_ROOT / "data" / "openatlas.db")
    )
    # Used only when backend is mysql/postgres and no explicit URL is set.
    host = os.getenv("OPENATLAS_DB_HOST", "localhost")
    port = os.getenv("OPENATLAS_DB_PORT", "")
    name = os.getenv("OPENATLAS_DB_NAME", "openatlas")
    user = os.getenv("OPENATLAS_DB_USER", "openatlas")
    password = os.getenv("OPENATLAS_DB_PASSWORD", "")
    echo = os.getenv("OPENATLAS_DB_ECHO", "0") == "1"


# --------------------------------------------------------------------------- #
# LLM / reasoning - Ollama only, OpenAI-compatible endpoint
# --------------------------------------------------------------------------- #
class LLM(ConfigBase):
    # e.g. http://localhost:11434 ; the OpenAI-compatible path is /v1
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    base_url = host.rstrip("/") + "/v1"
    # A dummy key satisfies the OpenAI client; Ollama ignores it.
    api_key = os.getenv("OLLAMA_API_KEY", "ollama")
    text_model = os.getenv("OPENATLAS_LLM_MODEL", "llama3.1:8b")
    vision_model = os.getenv("OPENATLAS_VISION_MODEL", "llava:7b")
    request_timeout = int(os.getenv("OPENATLAS_LLM_TIMEOUT", "60"))
    temperature = float(os.getenv("OPENATLAS_LLM_TEMPERATURE", "0.2"))


# --------------------------------------------------------------------------- #
# Per-service endpoints (all keyless / public)
# --------------------------------------------------------------------------- #
class Services(ConfigBase):
    # Truthful, contactable UA. We do NOT impersonate browsers to defeat bots.
    user_agent = os.getenv(
        "OPENATLAS_USER_AGENT",
        "OpenAtlas-OSINT/0.1 (+https://github.com/voidless026-design/Map; public-data-only)",
    )
    http_timeout = int(os.getenv("OPENATLAS_HTTP_TIMEOUT", "20"))

    # Reddit public JSON
    reddit_about = "https://www.reddit.com/user/{username}/about.json"
    reddit_comments = "https://www.reddit.com/user/{username}/comments.json"
    reddit_posts = "https://www.reddit.com/user/{username}/submitted.json"
    reddit_search = "https://www.reddit.com/search.json"
    reddit_post = "https://www.reddit.com/r/{subreddit}/comments/{post_id}.json"

    # GitHub public REST (unauthenticated; low rate limit but no key)
    github_user = "https://api.github.com/users/{username}"
    github_repos = "https://api.github.com/users/{username}/repos?per_page=100&type=owner"

    # IP lookups (keyless)
    ip_api = "http://ip-api.com/json/{ip}?fields=66846719"
    ipapi_co = "https://ipapi.co/{ip}/json/"
    ripestat_asn = "https://stat.ripe.net/data/as-overview/data.json?resource=AS{asn}"

    # Breach checks (keyless)
    hibp_pwned_passwords_range = "https://api.pwnedpasswords.com/range/{prefix}"
    xposedornot_breaches = "https://api.xposedornot.com/v1/check-email/{email}"
    xposedornot_analytics = "https://api.xposedornot.com/v1/breach-analytics?email={email}"

    # Reverse geocoding (keyless, respect usage policy: <=1 req/s)
    nominatim_reverse = "https://nominatim.openstreetmap.org/reverse"

    # Instagram / others are handled by public HTML parsing in their modules.


class Settings(ConfigBase):
    # CLI-facing defaults (mirror upstream flag names where sensible)
    show_version = False
    show_api_services = False
    show_all_functions = False
    show_help_menu = False
    functions: list[str] = []
    verbose_mode = False
    use_llm = False  # replaces upstream '-o/--use-openai'; here means "use Ollama"
    # Nettacker / scanning must be explicitly authorized by the operator.
    authorized_target = False


class Web(ConfigBase):
    start_api_server = False
    host = os.getenv("OPENATLAS_WEB_HOST", "127.0.0.1")
    port = int(os.getenv("OPENATLAS_WEB_PORT", "8501"))


class BA(ConfigBase):
    """Browser-automation (PyBA reimplementation) settings."""

    headless = os.getenv("OPENATLAS_BA_HEADLESS", "1") == "1"
    enable_tracing = os.getenv("OPENATLAS_BA_TRACE", "0") == "1"
    max_depth = int(os.getenv("OPENATLAS_BA_MAX_DEPTH", "3"))
    low_memory = os.getenv("OPENATLAS_BA_LOW_MEMORY", "0") == "1"
    respect_robots = True  # never negotiable
    solve_captchas = False  # never; we do not bypass CAPTCHAs
    bypass_paywalls = False  # never


class Config:
    """Aggregate config object, imported as ``from openatlas.config import Config``."""

    files = Files()
    database = Database()
    llm = LLM()
    services = Services()
    settings = Settings()
    web = Web()
    ba = BA()

    @staticmethod
    @lru_cache(maxsize=1)
    def read_file(path: str) -> str:
        return Path(path).read_text(encoding="utf-8")


# A registry of every backend this tool talks to, and proof it is free/keyless.
# Rendered by `--show-api-services`.
API_SERVICES: list[dict[str, str]] = [
    {"service": "Ollama (local LLM/vision)", "replaces": "OpenAI / VertexAI", "key": "none (local)"},
    {"service": "DuckDuckGo (ddgs)", "replaces": "Perplexity", "key": "none"},
    {"service": "HIBP Pwned Passwords", "replaces": "HIBP (paid tier)", "key": "none (k-anonymity)"},
    {"service": "XposedOrNot", "replaces": "OathNet breach data", "key": "none"},
    {"service": "Holehe", "replaces": "Hunter.io", "key": "none"},
    {"service": "WhatsMyName dataset", "replaces": "username APIs", "key": "none"},
    {"service": "ip-api.com / ipapi.co", "replaces": "IPinfo (paid)", "key": "none"},
    {"service": "RIPEstat", "replaces": "IPinfo ASN", "key": "none"},
    {"service": "Nominatim (OSM)", "replaces": "Picarta geocode", "key": "none"},
    {"service": "Local HF deepfake model", "replaces": "isgen.ai", "key": "none (local)"},
    {"service": "Public Reddit JSON", "replaces": "Reddit API", "key": "none"},
    {"service": "Public GitHub REST", "replaces": "GitHub token", "key": "none (unauth)"},
]
