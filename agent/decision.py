"""
agent/decision.py
-------------------
Deterministic, explainable decision engine that turns the evidence gathered
during an investigation into a final verdict + recommended action.

This is intentionally NOT left to the LLM: an LLM may draft a narrative, but
the actual action recommendation is produced by transparent rules reading
structured graph evidence, so judges (and real investigators) can audit
exactly why RingTrace recommended what it did. This is also what guarantees
section 7's requirement: identical rule logic, but DIFFERENT graph evidence,
yields a visibly different decision.
"""
from __future__ import annotations

import logging
from typing import Any, Optional


def _latest(evidence_trail: list[dict], tool_name: str, account_id: Optional[str] = None) -> Optional[dict]:
    for entry in reversed(evidence_trail):
        if entry.get("tool") != tool_name or not entry.get("ok"):
            continue
        data = entry.get("data") or {}
        if account_id and isinstance(data, dict):
            # loosely match entries that reference this account where relevant
            aid_fields = [data.get("account_id"), (data.get("account") or {}).get("id")]
            if account_id not in aid_fields and tool_name in ("get_account_context", "calculate_risk_score"):
                if account_id not in aid_fields:
                    continue
        return entry
    return None


def _all_matching(evidence_trail: list[dict], tool_name: str) -> list[dict]:
    return [e for e in evidence_trail if e.get("tool") == tool_name and e.get("ok")]


