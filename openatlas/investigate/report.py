"""Render a case report as Markdown (for export / terminal output)."""

from __future__ import annotations

from typing import Any, Dict

ICON = {"confirmed": "✓", "refuted": "✗", "unverified": "○"}


def to_markdown(report: Dict[str, Any]) -> str:
    t = report["target"]
    s = report["summary"]
    lines = [
        f"# Case {report['case_id']}: {report['name']}",
        "",
        f"- **Target:** `{t['value']}` ({t['type']})",
        f"- **Purpose:** {report['purpose']}",
        f"- **Finished:** {report['finished_at']} in {report['elapsed_s']} s",
        f"- **Findings:** {s['findings']} — {s['confirmed']} confirmed, {s['unverified']} unverified, "
        f"{s['refuted']} refuted",
        "",
    ]
    if report.get("ai_summary"):
        lines += ["## Local AI summary", "", report["ai_summary"], ""]
    lines += ["## Findings", ""]
    for i, e in enumerate(report["evidence"], 1):
        link = f" — <{e['url']}>" if e.get("url") else ""
        lines.append(f"{i}. {ICON[e['status']]} **{e['title']}** "
                     f"({e['source']}, {int(e['confidence'] * 100)}%){link}")
        if e.get("snippet"):
            lines.append(f"   > {e['snippet'][:300]}")
        why = (e.get("verification") or {}).get("result") or (e.get("verification") or {}).get("reason")
        if why:
            lines.append(f"   _{e['status']}: {why}_")
    if report.get("entities"):
        lines += ["", "## Entities", "", "| type | value | sources | confidence |", "|---|---|---|---|"]
        for ent in report["entities"][:50]:
            lines.append(f"| {ent['type']} | {ent['value']} | {', '.join(ent['sources'])} | "
                         f"{int(ent['confidence'] * 100)}% |")
    lines += ["", "## What was searched", ""]
    for r in report["searched"]:
        status = "ok" if r["ok"] else f"failed: {r['error']}"
        lines.append(f"- **{r['source']}** — {r['searched']} → {r['found']} found ({status})")
    return "\n".join(lines) + "\n"
