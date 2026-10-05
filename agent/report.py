"""
agent/report.py
-----------------
Builds a human-readable investigation case report (Markdown) from the
evidence trail accumulated during an investigation session, plus the final
verdict. Used by the `generate_case_report` tool and the dashboard's
downloadable "Case Report" panel.
"""
from __future__ import annotations

from datetime import datetime, timezone

from agent.decision import ACTION_DESCRIPTIONS


def build_case_report_markdown(account_id: str, steps: list[dict], verdict: dict) -> str:
    """Pure function: given the evidence trail (`steps`, as produced by any
    investigation run) and the final `verdict` dict, render a Markdown case
    report. Decoupled from a live ToolContext so both the agent (mid-loop)
    and the dashboard (post-hoc, from a stored InvestigationResult) can
    produce an identical report."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        f"# RingTrace Investigation Report — {account_id}",
        "",
        f"*Generated {now} — SYNTHETIC DEMO DATA. For hackathon demonstration purposes only.*",
        "",
        "## Verdict",
        f"- **Verdict:** {verdict['verdict']}",
        f"- **Risk score:** {verdict['risk_score']:.2f} ({verdict['risk_class']})",
        f"- **Confidence:** {verdict['confidence']:.2f}",
        f"- **Recommended action:** {verdict['recommended_action']} — "
        f"{ACTION_DESCRIPTIONS.get(verdict['recommended_action'], '')}",
        "",
        "## Reasoning (graph evidence)",
    ]
    for r in verdict["reasoning"]:
        lines.append(f"- {r}")

    lines += ["", "## Ring Membership"]
    if len(verdict["ring_members"]) > 1:
        lines.append(f"- Component size: {len(verdict['ring_members'])}")
        lines.append(f"- Members: {', '.join(verdict['ring_members'])}")
        lines.append(f"- Likely ring leader: {verdict['ring_leader'] or 'not yet determined'}")
    else:
        lines.append("- No connected ring detected.")

    if verdict["money_path"]:
        mp = verdict["money_path"]
        lines += ["", "## Money Path", f"- {' -> '.join(mp['accounts'])} ({mp['hops']} hop(s))"]
        for t in mp.get("transfers", []):
            lines.append(f"  - amount={t.get('amount')} timestamp={t.get('timestamp')} txn_id={t.get('txn_id')}")

    lines += ["", "## Tool Execution History"]
    for entry in steps:
        status = "OK" if entry.get("ok") else "FAILED"
        lines.append(f"- `{entry.get('tool')}` [{status}] — {entry.get('summary')}")

    lines += ["", "## Disclaimer",
              "This report was generated from 100% SYNTHETIC data created for the WeMakeDevs x FalkorDB "
              "Graph Hacks 2026 hackathon. No real individuals, accounts, or transactions are represented."]

    return "\n".join(lines)