def build_verdict(ctx, account_id: str) -> dict:
    trail = getattr(ctx, "evidence_trail", [])

    ring_entry = _latest(trail, "find_fraud_ring")
    leader_entry = _latest(trail, "rank_ring_leaders")
    identity_entry = _latest(trail, "find_identity_links")
    money_entries = _all_matching(trail, "trace_money_path")
    risk_entry = _latest(trail, "calculate_risk_score", account_id)
    context_entry = _latest(trail, "get_account_context", account_id)

    # Always guarantee we have a risk score, even if the agent skipped the tool.
    if risk_entry is None:
        cache = ctx.feature_cache()
        risk_data = ctx.risk_scorer.score_account(ctx.graph_store, account_id, cache=cache)
    else:
        risk_data = risk_entry["data"]

    ring_data = (ring_entry or {}).get("data", {}) or {}
    component_size = ring_data.get("size", 1)
    is_ring = ring_data.get("is_ring", False)
    ring_members = ring_data.get("members", [account_id])
    ring_score = ring_data.get("ring_score", 0.0)
    ring_confidence = ring_data.get("ring_confidence", 0.0)
    ring_reasons = ring_data.get("ring_reasons", [])

    leader_data = (leader_entry or {}).get("data", {}) or {}
    ring_leader = leader_data.get("ring_leader")

    identity_data = (identity_entry or {}).get("data", {}) or {}
    shared_device_accounts = {a for d in identity_data.get("shared_devices", []) for a in d.get("other_accounts", [])}
    shared_ip_accounts = {a for d in identity_data.get("shared_ips", []) for a in d.get("other_accounts", [])}

    best_money_path = None
    for e in money_entries:
        for p in (e.get("data", {}) or {}).get("paths", []):
            if best_money_path is None or p.get("hops", 0) > best_money_path.get("hops", 0):
                best_money_path = p

    own_alerts = []
    if context_entry:
        own_alerts = (context_entry.get("data", {}) or {}).get("alerts", []) or []

    risk_score = risk_data.get("risk_score", 0.0)
    risk_class = risk_data.get("risk_class", "LOW")

    # ------------------------------------------------------------------
    # Reasoning trail (human-readable, numbers-first — mirrors the brief's
    # worked example exactly).
    # ------------------------------------------------------------------
    reasoning: list[str] = []
    if component_size > 1:
        reasoning.append(f"{component_size} accounts are in the same connected component "
                          f"({', '.join(ring_members[:12])}{'...' if len(ring_members) > 12 else ''}). "
                          f"Ring score = {ring_score:.2f} (confidence {ring_confidence:.2f}).")
        for r in ring_reasons[1:]:  # skip the generic "N accounts form a component" line, already said above
            reasoning.append(r)
    else:
        reasoning.append(f"{account_id} has no identity or money-flow links to any other account in the graph.")
    if shared_device_accounts:
        reasoning.append(f"{len(shared_device_accounts)} other account(s) share a device with {account_id}.")
    if shared_ip_accounts:
        reasoning.append(f"{len(shared_ip_accounts)} other account(s) share an IP address with {account_id}.")
    if ring_leader:
        reasoning.append(f"{ring_leader} has the highest money-flow PageRank in this component "
                          f"(likely ring leader).")
    if best_money_path:
        reasoning.append(f"{account_id} participates in a {best_money_path['hops']}-hop money path: "
                          f"{' -> '.join(best_money_path['accounts'])}.")
    if own_alerts:
        reasoning.append(f"{account_id} already has {len(own_alerts)} open alert(s): "
                          f"{own_alerts[0].get('reason', '')}.")
    reasoning.append(f"Graph-derived ML risk score = {risk_score:.2f} ({risk_class}).")
    if risk_data.get("graph_guardrail_applied"):
        reasoning.append("A graph-evidence guardrail capped the raw model score because corroborating "
                          "graph evidence did not support a higher verdict.")

    # ------------------------------------------------------------------
    # Verdict + action (THIS is what the graph structure directly decides)
    # ------------------------------------------------------------------
    # Confidence now blends BOTH raw component size and the richer ring_score
    # composite (size alone can't distinguish a dense, corroborated ring from
    # a large but loosely-connected one).
    ring_strength = max(min(component_size / 9, 1.0), ring_score)
    if risk_class == "CRITICAL":
        verdict = "FRAUD RING CONFIRMED"
        action = "ESCALATE_FOR_MANUAL_INVESTIGATION"
        confidence = min(0.99, 0.75 + 0.2 * ring_strength)
    elif risk_class == "HIGH":
        verdict = "SUSPICIOUS — LIKELY RING MEMBER"
        action = "FLAG_AND_REQUEST_MANUAL_REVIEW"
        confidence = 0.65 + 0.1 * ring_strength
    elif risk_class == "MEDIUM":
        verdict = "WEAK SIGNAL — MONITOR"
        action = "ADD_TO_WATCHLIST"
        confidence = 0.5
    else:
        verdict = "NO SIGNIFICANT RISK DETECTED"
        action = "NO_ACTION_REQUIRED"
        confidence = 0.6

    return {
        "account_id": account_id,
        "verdict": verdict,
        "risk_score": risk_score,
        "risk_class": risk_class,
        "confidence": round(confidence, 2),
        "recommended_action": action,
        "reasoning": reasoning,
        "ring_members": ring_members,
        "ring_leader": ring_leader,
        "ring_score": ring_score,
        "ring_confidence": ring_confidence,
        "ring_reasons": ring_reasons,
        "money_path": best_money_path,
        "shared_device_account_count": len(shared_device_accounts),
        "shared_ip_account_count": len(shared_ip_accounts),
        "tools_used": sorted({e.get("tool") for e in trail if e.get("ok")}),
        "raw_model_score": risk_data.get("raw_model_score"),
        "graph_evidence_points": risk_data.get("graph_evidence_points"),
        "graph_guardrail_applied": risk_data.get("graph_guardrail_applied", False),
        "risk_method": risk_data.get("method"),
        "top_contributing_features": risk_data.get("top_contributing_features", []),
    }


ACTION_DESCRIPTIONS = {
    "ESCALATE_FOR_MANUAL_INVESTIGATION": "Escalate case to a senior fraud investigator for manual review and potential account suspension.",
    "FLAG_AND_REQUEST_MANUAL_REVIEW": "Flag the account and request a manual review before any further high-value transfers.",
    "ADD_TO_WATCHLIST": "Add the account to the investigation watchlist for continued monitoring.",
    "NO_ACTION_REQUIRED": "No action required — graph evidence does not currently support elevated risk.",
}


