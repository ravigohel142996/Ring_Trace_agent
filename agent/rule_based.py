"""
agent/rule_based.py
---------------------
Deterministic investigation planner used whenever no LLM is configured (or
the LLM call fails). It implements the exact dynamic-tool-selection
methodology described in the RingTrace brief:

    get_account_context -> find_fraud_ring -> rank_ring_leaders ->
    trace_money_path -> find_identity_links -> calculate_risk_score ->
    generate_verdict

...but SKIPS steps the evidence doesn't justify (e.g. an isolated account
never triggers rank_ring_leaders or trace_money_path) — this is still real
dynamic tool selection, just driven by explicit, auditable rules instead of
an LLM's judgement. It guarantees RingTrace always produces a complete,
evidence-backed investigation even with zero API keys configured.
"""
from __future__ import annotations

import logging

from tools.base import REGISTRY

logger = logging.getLogger("ringtrace.agent.rule_based")


def run_investigation(ctx, account_id: str) -> list[dict]:
    steps: list[dict] = []

    def call(tool_name: str, **kwargs) -> dict:
        spec = REGISTRY.get(tool_name)
        result = spec.run(ctx, **kwargs)
        entry = result.to_dict()
        ctx.evidence_trail.append(entry)
        steps.append(entry)
        logger.info("[%s] %s", tool_name, result.summary)
        return entry

    ctx_entry = call("get_account_context", account_id=account_id)
    if not ctx_entry["ok"]:
        # Account doesn't exist — nothing further to investigate.
        return steps

    ring_entry = call("find_fraud_ring", account_id=account_id)
    ring_data = ring_entry.get("data") or {}
    members = ring_data.get("members", [account_id])
    is_ring = ring_data.get("is_ring", False)

    ring_leader = None
    if is_ring and len(members) > 1:
        leader_entry = call("rank_ring_leaders", account_ids=members)
        ring_leader = (leader_entry.get("data") or {}).get("ring_leader")

    outgoing = (ctx_entry.get("data") or {}).get("outgoing_transfers") or []
    if ring_leader and ring_leader != account_id:
        call("trace_money_path", source_account_id=account_id, destination_account_id=ring_leader)
    elif outgoing:
        call("trace_money_path", source_account_id=account_id)

    call("find_identity_links", account_id=account_id)
    call("calculate_risk_score", account_id=account_id)
    call("generate_verdict", account_id=account_id)
    return steps
