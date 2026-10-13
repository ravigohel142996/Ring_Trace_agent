"""
app/dashboard.py
------------------
RingTrace — Fraud-Ring Detective Agent. Streamlit investigator dashboard.

Run with:  streamlit run app/dashboard.py --server.address 0.0.0.0

Sections (per hackathon spec):
  A. Investigation Input   B. Agent Investigation (live tool trace)
  C. Graph View            D. Risk                  E. Evidence
  F. Final Decision        G. Case Report
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import tools  # noqa: E402  (side-effect: registers all tools into REGISTRY)
from agent.decision import ACTION_DESCRIPTIONS  # noqa: E402
from agent.investigator import Investigator  # noqa: E402
from agent.report import build_case_report_markdown  # noqa: E402
from app.graph_viz import build_investigation_network  # noqa: E402
from graph.connection import health_check  # noqa: E402
from tools.base import REGISTRY  # noqa: E402

st.set_page_config(page_title="RingTrace — Fraud-Ring Detective", page_icon="\U0001F575\uFE0F", layout="wide")

RISK_COLORS = {"CRITICAL": "#ef4444", "HIGH": "#f97316", "MEDIUM": "#eab308", "LOW": "#22c55e"}

DEMO_PRESETS = {
    "Case C — Dense ring + confirmed money flow (expect CRITICAL)": "A1027",
    "Case B — Shared-IP identity cluster, no money trail (expect HIGH)": "A1200",
    "Case A — Isolated / low connectivity (expect LOW)": "A1100",
    "DEMO-01 — Clean, isolated account": "A1300",
    "DEMO-02 — Benign shared device, no money (should NOT escalate)": "A1310",
    "DEMO-03 — Reciprocal wash-trading ring (no shared identity)": "A1320",
    "DEMO-04 — Layered movement ending in a real merchant purchase": "A1332",
    "DEMO-05 — Benign: two strangers who shop at the same merchant": "A1340",
    "DEMO-06 — Genuinely ambiguous (weak signal, should be MEDIUM)": "A1350",
}


@st.cache_resource(show_spinner=False)
def get_investigator() -> Investigator:
    return Investigator()


def init_state():
    st.session_state.setdefault("result", None)
    st.session_state.setdefault("account_input", "A1027")


def render_sidebar():
    with st.sidebar:
        st.markdown("## \U0001F575\uFE0F RingTrace")
        st.caption("Fraud-Ring Detective Agent — WeMakeDevs x FalkorDB Graph Hacks 2026")

        health = health_check()
        if health["connected"]:
            st.success(f"FalkorDB connected\n\n`{health['host']}:{health['port']}` · graph `{health['graph']}`")
        else:
            st.error(f"FalkorDB unreachable: {health['error']}")

        provider = os.getenv("LLM_PROVIDER", "none").lower()
        if provider not in ("", "none") and os.getenv("LLM_API_KEY"):
            st.info(f"\U0001F9E0 LLM tool-calling ACTIVE\n\n{provider} / {os.getenv('LLM_MODEL', '')}")
        else:
            st.warning("\U0001F9E0 No LLM configured — using the deterministic rule-based planner "
                       "(fully functional, same tools, same graph evidence).")

        st.markdown("---")
        st.caption(f"Registered tools: {len(REGISTRY.all())} "
                   f"({len(REGISTRY.all('investigation'))} investigation, {len(REGISTRY.all('action'))} action)")
        with st.expander("Tool registry"):
            for spec in REGISTRY.all():
                st.markdown(f"**`{spec.name}`** _{spec.category}_  \n{spec.description}")

        st.markdown("---")
        st.warning("\u26A0\uFE0F All accounts, transactions, and identities in this demo are **100% synthetic**, "
                   "generated for this hackathon. No real individuals or financial systems are involved. "
                   "Simulated graph actions are available only through the authenticated API; this legacy view is read-only for actions.")


def render_investigation_input():
    st.markdown("### A. Investigation Input")
    col1, col2 = st.columns([2, 1])
    with col1:
        preset = st.selectbox("Quick demo scenarios (prove graph drives the decision)",
                               ["— choose a preset —"] + list(DEMO_PRESETS.keys()))
        if preset != "— choose a preset —":
            st.session_state.account_input = DEMO_PRESETS[preset]
        account_id = st.text_input("Account / Alert ID", key="account_input")
        query = st.text_area("Optional natural-language instruction for the agent",
                              placeholder="e.g. 'Investigate this account and check if it's part of a larger ring.'",
                              height=70)
    with col2:
        st.markdown("&nbsp;")
        run = st.button("\U0001F50E Run Investigation", type="primary", use_container_width=True)
        st.caption("The agent decides which graph tools to call based on what each tool returns — "
                  "it does not run a fixed script.")
    return account_id.strip(), query.strip(), run


def render_agent_trace(result):
    st.markdown("### B. Agent Investigation — Live Tool Trace")
    st.caption(f"Planner mode: **{result.mode}** · {len(result.steps)} tool call(s)")
    for i, step in enumerate(result.steps, 1):
        icon = "\u2705" if step["ok"] else "\u274C"
        with st.expander(f"{icon} Step {i}: `{step['tool']}` — {step['summary']}", expanded=(i == len(result.steps))):
            st.write(step["summary"])
            if step.get("data") is not None:
                st.json(step["data"], expanded=False)
            if step.get("error"):
                st.error(step["error"])
            st.caption(f"{step.get('duration_ms', 0):.1f} ms")
    if result.narrative:
        st.markdown("**Agent narrative:**")
        st.info(result.narrative)


def render_graph_view(result):
    st.markdown("### C. Graph View")
    st.caption("Nodes: \U0001F535 target account · \U0001F7E1 likely ring leader · \U0001F7E6 other ring members · "
               "\U0001F7E2 outside/legit account · \U0001F536 shared device · \u25A0 shared IP. "
               "Red edges = traced money flow, dashed = shared identity, solid gray = ring linkage.")
    try:
        html = build_investigation_network(result.account_id, result.steps, result.verdict)
        components.html(html, height=580, scrolling=False)
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not render graph view: {exc}")


def render_risk_panel(result):
    st.markdown("### D. Risk")
    verdict = result.verdict
    risk_score = verdict.get("risk_score", 0.0)
    risk_class = verdict.get("risk_class", "LOW")
    color = RISK_COLORS.get(risk_class, "#22c55e")

    col1, col2 = st.columns([1, 2])
    with col1:
        fig = go.Figure(go.Indicator(
            mode="gauge+number", value=risk_score * 100,
            number={"suffix": "%", "font": {"color": color}},
            gauge={"axis": {"range": [0, 100]}, "bar": {"color": color},
                   "steps": [{"range": [0, 20], "color": "#dcfce7"}, {"range": [20, 55], "color": "#fef9c3"},
                             {"range": [55, 72], "color": "#ffedd5"}, {"range": [72, 100], "color": "#fee2e2"}]},
            title={"text": f"Risk Class: {risk_class}"}))
        fig.update_layout(height=260, margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        raw = verdict.get("raw_model_score")
        if raw is not None and verdict.get("graph_guardrail_applied"):
            st.markdown(f"**Raw ML model score:** {raw:.2f} → **Graph-evidence-adjusted score:** {risk_score:.2f}")
            st.caption("A graph-evidence guardrail capped the raw ML score because the graph did not show "
                      "corroborating evidence (e.g. a confirmed money trail or proximity to a known alert) for a "
                      "higher verdict. This keeps the final decision explainable and grounded in the graph, not "
                      "just the model's opinion.")
        pts = verdict.get("graph_evidence_points")
        if pts is not None:
            st.markdown(f"**Graph evidence points:** {pts:.1f}")
        st.caption(f"Scoring method: {verdict.get('risk_method', 'n/a')}")

        feats = verdict.get("top_contributing_features") or []
        if feats:
            df = pd.DataFrame(feats)
            # attribution is None for the no-model heuristic fallback; fall back to raw value then.
            df["bar_value"] = df["attribution"].fillna(df["value"]) if "attribution" in df else df["value"]
            fig2 = go.Figure(go.Bar(x=df["bar_value"], y=df["feature"], orientation="h", marker_color=color))
            fig2.update_layout(height=260, margin=dict(l=10, r=10, t=30, b=10),
                                title="Top contributing graph features", yaxis={"autorange": "reversed"})
            st.plotly_chart(fig2, use_container_width=True)


def render_evidence(result):
    st.markdown("### E. Evidence")
    verdict = result.verdict
    for i, line in enumerate(verdict.get("reasoning", []), 1):
        st.markdown(f"**{i}.** {line}")

    if verdict.get("money_path"):
        mp = verdict["money_path"]
        with st.expander(f"\U0001F4B8 Money path ({mp['hops']} hop(s)): {' → '.join(mp['accounts'])}", expanded=True):
            if mp.get("transfers"):
                st.dataframe(pd.DataFrame(mp["transfers"]), use_container_width=True, hide_index=True)

    if len(verdict.get("ring_members", [])) > 1:
        with st.expander(f"\U0001F465 Ring members ({len(verdict['ring_members'])})"):
            st.write(", ".join(verdict["ring_members"]))
            if verdict.get("ring_leader"):
                st.caption(f"Likely leader (highest money-flow PageRank): **{verdict['ring_leader']}**")


def render_decision(result):
    st.markdown("### F. Final Decision")
    verdict = result.verdict
    risk_class = verdict.get("risk_class", "LOW")
    color = RISK_COLORS.get(risk_class, "#22c55e")
    st.markdown(
        f"""<div style="padding:16px;border-radius:10px;border:2px solid {color};background:{color}22">
        <h3 style="margin:0;color:{color}">{verdict.get('verdict')}</h3>
        <p style="margin:4px 0 0 0">Confidence: <b>{verdict.get('confidence', 0):.0%}</b> ·
        Risk score: <b>{verdict.get('risk_score', 0):.2f}</b> ({risk_class})</p>
        </div>""", unsafe_allow_html=True)

    action = verdict.get("recommended_action", "NO_ACTION_REQUIRED")
    st.markdown(f"**Recommended action:** `{action}`")
    st.caption(ACTION_DESCRIPTIONS.get(action, ""))

    st.warning(
        "Direct graph actions are disabled in this legacy Streamlit view. "
        "Use the authenticated React/API action flow to sign in, approve, and explicitly confirm an action."
    )


def render_case_report(result):
    st.markdown("### G. Case Report")
    markdown = build_case_report_markdown(result.account_id, result.steps, result.verdict)
    st.download_button("\u2B07\uFE0F Download Case Report (Markdown)", data=markdown,
                       file_name=f"ringtrace_case_{result.account_id}.md", mime="text/markdown")
    with st.expander("Preview report", expanded=False):
        st.markdown(markdown)
    # Also persist a server-side copy under ./reports (this is what the `./reports`
    # volume in docker-compose.yml is for — reports survive container restarts and
    # are inspectable on the host without going through the browser download).
    try:
        reports_dir = Path(__file__).resolve().parent.parent / "reports"
        reports_dir.mkdir(exist_ok=True)
        (reports_dir / f"ringtrace_case_{result.account_id}.md").write_text(markdown)
    except OSError:
        pass  # read-only filesystem or similar — the in-browser download still works


def render_why_this_action(result):
    """The dedicated 'WHY DID RINGTRACE TAKE THIS ACTION?' panel (judge-facing
    centerpiece): makes the full causal chain

        GRAPH FACTS -> TOOL CALLS -> EVIDENCE -> RISK -> DECISION -> ACTION

    impossible to miss, with every number traced back to a specific FalkorDB
    query result already captured in the evidence trail — nothing here is
    re-derived or guessed, it's all read straight out of `result.verdict`
    and `result.steps`.
    """
    verdict = result.verdict
    risk_class = verdict.get("risk_class", "LOW")
    color = RISK_COLORS.get(risk_class, "#22c55e")

    st.markdown(
        f"""<div style="padding:14px 18px;border-radius:10px;background:#111827;color:#e5e7eb;">
        <b>WITHOUT FALKORDB, THIS DECISION COULD NOT HAVE BEEN MADE.</b><br/>
        <span style="color:#9ca3af;font-size:0.9em">Every box below is one real, parameterized Cypher query
        result — ring membership came from <code>algo.WCC</code>, the leader came from
        <code>algo.pageRank</code>, the money trail came from a variable-length
        <code>TRANSFERRED_TO*</code> path match. Remove the graph and none of this evidence exists.</span>
        </div>""",
        unsafe_allow_html=True,
    )
    st.markdown("")

    c1, c2, c3 = st.columns(3)

    with c1:
        st.markdown("#### \U0001F4CA 1. GRAPH FACTS")
        st.metric("Connected component size", len(verdict.get("ring_members", [result.account_id])))
        st.metric("Ring score (composite)", f"{verdict.get('ring_score', 0.0):.2f}")
        st.metric("Ring confidence", f"{verdict.get('ring_confidence', 0.0):.2f}")
        if verdict.get("ring_leader"):
            st.caption(f"\U0001F451 Ring leader (PageRank): **{verdict['ring_leader']}**")
        if verdict.get("money_path"):
            mp = verdict["money_path"]
            st.caption(f"\U0001F4B8 Money path: {' → '.join(mp['accounts'])} ({mp['hops']} hop(s))")
        st.caption(f"\U0001F517 Shared devices: {verdict.get('shared_device_account_count', 0)} account(s) · "
                   f"Shared IPs: {verdict.get('shared_ip_account_count', 0)} account(s)")

        st.markdown("#### \U0001F6E0\uFE0F 2. TOOL CALLS")
        tools_used = verdict.get("tools_used") or sorted({s["tool"] for s in result.steps if s.get("ok")})
        for t in tools_used:
            st.markdown(f"- `{t}`")

    with c2:
        st.markdown("#### \U0001F4DD 3. EVIDENCE (reasoning trail)")
        for i, line in enumerate(verdict.get("reasoning", []), 1):
            st.markdown(f"{i}. {line}")

    with c3:
        st.markdown("#### \u2696\uFE0F 4. RISK")
        st.markdown(f"**{verdict.get('risk_score', 0):.2f}** ({risk_class}) via `{verdict.get('risk_method', 'n/a')}`")
        if verdict.get("graph_guardrail_applied"):
            st.caption(f"Raw model: {verdict.get('raw_model_score', 0):.2f} → graph-guardrail-adjusted: "
                       f"{verdict.get('risk_score', 0):.2f}")

        st.markdown("#### \U0001F3AF 5. DECISION")
        st.markdown(f"<span style='color:{color};font-weight:700'>{verdict.get('verdict')}</span> "
                    f"(confidence {verdict.get('confidence', 0):.0%})", unsafe_allow_html=True)

        st.markdown("#### \u26A1 6. ACTION")
        action = verdict.get("recommended_action", "NO_ACTION_REQUIRED")
        st.markdown(f"`{action}`")
        st.caption(ACTION_DESCRIPTIONS.get(action, ""))


def main():
    init_state()
    render_sidebar()

    st.title("\U0001F575\uFE0F RingTrace — Fraud-Ring Detective Agent")
    st.caption("FalkorDB is the agent's live reasoning context — every tool call below queries the graph directly, "
              "and the graph's own structure (who shares devices/IPs, how money flows, who's connected to whom) "
              "is what drives the final verdict below, not a canned script.")

    account_id, query, run = render_investigation_input()

    if run and account_id:
        inv = get_investigator()
        with st.spinner(f"Investigating {account_id}... querying FalkorDB, running graph algorithms, scoring risk"):
            st.session_state.result = inv.investigate(account_id=account_id, query=query)

    result = st.session_state.result
    if result is None:
        st.info("Enter an account ID (try a demo preset above) and click **Run Investigation** to begin.")
        return

    if result.error:
        st.error(result.error)
        return

    st.markdown("---")
    tabs = st.tabs(["\U0001F50D Why This Action?", "B. Agent Trace", "C. Graph View", "D. Risk",
                    "E. Evidence", "F. Decision", "G. Case Report"])
    with tabs[0]:
        render_why_this_action(result)
    with tabs[1]:
        render_agent_trace(result)
    with tabs[2]:
        render_graph_view(result)
    with tabs[3]:
        render_risk_panel(result)
    with tabs[4]:
        render_evidence(result)
    with tabs[5]:
        render_decision(result)
    with tabs[6]:
        render_case_report(result)


if __name__ == "__main__":
    main()
