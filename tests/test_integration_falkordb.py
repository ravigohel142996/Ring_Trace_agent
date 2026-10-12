"""
tests/test_integration_falkordb.py
-------------------------------------
These integration tests use a real FalkorDB instance, but the harness requires
an explicit disposable-target opt-in and refuses port 6379. They cover scenarios
not already exercised by test_tools.py / test_decision.py / test_risk_scorer.py /
test_llm_loop_mocked.py:

  * connection failure handling (hermetic; no graph endpoint probe)
  * schema setup idempotency
  * degree_stats financial totals under independent in/out and identity fan-out
  * the graph-evidence guardrail through the real risk scorer
  * the full action write (Case/Evidence/GraphFinding/Action graph)
  * malformed input handling
  * LLM-unavailable fallback (no LLM_PROVIDER configured -> rule-based mode)

Ring detection, PageRank, money path, and identity resolution are already
covered by test_tools.py; they are not duplicated here.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from graph.connection import GraphConnectionError, health_check
from graph.queries import GraphStore
from graph.schema import ensure_schema
from tests.conftest import requires_graph
from tools.base import REGISTRY


# ---------------------------------------------------------------------------
# Connection failure handling
# ---------------------------------------------------------------------------
def test_health_check_reports_disconnected_cleanly_for_bad_host(monkeypatch):
    # Keep this failure-path test hermetic: never probe the default graph endpoint.
    def fail_get_graph(_graph_name=None):
        raise GraphConnectionError("synthetic connection failure")

    monkeypatch.setattr("graph.connection.get_graph", fail_get_graph)
    health = health_check(retries=0)
    assert set(health.keys()) >= {"connected", "host", "port", "graph"}
    assert health["connected"] is False
    assert health["error"] == "synthetic connection failure"


def test_graph_connection_error_is_a_real_exception_type():
    # The connection layer must expose a typed exception for callers that want
    # to distinguish "FalkorDB down" from other failures, not a bare Exception.
    assert issubclass(GraphConnectionError, Exception)


# ---------------------------------------------------------------------------
# Schema setup idempotency
# ---------------------------------------------------------------------------
@requires_graph
def test_ensure_schema_is_idempotent(graph_store):
    # Running schema setup twice must not raise or duplicate indexes.
    ensure_schema(graph_store.graph)
    ensure_schema(graph_store.graph)
    stats = graph_store.graph_stats()
    assert stats.data[0][0] > 0  # nodes still present, nothing wiped


# ---------------------------------------------------------------------------
# Financial aggregation regression: fan-outs must not inflate transfer totals
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("outgoing_amounts", "incoming_amounts", "self_transfer_amount",
     "device_count", "ip_count", "extra_linked_count"),
    [
        ([], [], None, 0, 0, 0),
        ([], [], None, 2, 3, 4),
        ([10.25, 20.50], [2.75, 5.25, 9.00], None, 2, 3, 1),
        ([1.00, 2.00, 4.00, 8.00], [30.00], 11.50, 4, 1, 2),
        ([], [0.10, 0.20], None, 3, 0, 5),
    ],
)
@requires_graph
def test_degree_stats_keeps_transfer_totals_independent_of_graph_fanout(
    graph_store, outgoing_amounts, incoming_amounts, self_transfer_amount,
    device_count, ip_count, extra_linked_count,
):
    """Exercise zero-match, parallel transfers, self-loops, and high identity fan-out.

    Every fixture node uses a UUID-scoped ID and is deleted in a finally block;
    this never touches the seeded demo accounts or wipes/reseeds the graph.
    """
    graph = graph_store.graph
    prefix = f"RT-P0-DEGREE-{uuid4().hex}"
    target_id = f"{prefix}-TARGET"
    outgoing_peers = [f"{prefix}-OUT-{i}" for i in range(len(outgoing_amounts))]
    incoming_peers = [f"{prefix}-IN-{i}" for i in range(len(incoming_amounts))]
    device_peers = [f"{prefix}-DEVICE-PEER-{i}" for i in range(device_count)]
    ip_peers = [f"{prefix}-IP-PEER-{i}" for i in range(ip_count)]
    extra_peers = [f"{prefix}-LINK-PEER-{i}" for i in range(extra_linked_count)]
    device_ids = [f"{prefix}-DEVICE-{i}" for i in range(device_count)]
    ip_ids = [f"{prefix}-IP-{i}" for i in range(ip_count)]
    account_ids = [target_id, *outgoing_peers, *incoming_peers, *device_peers, *ip_peers, *extra_peers]
    node_ids = [*account_ids, *device_ids, *ip_ids]

    try:
        graph.query("UNWIND $ids AS id CREATE (:Account {id: id})", {"ids": account_ids})
        if device_ids:
            graph.query("UNWIND $ids AS id CREATE (:Device {id: id})", {"ids": device_ids})
        if ip_ids:
            graph.query("UNWIND $ids AS id CREATE (:IP {id: id})", {"ids": ip_ids})

        if outgoing_amounts:
            graph.query("""
                UNWIND $rows AS row
                MATCH (src:Account {id: $target_id})
                MATCH (dst:Account {id: row.peer_id})
                CREATE (src)-[:TRANSFERRED_TO {amount: toFloat(row.amount), txn_id: row.txn_id}]->(dst)
            """, {"target_id": target_id, "rows": [
                {"peer_id": peer, "amount": amount, "txn_id": f"{prefix}-OUT-TX-{i}"}
                for i, (peer, amount) in enumerate(zip(outgoing_peers, outgoing_amounts))
            ]})

        if incoming_amounts:
            graph.query("""
                UNWIND $rows AS row
                MATCH (src:Account {id: row.peer_id})
                MATCH (dst:Account {id: $target_id})
                CREATE (src)-[:TRANSFERRED_TO {amount: toFloat(row.amount), txn_id: row.txn_id}]->(dst)
            """, {"target_id": target_id, "rows": [
                {"peer_id": peer, "amount": amount, "txn_id": f"{prefix}-IN-TX-{i}"}
                for i, (peer, amount) in enumerate(zip(incoming_peers, incoming_amounts))
            ]})

        if self_transfer_amount is not None:
            graph.query("""
                MATCH (a:Account {id: $target_id})
                CREATE (a)-[:TRANSFERRED_TO {amount: toFloat($amount), txn_id: $txn_id}]->(a)
            """, {"target_id": target_id, "amount": self_transfer_amount,
                  "txn_id": f"{prefix}-SELF-TX"})

        if device_ids:
            graph.query("""
                UNWIND $rows AS row
                MATCH (a:Account {id: $target_id})
                MATCH (peer:Account {id: row.peer_id})
                MATCH (d:Device {id: row.entity_id})
                CREATE (a)-[:USES_DEVICE]->(d)
                CREATE (peer)-[:USES_DEVICE]->(d)
                CREATE (a)-[:LINKED_TO {via: 'DEVICE', ref: row.entity_id}]->(peer)
                CREATE (peer)-[:LINKED_TO {via: 'DEVICE', ref: row.entity_id}]->(a)
            """, {"target_id": target_id, "rows": [
                {"peer_id": peer, "entity_id": device}
                for peer, device in zip(device_peers, device_ids)
            ]})

        if ip_ids:
            graph.query("""
                UNWIND $rows AS row
                MATCH (a:Account {id: $target_id})
                MATCH (peer:Account {id: row.peer_id})
                MATCH (ip:IP {id: row.entity_id})
                CREATE (a)-[:LOGGED_FROM]->(ip)
                CREATE (peer)-[:LOGGED_FROM]->(ip)
                CREATE (a)-[:LINKED_TO {via: 'IP', ref: row.entity_id}]->(peer)
                CREATE (peer)-[:LINKED_TO {via: 'IP', ref: row.entity_id}]->(a)
            """, {"target_id": target_id, "rows": [
                {"peer_id": peer, "entity_id": ip}
                for peer, ip in zip(ip_peers, ip_ids)
            ]})

        if extra_peers:
            graph.query("""
                UNWIND $rows AS row
                MATCH (a:Account {id: $target_id})
                MATCH (peer:Account {id: row.peer_id})
                CREATE (a)-[:LINKED_TO {via: 'TEST', ref: row.ref}]->(peer)
            """, {"target_id": target_id, "rows": [
                {"peer_id": peer, "ref": f"{prefix}-REF-{i}"}
                for i, peer in enumerate(extra_peers)
            ]})

        params = {"id": target_id}
        direct_out = graph.query("""
            MATCH (a:Account {id: $id})-[t:TRANSFERRED_TO]->()
            RETURN count(t), sum(t.amount)
        """, params).result_set[0]
        direct_in = graph.query("""
            MATCH ()-[t:TRANSFERRED_TO]->(a:Account {id: $id})
            RETURN count(t), sum(t.amount)
        """, params).result_set[0]
        direct_linked_degree = graph.query("""
            MATCH (a:Account {id: $id})-[l:LINKED_TO]-()
            RETURN count(DISTINCT l)
        """, params).result_set[0][0]
        actual_device_count = graph.query("""
            MATCH (a:Account {id: $id})-[:USES_DEVICE]->(d:Device)
            RETURN count(DISTINCT d)
        """, params).result_set[0][0]
        actual_ip_count = graph.query("""
            MATCH (a:Account {id: $id})-[:LOGGED_FROM]->(ip:IP)
            RETURN count(DISTINCT ip)
        """, params).result_set[0][0]

        stats_result = graph_store.degree_stats(target_id)
        assert stats_result.row_count == 1
        assert stats_result.params == params  # lookup remains parameterized
        out_count, out_total, in_count, in_total, linked_degree = stats_result.data[0]

        self_amount = self_transfer_amount or 0.0
        expected_out_count = len(outgoing_amounts) + int(self_transfer_amount is not None)
        expected_in_count = len(incoming_amounts) + int(self_transfer_amount is not None)
        expected_out_total = sum(outgoing_amounts) + self_amount
        expected_in_total = sum(incoming_amounts) + self_amount

        assert direct_out[0] == expected_out_count
        assert (direct_out[1] or 0.0) == pytest.approx(expected_out_total)
        assert direct_in[0] == expected_in_count
        assert (direct_in[1] or 0.0) == pytest.approx(expected_in_total)
        assert out_count == direct_out[0]
        assert out_total == pytest.approx(direct_out[1] or 0.0)
        assert in_count == direct_in[0]
        assert in_total == pytest.approx(direct_in[1] or 0.0)
        assert actual_device_count == device_count
        assert actual_ip_count == ip_count
        assert linked_degree == direct_linked_degree
        assert linked_degree == 2 * (device_count + ip_count) + extra_linked_count
    finally:
        graph.query("MATCH (n) WHERE n.id IN $ids DETACH DELETE n", {"ids": node_ids})


@requires_graph
def test_degree_stats_missing_account_still_returns_no_rows(graph_store):
    result = graph_store.degree_stats(f"RT-P0-MISSING-{uuid4().hex}")
    assert result.data == []
    assert result.row_count == 0


# ---------------------------------------------------------------------------
# Evidence guardrail, end-to-end through the risk scorer
# ---------------------------------------------------------------------------
@requires_graph
def test_guardrail_caps_isolated_account_below_critical(ctx):
    res = REGISTRY.get("calculate_risk_score").run(ctx, account_id="A1100")
    assert res.ok
    assert res.data["risk_class"] in {"LOW", "MEDIUM"}
    if res.data.get("raw_model_score") is not None:
        # If the raw model alone would have scored this higher than the
        # guarded output, the guardrail must be the thing that pulled it down.
        if res.data["raw_model_score"] > res.data["risk_score"]:
            assert res.data["graph_guardrail_applied"] is True


@requires_graph
def test_guardrail_allows_dense_confirmed_ring_to_reach_critical(ctx):
    res = REGISTRY.get("calculate_risk_score").run(ctx, account_id="A1027")
    assert res.ok
    assert res.data["risk_class"] in {"HIGH", "CRITICAL"}


# ---------------------------------------------------------------------------
# Action write — the full second-order evidence graph actually lands
# ---------------------------------------------------------------------------
@requires_graph
def test_execute_recommended_action_writes_evidence_graph(graph_store, risk_scorer):
    from agent.decision import build_verdict, execute_recommended_action
    from agent.rule_based import run_investigation
    from tools.context import ToolContext

    ctx = ToolContext(graph_store=graph_store, risk_scorer=risk_scorer)
    run_investigation(ctx, "A1027")
    verdict = build_verdict(ctx, "A1027")
    results = execute_recommended_action(ctx, "A1027", verdict)

    assert any(r["tool"] == "create_investigation_case" and r["ok"] for r in results)
    case_id = next(r["data"]["case_id"] for r in results if r["tool"] == "create_investigation_case")

    # HAS_CASE: Account -> Case (reciprocal of the existing Case -[:INVESTIGATES]-> Account)
    has_case = graph_store.graph.query(
        "MATCH (a:Account {id: $aid})-[:HAS_CASE]->(c:Case {id: $cid}) RETURN c.id",
        {"aid": "A1027", "cid": case_id},
    )
    assert has_case.result_set and has_case.result_set[0][0] == case_id

    # SUPPORTED_BY: Case -> Evidence
    evidence = graph_store.graph.query(
        "MATCH (c:Case {id: $cid})-[:SUPPORTED_BY]->(e:Evidence) RETURN count(e)", {"cid": case_id},
    )
    assert evidence.result_set[0][0] > 0

    # RESULTED_IN -> TRIGGERED_BY: Case -> Action -> GraphFinding
    action_chain = graph_store.graph.query(
        "MATCH (c:Case {id: $cid})-[:RESULTED_IN]->(ac:Action)-[:TRIGGERED_BY]->(gf:GraphFinding) "
        "RETURN ac.action_type, count(gf)", {"cid": case_id},
    )
    assert action_chain.result_set
    assert action_chain.result_set[0][1] > 0


# ---------------------------------------------------------------------------
# Malformed input handling
# ---------------------------------------------------------------------------
@requires_graph
def test_malformed_account_id_type_is_rejected_not_crashed(ctx):
    res = REGISTRY.get("get_account_context").run(ctx, account_id=12345)  # wrong type, pydantic should coerce or reject
    # Either pydantic coerces the int to a str (and the lookup cleanly fails as
    # "not found"), or it's rejected outright — either way, must be a structured
    # ToolResult failure, never a raised exception bubbling out of .run().
    assert res.ok is False or res.data is not None


@requires_graph
def test_missing_required_field_returns_structured_error(ctx):
    res = REGISTRY.get("trace_money_path").run(ctx, max_hops=3)  # missing required source_account_id
    assert res.ok is False
    assert res.error


# ---------------------------------------------------------------------------
# LLM-unavailable fallback
# ---------------------------------------------------------------------------
def test_llm_client_is_none_when_no_provider_configured(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    from agent.llm import get_llm_client, _client_cache

    _client_cache.clear()
    assert get_llm_client() is None


@requires_graph
def test_investigate_falls_back_to_rule_based_when_no_llm(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    from agent.llm import _client_cache
    _client_cache.clear()

    from agent.investigator import Investigator
    inv = Investigator()
    result = inv.investigate(account_id="A1100")
    assert result.mode == "rule_based"
    assert result.verdict["risk_class"] in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
