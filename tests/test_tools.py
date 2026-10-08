"""
tests/test_tools.py
---------------------
Smoke + contract tests for the 7 required investigation tools: every tool
must always return a ToolResult (never raise), and must return the expected
shape of data for known demo accounts.
"""
from __future__ import annotations

from tests.conftest import requires_graph
from tools.base import REGISTRY


def test_registry_has_all_required_tools():
    required = {
        "get_account_context", "find_fraud_ring", "rank_ring_leaders", "trace_money_path",
        "find_identity_links", "calculate_risk_score", "generate_verdict",
    }
    assert required.issubset(set(REGISTRY.names()))


@requires_graph
def test_get_account_context_known_account(ctx):
    res = REGISTRY.get("get_account_context").run(ctx, account_id="A1027")
    assert res.ok
    assert res.data["account"]["id"] == "A1027"


@requires_graph
def test_get_account_context_unknown_account_fails_gracefully(ctx):
    res = REGISTRY.get("get_account_context").run(ctx, account_id="NOPE-999")
    assert not res.ok
    assert res.error


@requires_graph
def test_find_fraud_ring_detects_the_demo_ring(ctx):
    res = REGISTRY.get("find_fraud_ring").run(ctx, account_id="A1027")
    assert res.ok
    assert res.data["is_ring"] is True
    assert res.data["size"] >= 9
    assert "A1001" in res.data["members"]


@requires_graph
def test_find_fraud_ring_isolated_case_a(ctx):
    res = REGISTRY.get("find_fraud_ring").run(ctx, account_id="A1100")
    assert res.ok
    assert res.data["size"] < 3  # below ring threshold -> not a "ring"


@requires_graph
def test_rank_ring_leaders_identifies_a1001(ctx):
    members = ["A1020", "A1021", "A1022", "A1023", "A1024", "A1025", "A1026", "A1027", "A1001"]
    res = REGISTRY.get("rank_ring_leaders").run(ctx, account_ids=members)
    assert res.ok
    assert res.data["ring_leader"] == "A1001"


@requires_graph
def test_trace_money_path_finds_multi_hop_chain(ctx):
    res = REGISTRY.get("trace_money_path").run(ctx, source_account_id="A1027", destination_account_id="A1001")
    assert res.ok
    assert res.data["paths"]
    path = res.data["paths"][0]
    assert path["accounts"][0] == "A1027"
    assert path["accounts"][-1] == "A1001"
    # every account should appear exactly once (no self-loop / revisit artifacts)
    assert len(set(path["accounts"])) == len(path["accounts"])


@requires_graph
def test_find_identity_links_detects_shared_device(ctx):
    res = REGISTRY.get("find_identity_links").run(ctx, account_id="A1027")
    assert res.ok
    assert res.data["shared_devices"]


@requires_graph
def test_calculate_risk_score_returns_explainable_output(ctx):
    res = REGISTRY.get("calculate_risk_score").run(ctx, account_id="A1027")
    assert res.ok
    assert 0.0 <= res.data["risk_score"] <= 1.0
    assert res.data["risk_class"] in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    assert res.data["top_contributing_features"]


@requires_graph
def test_invalid_input_returns_tool_result_not_exception(ctx):
    res = REGISTRY.get("trace_money_path").run(ctx, source_account_id="A1027", max_hops=-1)
    assert not res.ok
    assert res.error
