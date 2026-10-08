"""
tools/investigation.py
-----------------------
The core investigation tools RingTrace's agent calls against FalkorDB. Each
tool is deliberately scoped to answer ONE investigative question, with a
description written for an LLM tool-router to understand WHEN (not just how)
to call it. All typed inputs are validated with pydantic; all outputs are
plain JSON-serializable dicts plus the exact Cypher used, for evidence
transparency.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from pydantic import BaseModel, Field

from tools.base import REGISTRY, ToolResult, ToolSpec
from tools.context import ToolContext

# ---------------------------------------------------------------------------
# 1) get_account_context
# ---------------------------------------------------------------------------
class GetAccountContextInput(BaseModel):
    account_id: str = Field(..., description="The account identifier to inspect, e.g. 'A1027'.")


def _get_account_context(ctx: ToolContext, inp: GetAccountContextInput) -> ToolResult:
    gs = ctx.graph_store
    res = gs.account_context(inp.account_id)
    if not res.data:
        return ToolResult(ok=False, tool="get_account_context",
                           summary=f"Account {inp.account_id} was not found in the graph.",
                           error="account_not_found")
    row = res.data[0]
    account, owner, devices, ips, brokers, alerts, outgoing, incoming, merchant_purchases = row
    outgoing = [o for o in outgoing if o.get("to") is not None]
    incoming = [i for i in incoming if i.get("from") is not None]
    merchant_purchases = [m for m in merchant_purchases if m.get("merchant_id") is not None]
    data = {
        "account": account, "owner": owner, "devices": devices, "ips": ips,
        "brokers": brokers, "alerts": alerts, "outgoing_transfers": outgoing,
        "incoming_transfers": incoming, "merchant_purchases": merchant_purchases,
    }
    summary = (
        f"Account {inp.account_id} ({account.get('status', '?')}, {account.get('country', '?')}): "
        f"{len(devices)} device(s), {len(ips)} IP(s), {len(brokers)} broker(s), "
        f"{len(alerts)} alert(s), {len(outgoing)} outgoing / {len(incoming)} incoming transfer(s), "
        f"{len(merchant_purchases)} merchant purchase(s)."
    )
    return ToolResult(ok=True, tool="get_account_context", summary=summary, data=data,
                       evidence=[res.as_evidence()])


# ---------------------------------------------------------------------------
# 2) find_fraud_ring
# ---------------------------------------------------------------------------
class FindFraudRingInput(BaseModel):
    account_id: str = Field(..., description="Account to check for ring membership.")
    min_component_size: int = Field(3, ge=1, description="Minimum size to call a component a 'ring'.")


def _find_fraud_ring(ctx: ToolContext, inp: FindFraudRingInput) -> ToolResult:
    gs = ctx.graph_store
    wcc = gs.weakly_connected_components()
    components: dict = defaultdict(list)
    for account_id, component_id in wcc.data:
        components[component_id].append(account_id)

    my_component_id = next((cid for cid, members in components.items() if inp.account_id in members), None)
    if my_component_id is None:
        return ToolResult(ok=True, tool="find_fraud_ring",
                           summary=f"{inp.account_id} has no identity/money links to any other account.",
                           data={"component_id": None, "members": [inp.account_id], "size": 1,
                                 "is_ring": False, "edges": []},
                           evidence=[wcc.as_evidence()])

    members = sorted(components[my_component_id])
    edges_res = gs.component_edges(members)
    summary_res = gs.accounts_summary(members)
    is_ring = len(members) >= inp.min_component_size and len(members) > 1

    # ------------------------------------------------------------------
    # Transparent composite ring score. Replaces the old "size >= 3 means
    # ring" heuristic with a weighted blend of graph-native signals, each
    # individually auditable via its own parameterized Cypher query. A
    # single boolean (`is_ring`) is still returned for backward compatibility
    # with callers that only need a yes/no, but `ring_score`/`ring_confidence`
    # /`ring_reasons` are the real, explainable verdict inputs.
    # ------------------------------------------------------------------
    size = len(members)
    max_pairs = max(size * (size - 1) / 2, 1)
    evidence_extra = [edges_res.as_evidence(), summary_res.as_evidence()]

    pair_res = gs.shared_identity_pair_counts(members)
    shared_device_pairs, shared_ip_pairs = pair_res.data[0] if pair_res.data else (0, 0)
    evidence_extra.append(pair_res.as_evidence())

    recip_res = gs.reciprocal_transfer_pairs(members)
    reciprocal_pairs = recip_res.data[0][0] if recip_res.data else 0
    evidence_extra.append(recip_res.as_evidence())

    txn_res = gs.component_txn_stats(members)
    txn_count, total_amount, earliest_ts, latest_ts = txn_res.data[0] if txn_res.data else (0, 0.0, None, None)
    txn_count = txn_count or 0
    total_amount = total_amount or 0.0
    evidence_extra.append(txn_res.as_evidence())

    broker_res = gs.component_broker_count(members)
    broker_count = broker_res.data[0][0] if broker_res.data else 0
    evidence_extra.append(broker_res.as_evidence())

    alert_res = gs.component_alert_count(members)
    alerted_member_count = alert_res.data[0][0] if alert_res.data else 0
    evidence_extra.append(alert_res.as_evidence())

    hours_span = max(((latest_ts - earliest_ts) / 3600.0), 0.0) if (earliest_ts and latest_ts) else 0.0

    pagerank_concentration = 0.0
    if size > 1:
        pr_res = gs.pagerank("TRANSFERRED_TO")
        member_scores = [s for aid, s in pr_res.data if aid in set(members)]
        total_pr = sum(member_scores)
        if total_pr > 0:
            pagerank_concentration = max(member_scores) / total_pr

    signals = {
        "component_size": min((size - 1) / 10.0, 1.0) if size > 1 else 0.0,
        "shared_device_density": min(shared_device_pairs / max_pairs, 1.0),
        "shared_ip_density": min(shared_ip_pairs / max_pairs, 1.0),
        "reciprocal_density": min(reciprocal_pairs / max_pairs, 1.0),
        "txn_density": min(txn_count / max(size * 3, 1), 1.0),
        "broker_concentration": min(broker_count / 2.0, 1.0) if broker_count else 0.0,
        "alert_ratio": min(alerted_member_count / max(size, 1), 1.0),
        "pagerank_concentration": pagerank_concentration,
        "txn_velocity": 1.0 if (txn_count >= 3 and 0 < hours_span <= 48) else min(txn_count / 20.0, 1.0),
    }
    weights = {
        "component_size": 0.15, "shared_device_density": 0.15, "shared_ip_density": 0.10,
        "reciprocal_density": 0.15, "txn_density": 0.10, "broker_concentration": 0.10,
        "alert_ratio": 0.10, "pagerank_concentration": 0.10, "txn_velocity": 0.05,
    }
    ring_score = round(min(sum(signals[k] * weights[k] for k in weights), 1.0), 3) if size > 1 else 0.0
    nonzero_signals = sum(1 for v in signals.values() if v > 0.05)
    ring_confidence = round(nonzero_signals / len(signals), 2) if size > 1 else 0.0

    ring_reasons: list[str] = [f"{size} account(s) form one weakly-connected component."]
    if shared_device_pairs:
        ring_reasons.append(f"{shared_device_pairs} account pair(s) in this component share a device.")
    if shared_ip_pairs:
        ring_reasons.append(f"{shared_ip_pairs} account pair(s) in this component share an IP address.")
    if reciprocal_pairs:
        ring_reasons.append(f"{reciprocal_pairs} account pair(s) show reciprocal back-and-forth transfers "
                             f"(wash-trading / layering signature).")
    if txn_count:
        ring_reasons.append(f"{txn_count} internal transfer(s) totaling ${total_amount:,.2f} moved strictly "
                             f"between members of this component.")
    if broker_count:
        ring_reasons.append(f"Members collectively route through {broker_count} distinct broker(s)/mixer(s).")
    if alerted_member_count:
        ring_reasons.append(f"{alerted_member_count} member(s) already carry an open fraud alert.")
    if pagerank_concentration >= 0.25:
        ring_reasons.append(f"Money flow is concentrated: the top account holds "
                             f"{pagerank_concentration*100:.0f}% of this component's PageRank mass.")
    if signals["txn_velocity"] >= 0.5 and hours_span:
        ring_reasons.append(f"{txn_count} transfer(s) occurred within a {hours_span:.1f}-hour window "
                             f"(high velocity).")

    summary = (
        f"Account {inp.account_id} belongs to a weakly-connected component of {len(members)} account(s). "
        f"Ring score = {ring_score:.2f} (confidence {ring_confidence:.2f})"
        f"{' — flagged as a probable fraud ring' if is_ring else ' — below the simple size threshold, but see ring_score for a nuanced read'}."
    )
    data = {
        "component_id": my_component_id,
        "members": members,
        "size": len(members),
        "is_ring": is_ring,
        "ring_score": ring_score,
        "ring_confidence": ring_confidence,
        "ring_reasons": ring_reasons,
        "ring_signals": signals,
        "ring_signal_raw": {
            "shared_device_pairs": shared_device_pairs, "shared_ip_pairs": shared_ip_pairs,
            "reciprocal_pairs": reciprocal_pairs, "txn_count": txn_count, "total_amount": total_amount,
            "broker_count": broker_count, "alerted_member_count": alerted_member_count,
            "pagerank_concentration": round(pagerank_concentration, 3), "hours_span": round(hours_span, 1),
        },
        "edges": [{"source": s, "target": t, "via": via, "ref": ref, "weight": w}
                  for s, t, via, ref, w in edges_res.data],
        "member_summary": [{"id": i, "status": s, "account_type": t, "country": c, "alert_count": ac}
                            for i, s, t, c, ac in summary_res.data],
    }
    return ToolResult(ok=True, tool="find_fraud_ring", summary=summary, data=data,
                       evidence=[wcc.as_evidence(), *evidence_extra])


# ---------------------------------------------------------------------------
# 3) rank_ring_leaders
# ---------------------------------------------------------------------------
class RankRingLeadersInput(BaseModel):
    account_ids: list[str] = Field(..., description="The ring/component member account IDs to rank.")
    top_k: int = Field(5, ge=1, le=50)


def _rank_ring_leaders(ctx: ToolContext, inp: RankRingLeadersInput) -> ToolResult:
    gs = ctx.graph_store
    money_rank = gs.pagerank("TRANSFERRED_TO")
    identity_rank = dict(gs.pagerank("LINKED_TO").data)
    money_scores = dict(money_rank.data)

    members = set(inp.account_ids)
    ranked = sorted(
        ((aid, money_scores.get(aid, 0.0), identity_rank.get(aid, 0.0)) for aid in members),
        key=lambda t: t[1], reverse=True,
    )
    top = ranked[: inp.top_k]
    leader = top[0] if top else None
    summary = (
        f"Ranked {len(members)} account(s) by money-flow PageRank. "
        f"Likely ring leader: {leader[0]} (score={leader[1]:.5f})." if leader else "No accounts to rank."
    )
    data = {
        "ranking": [{"account_id": a, "pagerank_money": s, "pagerank_identity": ident} for a, s, ident in top],
        "ring_leader": leader[0] if leader else None,
    }
    return ToolResult(ok=True, tool="rank_ring_leaders", summary=summary, data=data,
                       evidence=[money_rank.as_evidence()])


# ---------------------------------------------------------------------------
# 4) trace_money_path
# ---------------------------------------------------------------------------
class TraceMoneyPathInput(BaseModel):
    source_account_id: str = Field(..., description="Where the money trail should start.")
    destination_account_id: Optional[str] = Field(
        None, description="If known, trace the path to this specific account. If omitted, the tool "
                           "explores the most interesting outbound trails (toward brokers / alerted accounts)."
    )
    max_hops: int = Field(6, ge=1, le=10)


def _trace_money_path(ctx: ToolContext, inp: TraceMoneyPathInput) -> ToolResult:
    gs = ctx.graph_store
    def _no_revisits(accounts: list[str]) -> bool:
        """Drop paths that touch the same account twice (e.g. a self-loop
        cash-out transaction at the end) — these aren't meaningful multi-hop
        trails and only add noise to the evidence."""
        return len(set(accounts)) == len(accounts)

    if inp.destination_account_id:
        res = gs.money_path_to_target(inp.source_account_id, inp.destination_account_id, inp.max_hops)
        if not res.data:
            return ToolResult(ok=True, tool="trace_money_path",
                               summary=f"No money path found from {inp.source_account_id} to "
                                       f"{inp.destination_account_id} within {inp.max_hops} hops.",
                               data={"paths": []}, evidence=[res.as_evidence()])
        paths = [{"accounts": p, "transfers": t, "hops": h} for p, t, h in res.data if _no_revisits(p)]
    else:
        res = gs.money_path_exploration(inp.source_account_id, inp.max_hops)
        if not res.data:
            return ToolResult(ok=True, tool="trace_money_path",
                               summary=f"No outbound money movement found from {inp.source_account_id}.",
                               data={"paths": []}, evidence=[res.as_evidence()])
        paths = [{"accounts": p, "transfers": t, "hops": h, "broker_id": b, "ends_at_alerted_account": al}
                  for p, t, h, b, al in res.data if _no_revisits(p)]
    if not paths:
        return ToolResult(ok=True, tool="trace_money_path",
                           summary="No meaningful (non-repeating) money path found.",
                           data={"paths": []}, evidence=[res.as_evidence()])

    best = paths[0]
    summary = (
        f"Found {len(paths)} money path(s) from {inp.source_account_id}. "
        f"Longest/most relevant: {' -> '.join(best['accounts'])} ({best['hops']} hop(s))."
    )
    return ToolResult(ok=True, tool="trace_money_path", summary=summary, data={"paths": paths},
                       evidence=[res.as_evidence()])


# ---------------------------------------------------------------------------
# 5) find_identity_links
# ---------------------------------------------------------------------------
class FindIdentityLinksInput(BaseModel):
    account_id: str = Field(..., description="Account to resolve shared identity signals for.")


def _find_identity_links(ctx: ToolContext, inp: FindIdentityLinksInput) -> ToolResult:
    gs = ctx.graph_store
    dev = gs.shared_devices(inp.account_id)
    ips = gs.shared_ips(inp.account_id)
    owners = gs.shared_owners(inp.account_id)
    brokers = gs.shared_brokers(inp.account_id)

    devices = [{"device_id": d, "device_type": t, "other_accounts": o} for d, t, o in dev.data]
    ip_links = [{"ip_id": i, "address": a, "other_accounts": o} for i, a, o in ips.data]
    owner_links = [{"person_id": p, "person_name": n, "other_accounts": o} for p, n, o in owners.data]
    broker_links = [{"broker_id": b, "broker_name": n, "other_accounts": o} for b, n, o in brokers.data]

    total_linked = len({a for grp in (devices, ip_links, owner_links, broker_links)
                         for row in grp for a in row["other_accounts"]})
    summary = (
        f"{inp.account_id} shares identity signals with {total_linked} distinct account(s): "
        f"{len(devices)} shared device(s), {len(ip_links)} shared IP(s), "
        f"{len(owner_links)} shared owner(s), {len(broker_links)} shared broker(s)."
    )
    data = {"shared_devices": devices, "shared_ips": ip_links, "shared_owners": owner_links,
            "shared_brokers": broker_links, "total_distinct_linked_accounts": total_linked}
    return ToolResult(ok=True, tool="find_identity_links", summary=summary, data=data,
                       evidence=[r.as_evidence() for r in (dev, ips, owners, brokers)])


# ---------------------------------------------------------------------------
# 6) calculate_risk_score
# ---------------------------------------------------------------------------
class CalculateRiskScoreInput(BaseModel):
    account_id: str = Field(..., description="Account to produce a graph-derived ML risk score for.")


def _calculate_risk_score(ctx: ToolContext, inp: CalculateRiskScoreInput) -> ToolResult:
    gs = ctx.graph_store
    cache = ctx.feature_cache()
    result = ctx.risk_scorer.score_account(gs, inp.account_id, cache=cache)
    summary = (
        f"Risk score for {inp.account_id}: {result['risk_score']:.2f} ({result['risk_class']}) "
        f"via {result['method']}."
    )
    if result.get("graph_guardrail_applied"):
        summary += " A graph-evidence guardrail adjusted the raw model score to match corroborating evidence."
    return ToolResult(ok=True, tool="calculate_risk_score", summary=summary, data=result, evidence=[])


# ---------------------------------------------------------------------------
# 7) generate_verdict
# ---------------------------------------------------------------------------
class GenerateVerdictInput(BaseModel):
    account_id: str = Field(..., description="Account the investigation is concluding for.")


def _generate_verdict(ctx: ToolContext, inp: GenerateVerdictInput) -> ToolResult:
    from agent.decision import build_verdict  # local import avoids circular import at module load time

    verdict = build_verdict(ctx, inp.account_id)
    summary = (
        f"VERDICT for {inp.account_id}: {verdict['verdict']} "
        f"(confidence={verdict['confidence']:.2f}) -> recommended action: {verdict['recommended_action']}."
    )
    return ToolResult(ok=True, tool="generate_verdict", summary=summary, data=verdict, evidence=[])


# ---------------------------------------------------------------------------
# Optional tools
# ---------------------------------------------------------------------------
class TimelineInput(BaseModel):
    account_id: str


def _timeline(ctx: ToolContext, inp: TimelineInput) -> ToolResult:
    res = ctx.graph_store.timeline(inp.account_id)
    rows = [{"txn_id": t, "amount": a, "timestamp": ts, "channel": c, "from_account": f, "to_account": to}
            for t, a, ts, c, f, to in res.data]
    summary = f"{inp.account_id} has {len(rows)} transaction(s) on record."
    return ToolResult(ok=True, tool="timeline_analysis", summary=summary, data={"transactions": rows},
                       evidence=[res.as_evidence()])


class BrokerAnalysisInput(BaseModel):
    broker_id: Optional[str] = Field(None, description="Specific broker to inspect; omit to list all brokers by usage.")


def _broker_analysis(ctx: ToolContext, inp: BrokerAnalysisInput) -> ToolResult:
    res = ctx.graph_store.broker_analysis(inp.broker_id)
    if inp.broker_id:
        rows = [{"broker_id": b, "name": n, "broker_type": t, "risk_level": r, "accounts": a, "account_count": c}
                 for b, n, t, r, a, c in res.data]
    else:
        rows = [{"broker_id": b, "name": n, "broker_type": t, "risk_level": r, "account_count": c}
                 for b, n, t, r, c in res.data]
    summary = f"Found {len(rows)} broker(s)." if rows else "No broker activity found."
    return ToolResult(ok=True, tool="broker_analysis", summary=summary, data={"brokers": rows},
                       evidence=[res.as_evidence()])


class CompareAccountsInput(BaseModel):
    account_id_a: str
    account_id_b: str


def _compare_accounts(ctx: ToolContext, inp: CompareAccountsInput) -> ToolResult:
    res = ctx.graph_store.compare_accounts(inp.account_id_a, inp.account_id_b)
    if not res.data:
        return ToolResult(ok=False, tool="compare_accounts", summary="One or both accounts not found.",
                           error="account_not_found")
    shared_devices, shared_ips, shared_brokers, link_distance = res.data[0]
    summary = (
        f"{inp.account_id_a} vs {inp.account_id_b}: {len(shared_devices)} shared device(s), "
        f"{len(shared_ips)} shared IP(s), {len(shared_brokers)} shared broker(s); "
        f"identity-graph distance = {link_distance if link_distance is not None else 'unreachable'}."
    )
    data = {"shared_devices": shared_devices, "shared_ips": shared_ips,
            "shared_brokers": shared_brokers, "link_distance": link_distance}
    return ToolResult(ok=True, tool="compare_accounts", summary=summary, data=data, evidence=[res.as_evidence()])


class InvestigateEntityInput(BaseModel):
    entity_type: str = Field(..., description="One of: device, ip, person, broker")
    entity_id: str


def _investigate_entity(ctx: ToolContext, inp: InvestigateEntityInput) -> ToolResult:
    res = ctx.graph_store.investigate_entity(inp.entity_type, inp.entity_id)
    if not res.data:
        return ToolResult(ok=True, tool="investigate_entity",
                           summary=f"No accounts connected to {inp.entity_type} {inp.entity_id}.",
                           data={"connected_accounts": []}, evidence=[res.as_evidence()])
    entity, accounts, count = res.data[0]
    summary = f"{inp.entity_type} {inp.entity_id} connects {count} account(s): {', '.join(accounts)}."
    return ToolResult(ok=True, tool="investigate_entity", summary=summary,
                       data={"entity": entity, "connected_accounts": accounts, "account_count": count},
                       evidence=[res.as_evidence()])


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
REGISTRY.register(ToolSpec(
    name="get_account_context",
    description=(
        "Fetch the direct graph context for a single account: its owner, devices, IPs, brokers, "
        "active alerts, and immediate incoming/outgoing transfers. ALWAYS call this FIRST when "
        "starting a new investigation — it tells you whether deeper tools (ring detection, identity "
        "resolution, money tracing) are worth running."
    ),
    input_model=GetAccountContextInput, handler=_get_account_context,
))
REGISTRY.register(ToolSpec(
    name="find_fraud_ring",
    description=(
        "Use when investigating whether an account belongs to a suspicious connected component "
        "(a 'fraud ring'). Runs FalkorDB's Weakly Connected Components algorithm over the derived "
        "identity-resolution graph (shared device/IP/owner/broker + money transfers) to isolate every "
        "account structurally linked to the target, regardless of how many hops away."
    ),
    input_model=FindFraudRingInput, handler=_find_fraud_ring,
))
REGISTRY.register(ToolSpec(
    name="rank_ring_leaders",
    description=(
        "Use AFTER find_fraud_ring has identified a suspicious connected component, to identify the "
        "most influential account(s) in it. Runs PageRank over the directed money-flow graph so the "
        "account that accumulates funds from the rest of the ring — the likely ring leader / mule "
        "herder — rises to the top."
    ),
    input_model=RankRingLeadersInput, handler=_rank_ring_leaders,
))
REGISTRY.register(ToolSpec(
    name="trace_money_path",
    description=(
        "Use when you need the EXACT multi-hop transfer chain money took between two accounts (or "
        "outward from one account) — e.g. after get_account_context shows outgoing transfers, or "
        "after rank_ring_leaders names a likely leader and you want to see how the target's funds "
        "reach them. Returns the ordered account path plus each hop's amount/timestamp."
    ),
    input_model=TraceMoneyPathInput, handler=_trace_money_path,
))
REGISTRY.register(ToolSpec(
    name="find_identity_links",
    description=(
        "Use to explain WHY two or more accounts might be connected beyond money movement: shared "
        "devices, shared IP addresses, shared owning persons, or shared brokers. Call this whenever "
        "get_account_context shows devices/IPs/brokers worth checking for reuse across accounts."
    ),
    input_model=FindIdentityLinksInput, handler=_find_identity_links,
))
REGISTRY.register(ToolSpec(
    name="calculate_risk_score",
    description=(
        "Compute a graph-derived, explainable ML risk score (0-1) and risk class for an account, "
        "using live features such as component size, shared-identity counts, PageRank, and distance "
        "to known alerts. Call this once you have gathered enough graph context (ring membership, "
        "identity links, money paths) to make the score meaningful."
    ),
    input_model=CalculateRiskScoreInput, handler=_calculate_risk_score,
))
REGISTRY.register(ToolSpec(
    name="generate_verdict",
    description=(
        "Call LAST to synthesize everything gathered so far (ring membership, ring leader, money "
        "paths, identity links, risk score) into a final verdict, confidence level, and recommended "
        "investigation action. Only call this once you believe you have sufficient evidence."
    ),
    input_model=GenerateVerdictInput, handler=_generate_verdict,
))
REGISTRY.register(ToolSpec(
    name="timeline_analysis",
    description="Use to review an account's full transaction history in chronological order, e.g. to spot bursts of high-velocity activity.",
    input_model=TimelineInput, handler=_timeline,
))
REGISTRY.register(ToolSpec(
    name="broker_analysis",
    description="Use to inspect a specific payment broker/mixer's account exposure, or list all brokers ranked by how many accounts route through them.",
    input_model=BrokerAnalysisInput, handler=_broker_analysis,
))
REGISTRY.register(ToolSpec(
    name="compare_accounts",
    description="Use to directly compare two accounts for shared devices/IPs/brokers and identity-graph distance — useful when deciding if two flagged accounts are part of the same ring.",
    input_model=CompareAccountsInput, handler=_compare_accounts,
))
REGISTRY.register(ToolSpec(
    name="investigate_entity",
    description="Use to pivot from a non-account entity (a specific device, IP, person, or broker) to every account connected to it — useful when an investigator wants to start from a device/IP instead of an account.",
    input_model=InvestigateEntityInput, handler=_investigate_entity,
))
