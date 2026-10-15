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
from datetime import datetime, timezone
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

    ring_attempt = next((entry for entry in reversed(trail)
                         if entry.get("tool") == "find_fraud_ring"), None)
    # Use the latest attempt, not the latest successful result: a later failed
    # query invalidates an earlier component snapshot for this verdict.
    ring_entry = ring_attempt if ring_attempt and ring_attempt.get("ok") else None
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
    ring_evidence_status = (
        "observed" if ring_entry else "query_failed" if ring_attempt else "not_collected"
    )
    if ring_entry:
        component_size = ring_data.get("size", 1)
        ring_members = ring_data.get("members", [account_id])
        ring_score = ring_data.get("ring_score", 0.0)
        ring_confidence = ring_data.get("ring_confidence", 0.0)
        ring_reasons = ring_data.get("ring_reasons", [])
    else:
        # Missing/failed component evidence is unknown, not proof of an
        # isolated account or a measured zero ring score.
        component_size = None
        ring_members = []
        ring_score = None
        ring_confidence = None
        ring_reasons = []

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
    if ring_evidence_status == "query_failed":
        reasoning.append(f"Ring-analysis evidence for {account_id} is unavailable because "
                          "the latest find_fraud_ring call did not succeed.")
    elif ring_evidence_status == "not_collected":
        reasoning.append(f"Ring-analysis evidence for {account_id} was not collected; "
                          "ring membership is unknown.")
    elif component_size > 1:
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
    ring_strength = (
        max(min(component_size / 9, 1.0), ring_score)
        if ring_evidence_status == "observed" else 0.0
    )
    if risk_class == "CRITICAL":
        verdict = (
            "FRAUD RING CONFIRMED" if ring_evidence_status == "observed"
            else "CRITICAL RISK — RING EVIDENCE UNVERIFIED"
        )
        action = "ESCALATE_FOR_MANUAL_INVESTIGATION"
        confidence = min(0.99, 0.75 + 0.2 * ring_strength)
    elif risk_class == "HIGH":
        verdict = (
            "SUSPICIOUS — LIKELY RING MEMBER" if ring_evidence_status == "observed"
            else "HIGH RISK — RING EVIDENCE UNVERIFIED"
        )
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
        "ring_evidence_status": ring_evidence_status,
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
    """Run the simulated graph action and verify every required write.

    FalkorDB mutations span multiple queries rather than one transaction. A
    failed step therefore stops subsequent writes and leaves the case/action
    audit at ``failed``/``unknown`` where possible; callers must not report a
    successful graph write unless the final audit query confirms it.
    """
    from tools.base import REGISTRY, ToolResult  # local import avoids a module cycle

    logger = logging.getLogger("ringtrace.agent.decision")
    action = verdict.get("recommended_action", "NO_ACTION_REQUIRED")
    audit = dict(getattr(ctx, "action_audit", {}) or {})
    results: list[dict] = []
    gs = ctx.graph_store
    case_id: str | None = None
    action_id: str | None = None

    def append_result(result: ToolResult) -> ToolResult:
        entry = result.to_dict()
        ctx.evidence_trail.append(entry)
        results.append(entry)
        return result

    def call(name: str, **kwargs) -> ToolResult:
        spec = REGISTRY.get(name)
        if spec is None:
            return append_result(ToolResult(
                ok=False, tool=name, summary=f"Required action tool '{name}' is unavailable.",
                error="action_tool_unavailable",
            ))
        return append_result(spec.run(ctx, **kwargs))

    def write_audit(action_outcome: str, error: str | None = None) -> ToolResult:
        """Verify the final Case/Action audit write without guessing success."""
        if not case_id:
            return append_result(ToolResult(
                ok=False, tool="finalize_case_action_audit",
                summary="Cannot finalize an action without a persisted graph case.",
                error="case_write_failed",
            ))
        finished_at = datetime.now(timezone.utc).isoformat()
        graph_write_status = "written" if action_outcome == "succeeded" else "unknown"
        try:
            query_result = gs.finalize_case_action_audit(
                case_id,
                action_id=action_id,
                action_outcome=action_outcome,
                graph_write_status=graph_write_status,
                execution_finished_at=finished_at,
                executed_at=finished_at if action_outcome == "succeeded" else None,
                error=(str(error)[:500] if error else None),
            )
            expected_action_id = action_id
            if not query_result.data and action_id and action_outcome == "failed":
                # If an Action node was only partially created, still mark the
                # Case outcome failed/unknown when possible. Never use this
                # recovery path to confirm a successful write.
                expected_action_id = None
                query_result = gs.finalize_case_action_audit(
                    case_id,
                    action_id=None,
                    action_outcome=action_outcome,
                    graph_write_status=graph_write_status,
                    execution_finished_at=finished_at,
                    executed_at=None,
                    error=(str(error)[:500] if error else None),
                )
            row = query_result.data[0] if query_result.data else None
            if not isinstance(row, (list, tuple)) or len(row) < 5:
                raise RuntimeError("FalkorDB returned no completed action-audit record.")
            data = {
                "case_id": row[0],
                "api_case_id": row[1],
                "action_id": row[2],
                "action_outcome": row[3],
                "graph_write_status": row[4],
            }
            verified = (
                data["case_id"] == case_id
                and data["api_case_id"] == audit.get("api_case_id")
                and data["action_id"] == expected_action_id
                and data["action_outcome"] == action_outcome
                and data["graph_write_status"] == graph_write_status
            )
            if action_outcome == "succeeded" and not verified:
                raise RuntimeError("FalkorDB did not confirm the expected case/action audit values.")
            if action_outcome == "failed" and not verified:
                raise RuntimeError("FalkorDB did not confirm the failed action audit values.")
            return append_result(ToolResult(
                ok=(action_outcome == "succeeded" and verified),
                tool="finalize_case_action_audit",
                summary=("Verified completed graph action and audit write."
                         if action_outcome == "succeeded" and verified
                         else "Recorded a failed graph action; write-back is unverified."),
                data=data,
                evidence=[query_result.as_evidence()],
                error=None if action_outcome == "succeeded" and verified else (str(error)[:500] if error else "action_audit_failed"),
            ))
        except Exception as exc:  # noqa: BLE001 — never turn an unverified write into success
            logger.warning("finalize_case_action_audit failed for %s: %s", case_id, exc)
            return append_result(ToolResult(
                ok=False,
                tool="finalize_case_action_audit",
                summary="Could not verify the final graph action-audit write.",
                error="action_audit_finalize_failed",
            ))

    def fail(error: str) -> list[dict]:
        write_audit("failed", error)
        return results

    if audit and audit.get("action_type") != action:
        append_result(ToolResult(
            ok=False, tool="action_approval_binding",
            summary="The approved action does not match the current server-side recommendation.",
            error="approved_action_mismatch",
        ))
        return results

    # The approval binds the investigation's server-stored recommendation;
    # avoid recomputing a potentially different verdict during graph writes.
    ctx.action_verdict = verdict
    reason = "; ".join(verdict.get("reasoning", [])) or verdict.get("verdict", "")
    case_result = call(
        "create_investigation_case",
        account_id=account_id,
        notes=f"Auto-generated from verdict: {verdict.get('verdict')}",
    )
    case_id = (case_result.data or {}).get("case_id") if case_result.ok else None
    if not case_id:
        return results

    # Evidence is part of the action write, not optional bookkeeping: if a
    # query fails or returns fewer records than requested, stop and mark the
    # audit outcome unknown rather than claiming a completed action.
    findings = [
        {"id": f"{case_id}-F{i}", "tool": "generate_verdict", "summary": line}
        for i, line in enumerate(verdict.get("reasoning", []))
    ]
    finding_ids = [finding["id"] for finding in findings]
    if findings:
        try:
            evidence_write = gs.attach_case_evidence(case_id, account_id, findings)
            evidence_count = evidence_write.data[0][0] if evidence_write.data and evidence_write.data[0] else 0
            if int(evidence_count or 0) < len(findings):
                return fail("case_evidence_write_incomplete")
            append_result(ToolResult(
                ok=True, tool="attach_case_evidence",
                summary=f"Attached {int(evidence_count)} graph evidence records to the case.",
                data={"evidence_count": int(evidence_count)},
                evidence=[evidence_write.as_evidence()],
            ))
        except Exception as exc:  # noqa: BLE001 — evidence is required for the success audit
            logger.warning("attach_case_evidence failed for %s: %s", case_id, exc)
            append_result(ToolResult(
                ok=False, tool="attach_case_evidence",
                summary="Could not attach the investigation evidence to the graph case.",
                error="case_evidence_write_failed",
            ))
            return fail("case_evidence_write_failed")

    if action not in {
        "ESCALATE_FOR_MANUAL_INVESTIGATION",
        "FLAG_AND_REQUEST_MANUAL_REVIEW",
        "ADD_TO_WATCHLIST",
        "NO_ACTION_REQUIRED",
    }:
        append_result(ToolResult(
            ok=False, tool="action_dispatch",
            summary=f"Unsupported simulated action '{action}'.",
            error="unsupported_action",
        ))
        return fail("unsupported_action")

    if action != "NO_ACTION_REQUIRED":
        pending_action_id = f"{case_id}-A-{action}"
        action_id = pending_action_id
        try:
            action_write = gs.record_action_outcome(
                case_id, pending_action_id, action, reason, audit=audit
            )
            if not action_write.data:
                raise RuntimeError("Action audit node was not returned by FalkorDB.")
            action_id = pending_action_id
            append_result(ToolResult(
                ok=True, tool="record_action_outcome",
                summary=f"Recorded pending action audit for {action}.",
                data={"action_id": action_id}, evidence=[action_write.as_evidence()],
            ))
            if finding_ids:
                finding_write = gs.link_action_to_findings(action_id, finding_ids)
                finding_count = finding_write.data[0][0] if finding_write.data and finding_write.data[0] else 0
                if int(finding_count or 0) < len(finding_ids):
                    raise RuntimeError("Action-to-finding links were incomplete.")
                append_result(ToolResult(
                    ok=True, tool="link_action_to_findings",
                    summary=f"Linked the action to {int(finding_count)} graph findings.",
                    data={"finding_count": int(finding_count)}, evidence=[finding_write.as_evidence()],
                ))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Action-audit graph write failed for %s: %s", case_id, exc)
            append_result(ToolResult(
                ok=False, tool="record_action_outcome",
                summary="Could not complete the pending action-audit graph writes.",
                error="action_audit_write_failed",
            ))
            return fail("action_audit_write_failed")

    if action == "ESCALATE_FOR_MANUAL_INVESTIGATION":
        steps = [
            ("flag_account", {"account_id": account_id, "reason": reason}),
            ("mark_high_risk", {"account_id": account_id, "risk_score": verdict.get("risk_score", 0.9)}),
            ("request_manual_review", {"account_id": account_id, "reason": reason}),
            ("escalate_case", {"case_id": case_id, "reason": reason}),
        ]
    elif action == "FLAG_AND_REQUEST_MANUAL_REVIEW":
        steps = [
            ("flag_account", {"account_id": account_id, "reason": reason}),
            ("request_manual_review", {"account_id": account_id, "reason": reason}),
        ]
    elif action == "ADD_TO_WATCHLIST":
        steps = [(
            "add_to_watchlist",
            {"entity_id": account_id, "entity_type": "Account", "reason": reason},
        )]
    else:
        steps = []

    for tool_name, kwargs in steps:
        result = call(tool_name, **kwargs)
        if not result.ok:
            return fail(result.error or result.summary or f"{tool_name}_failed")

    write_audit("succeeded")
    return results
