"""BrowserAutomationEngine (BAE) - LLM-driven Playwright automation of public pages.

This is the engine-facing wrapper around the PyBA reimplementation in
``openatlas.browser``. It never logs in, solves CAPTCHAs, or bypasses paywalls, and
every navigation is robots-gated. Reasoning uses local Ollama; with no Ollama it
degrades to deterministic navigation + extraction.
"""

from __future__ import annotations

from openatlas.core.registry import BaseTool, ToolRegistry, ToolResult, ToolSpec
from openatlas.logger import get_logger

log = get_logger("openatlas.tools.browser")


@ToolRegistry.register("browser-automation")
class BrowserAutomationEngine(BaseTool):
    abbrev = "BAE"
    description = "LLM-driven Playwright automation of PUBLIC pages (no CAPTCHA/paywall bypass)."

    specs = {
        "run_automated_browser_instance": ToolSpec(
            name="run_automated_browser_instance",
            description="Drive a headless browser to perform a task on public pages, reasoning via Ollama.",
            parameters={"prompt": {"type": "string", "required": True,
                                   "description": "Task/instruction to perform"}},
            backend="Playwright + Ollama (local)", network=True, scrapes_web=True, needs_llm=True,
        ),
    }

    @staticmethod
    def run_automated_browser_instance(prompt: str) -> ToolResult:
        try:
            from openatlas.browser.engine import BrowserEngine
        except Exception as exc:
            return ToolResult.unavailable(
                "run_automated_browser_instance",
                f"browser stack unavailable ({exc}). Install with `poetry install --with browser` "
                f"and `playwright install chromium`.",
            )
        try:
            result = BrowserEngine().sync_run(prompt=prompt)
        except Exception as exc:
            return ToolResult.unavailable("run_automated_browser_instance",
                                          f"browser run failed: {exc}")
        return ToolResult(tool_name="run_automated_browser_instance", content=result, success=True)