def execute_recommended_action(ctx, account_id: str, verdict: dict) -> list[dict]:
    """Executes (simulates) the recommended action by calling the matching
    ACTION tools, writing real nodes/properties into FalkorDB. Returns the
    list of resulting tool-result dicts (also appended to ctx.evidence_trail).
    Always creates a Case first so every action is tied to an auditable
    investigation record."""
    from tools.base import REGISTRY  # local import avoids a module cycle at import time

    action = verdict.get("recommended_action", "NO_ACTION_REQUIRED")
    results = []

    def call(name, **kwargs):
        spec = REGISTRY.get(name)
        res = spec.run(ctx, **kwargs)
        entry = res.to_dict()
        ctx.evidence_trail.append(entry)
        results.append(entry)
        return res

    reason = "; ".join(verdict.get("reasoning", [])) or verdict.get("verdict", "")

    case_result = call("create_investigation_case", account_id=account_id,
                        notes=f"Auto-generated from verdict: {verdict.get('verdict')}")
    # Without a persisted case node there is no safe target for provenance or
    # follow-on action writes. Preserve the structured failure and stop here.
    case_id = (case_result.data or {}).get("case_id") if case_result.ok else None
    if not case_id:
        return results

    # ------------------------------------------------------------------
    # Second-order evidence graph (additive): one GraphFinding + Evidence
    # node per reasoning line, linked to the Case via SUPPORTED_BY, plus the
    # reciprocal Account-[:HAS_CASE]->Case edge. This is what lets
    # docs/DEMO_SCRIPT.md's sample Cypher query "what graph evidence
    # supported this case?" and get a real answer straight from the graph.
    gs = ctx.graph_store
    findings = [{"id": f"{case_id}-F{i}", "tool": "generate_verdict", "summary": line}
                for i, line in enumerate(verdict.get("reasoning", []))]
    finding_ids = [f["id"] for f in findings]
    if findings:
        try:
            gs.attach_case_evidence(case_id, account_id, findings)
        except Exception as exc:  # noqa: BLE001 — evidence-graph write is additive, never block the action
            logging.getLogger("ringtrace.agent.decision").warning("attach_case_evidence failed: %s", exc)

    def record_action_node(action_type: str):
        """Writes the generic (Case)-[:RESULTED_IN]->(Action)-[:TRIGGERED_BY]->(GraphFinding)
        bookkeeping for whichever specific action tool(s) just ran."""
        action_id = f"{case_id}-A-{action_type}"
        try:
            gs.record_action_outcome(case_id, action_id, action_type, reason)
            if finding_ids:
                gs.link_action_to_findings(action_id, finding_ids)
        except Exception as exc:  # noqa: BLE001
            logging.getLogger("ringtrace.agent.decision").warning("record_action_outcome failed: %s", exc)

    if action == "ESCALATE_FOR_MANUAL_INVESTIGATION":
        call("flag_account", account_id=account_id, reason=reason)
        call("mark_high_risk", account_id=account_id, risk_score=verdict.get("risk_score", 0.9))
        call("request_manual_review", account_id=account_id, reason=reason)
        call("escalate_case", case_id=case_id, reason=reason)
        record_action_node(action)
    elif action == "FLAG_AND_REQUEST_MANUAL_REVIEW":
        call("flag_account", account_id=account_id, reason=reason)
        call("request_manual_review", account_id=account_id, reason=reason)
        record_action_node(action)
    elif action == "ADD_TO_WATCHLIST":
        call("add_to_watchlist", entity_id=account_id, entity_type="Account", reason=reason)
        record_action_node(action)
    # NO_ACTION_REQUIRED -> the case + evidence graph record is the only artifact

    return results
