"""Failure-path tests for graph-backed simulated action execution."""
from __future__ import annotations

import tools.actions as action_tools
from agent.decision import execute_recommended_action
from graph.queries import QueryResult
from tools.context import ToolContext


def test_failed_case_write_stops_follow_on_action_tools(monkeypatch) -> None:
    class EmptyGraphStore:
        def create_case(self, **_kwargs):
            return QueryResult(data=[], cypher="CREATE CASE", params={}, row_count=0)

    monkeypatch.setattr(
        action_tools,
        "build_verdict",
        lambda _ctx, _account_id: {
            "verdict": "FRAUD RING CONFIRMED",
            "risk_score": 0.95,
            "confidence": 0.9,
            "recommended_action": "ESCALATE_FOR_MANUAL_INVESTIGATION",
            "reasoning": ["Synthetic test finding."],
        },
    )
    context = ToolContext(graph_store=EmptyGraphStore(), risk_scorer=None)
    verdict = {
        "verdict": "FRAUD RING CONFIRMED",
        "risk_score": 0.95,
        "confidence": 0.9,
        "recommended_action": "ESCALATE_FOR_MANUAL_INVESTIGATION",
        "reasoning": ["Synthetic test finding."],
    }

    results = execute_recommended_action(context, "A1027", verdict)

    assert len(results) == 1
    assert results[0]["tool"] == "create_investigation_case"
    assert results[0]["ok"] is False
    assert results[0]["error"] == "case_write_failed"
