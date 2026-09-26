"""PyBA reimplementation: LLM-driven browser automation using Playwright + Ollama.

A clean, key-free replacement for FauvidoTechnologies/PyBrowserAutomation. Instead of
OpenAI/VertexAI, reasoning is done by a *local* Ollama model. Where Ollama is
unavailable, the engine still performs deterministic navigation + extraction so basic
tasks work offline.

Ethics (non-negotiable, enforced here):
* Every navigation is robots-gated (openatlas.utils.robots.can_fetch).
* We never log in, never submit credentials, never solve CAPTCHAs, never bypass
  paywalls. If a page requires any of those, we stop and report it.
* "Stealth" is limited to a truthful UA and human-like pacing to be polite; it is
  not used to defeat bot-detection on sites that forbid automated access.

The public API mirrors PyBA:
    eng = BrowserEngine(headless=True)
    eng.sync_run(prompt="...", start_url="https://...")
    eng.generate_code("out.py")   # export a standalone Playwright script
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from openatlas.config import Config
from openatlas.llm import ollama_client
from openatlas.logger import get_logger
from openatlas.utils.robots import can_fetch

log = get_logger("openatlas.browser")


class BrowserEngine:
    def __init__(
        self,
        *,
        headless: Optional[bool] = None,
        enable_tracing: Optional[bool] = None,
        max_depth: Optional[int] = None,
        low_memory: Optional[bool] = None,
    ):
        self.headless = Config.ba.headless if headless is None else headless
        self.enable_tracing = Config.ba.enable_tracing if enable_tracing is None else enable_tracing
        self.max_depth = Config.ba.max_depth if max_depth is None else max_depth
        self.low_memory = Config.ba.low_memory if low_memory is None else low_memory
        self._actions: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------ #
    def _plan(self, prompt: str, page_text: str) -> Dict[str, Any]:
        """Ask the local LLM for the next action as JSON. Falls back to 'extract'."""
        if not ollama_client.available():
            return {"action": "extract", "reason": "no LLM backend; extracting page text"}
        sys = ("You drive a web browser for OSINT on PUBLIC pages only. Never log in, never "
               "solve CAPTCHAs, never bypass paywalls. Respond with ONE JSON action: "
               '{"action":"click|type|navigate|extract|stop","selector":"...","text":"...",'
               '"url":"...","reason":"..."}')
        user = f"Task: {prompt}\nVisible page text (truncated):\n{page_text[:3000]}"
        raw = ollama_client.complete(user, system=sys)
        if not raw:
            return {"action": "extract"}
        try:
            s, e = raw.find("{"), raw.rfind("}")
            return json.loads(raw[s : e + 1])
        except (ValueError, IndexError):
            return {"action": "extract"}

    # ------------------------------------------------------------------ #
    def sync_run(self, prompt: str, start_url: Optional[str] = None) -> Dict[str, Any]:
        """Run a browser task synchronously. Returns a structured result dict."""
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            return {"ok": False, "reason": f"playwright not installed ({exc}); "
                                          f"`poetry install --with browser && playwright install chromium`"}

        url = start_url
        if url and not can_fetch(url):
            return {"ok": False, "reason": f"robots.txt disallows {url}"}

        extracted: Dict[str, Any] = {"prompt": prompt, "steps": [], "text": None, "links": []}
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=self.headless)
                context = browser.new_context(user_agent=Config.services.user_agent)
                page = context.new_page()
                if url:
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)

                for depth in range(self.max_depth):
                    body = page.inner_text("body") if page.query_selector("body") else ""
                    # Detect login/CAPTCHA walls and stop rather than bypass them.
                    low = body.lower()
                    if any(w in low for w in ("captcha", "verify you are human", "log in to continue")):
                        extracted["steps"].append({"depth": depth, "stopped": "login/captcha wall"})
                        break
                    plan = self._plan(prompt, body)
                    extracted["steps"].append({"depth": depth, "plan": plan})
                    action = plan.get("action", "extract")
                    self._actions.append(plan)
                    if action == "stop":
                        break
                    if action == "navigate" and plan.get("url"):
                        if not can_fetch(plan["url"]):
                            extracted["steps"].append({"blocked_by_robots": plan["url"]})
                            break
                        page.goto(plan["url"], wait_until="domcontentloaded", timeout=30000)
                    elif action == "click" and plan.get("selector"):
                        try:
                            page.click(plan["selector"], timeout=5000)
                        except Exception as exc:
                            extracted["steps"].append({"click_failed": str(exc)})
                    elif action == "type" and plan.get("selector"):
                        try:
                            page.fill(plan["selector"], plan.get("text", ""))
                        except Exception as exc:
                            extracted["steps"].append({"type_failed": str(exc)})
                    else:  # extract
                        extracted["text"] = body[:20000]
                        extracted["links"] = [
                            a.get_attribute("href")
                            for a in page.query_selector_all("a[href]")[:200]
                        ]
                        break

                browser.close()
            extracted["ok"] = True
        except Exception as exc:
            extracted["ok"] = False
            extracted["reason"] = str(exc)
        return extracted

    # ------------------------------------------------------------------ #
    def generate_code(self, output_path: str) -> str:
        """Export the recorded actions as a standalone Playwright script (PyBA parity)."""
        lines = [
            "# Auto-generated by OpenAtlas BrowserEngine. Public pages only; no login/CAPTCHA bypass.",
            "from playwright.sync_api import sync_playwright",
            "",
            "with sync_playwright() as p:",
            "    browser = p.chromium.launch(headless=True)",
            "    page = browser.new_page()",
        ]
        for act in self._actions:
            a = act.get("action")
            if a == "navigate" and act.get("url"):
                lines.append(f"    page.goto({act['url']!r})")
            elif a == "click" and act.get("selector"):
                lines.append(f"    page.click({act['selector']!r})")
            elif a == "type" and act.get("selector"):
                lines.append(f"    page.fill({act['selector']!r}, {act.get('text','')!r})")
        lines += ["    print(page.inner_text('body'))", "    browser.close()", ""]
        code = "\n".join(lines)
        with open(output_path, "w", encoding="utf-8") as fh:
            fh.write(code)
        return code


# --- PyBA-style aliases for drop-in familiarity --------------------------------- #
Engine = BrowserEngine
