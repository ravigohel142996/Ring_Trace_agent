"""
tests/test_decision.py
------------------------
This is the test that encodes RingTrace's core acceptance criterion:
identical decision logic, but DIFFERENT graph evidence, must produce a
visibly different verdict for each of the three demo cases:

  Case A (A1100) — isolated / minimal connectivity       -> LOW / no action
  Case B (A1200) — shared-IP identity cluster, no money   -> HIGH / flag+review
                   trail to a known-bad entity
  Case C (A1027) — dense ring + confirmed money flow      -> CRITICAL / escalate
                   + a pre-existing alert
"""
from __future__ import annotations

from agent.decision import build_verdict
from agent.rule_based import run_investigation
from tests.conftest import requires_graph


@requires_graph
def test_case_a_isolated_account_is_low_risk(ctx):
    run_investigation(ctx, "A1100")
    verdict = build_verdict(ctx, "A1100")
    assert verdict["risk_class"] == "LOW"
    assert verdict["recommended_action"] == "NO_ACTION_REQUIRED"


@requires_graph
def test_case_b_identity_cluster_without_money_trail_is_high_not_critical(ctx):
    run_investigation(ctx, "A1200")
    verdict = build_verdict(ctx, "A1200")
    assert verdict["risk_class"] == "HIGH"
    assert verdict["recommended_action"] == "FLAG_AND_REQUEST_MANUAL_REVIEW"
    assert verdict["shared_ip_account_count"] > 0


@requires_graph
def test_case_c_ring_with_money_flow_is_critical(ctx):
    run_investigation(ctx, "A1027")
    verdict = build_verdict(ctx, "A1027")
    assert verdict["risk_class"] == "CRITICAL"
    assert verdict["recommended_action"] == "ESCALATE_FOR_MANUAL_INVESTIGATION"
    assert verdict["ring_leader"] == "A1001"
    assert verdict["money_path"] is not None


@requires_graph
def test_verdicts_differ_across_cases(ctx, graph_store, risk_scorer):
    from tools.context import ToolContext

    results = {}
    for account_id in ("A1100", "A1200", "A1027"):
        c = ToolContext(graph_store=graph_store, risk_scorer=risk_scorer)
        run_investigation(c, account_id)
        results[account_id] = build_verdict(c, account_id)["risk_class"]

    assert results["A1100"] == "LOW"
    assert results["A1200"] == "HIGH"
    assert results["A1027"] == "CRITICAL"
    assert len(set(results.values())) == 3  # all three genuinely different
