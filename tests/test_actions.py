"""Failure-path tests for graph-backed simulated action execution."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
import tools.actions as action_tools
from agent.decision import execute_recommended_action
from graph.queries import GraphStore, QueryResult
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


def test_account_action_does_not_claim_success_when_graph_returns_no_row():
    class EmptyGraphStore:
        def flag_account(self, *_args):
            return QueryResult(data=[], cypher="SET flagged", params={}, row_count=0)

    context = ToolContext(graph_store=EmptyGraphStore(), risk_scorer=None)
    result = action_tools._flag_account(context, action_tools.FlagAccountInput(
        account_id="A1027", reason="Synthetic unit-test reason."
    ))

    assert result.ok is False
    assert result.error == "account_write_failed"
    assert result.evidence[0]["cypher"] == "SET flagged"


def test_action_case_uses_the_approved_verdict_snapshot(monkeypatch):
    expected_verdict = {
        "verdict": "Synthetic approved verdict",
        "risk_score": 0.74,
        "confidence": 0.81,
        "recommended_action": "FLAG_AND_REQUEST_MANUAL_REVIEW",
        "reasoning": ["Synthetic stored finding."],
    }

    class CapturingGraphStore:
        params = None

        def create_case(self, **params):
            self.params = params
            return QueryResult(data=[[{"id": params["case_id"]}]], cypher="CREATE CASE", params=params, row_count=1)

    graph_store = CapturingGraphStore()
    context = ToolContext(graph_store=graph_store, risk_scorer=None, action_verdict=expected_verdict)
    monkeypatch.setattr(action_tools, "build_verdict", lambda *_args: pytest.fail("approval-bound verdict must not be recomputed"))

    result = action_tools._create_investigation_case(
        context,
        action_tools.CreateInvestigationCaseInput(account_id="A1027", notes="Synthetic test."),
    )

    assert result.ok is True
    assert graph_store.params["recommended_action"] == expected_verdict["recommended_action"]
    assert graph_store.params["risk_score"] == expected_verdict["risk_score"]
    assert result.data["verdict"] == expected_verdict


def test_graph_case_query_binds_audit_fields_from_server_context():
    class FakeGraph:
        def __init__(self):
            self.last_query = None
            self.last_params = None

        def query(self, cypher, params):
            self.last_query = cypher
            self.last_params = params
            return SimpleNamespace(result_set=[[{"id": "CASE-TEST"}]])

    graph = FakeGraph()
    store = GraphStore(graph)
    audit = {
        "api_case_id": "RT-TEST-123",
        "action_type": "ESCALATE_FOR_MANUAL_INVESTIGATION",
        "approved_by": "test-analyst",
        "approved_at": "2026-10-13T12:00:00+00:00",
        "approval_expires_at": "2026-10-13T12:05:00+00:00",
        "execution_actor": "test-analyst",
        "execution_started_at": "2026-10-13T12:01:00+00:00",
    }
    result = store.create_case(
        case_id="CASE-TEST",
        account_id="A1027",
        verdict="Synthetic verdict",
        risk_score=0.9,
        confidence=0.8,
        recommended_action=audit["action_type"],
        notes="Synthetic test record.",
        audit=audit,
    )

    assert result.row_count == 1
    assert "approved_by: $approved_by" in graph.last_query
    assert "execution_actor: $execution_actor" in graph.last_query
    assert graph.last_params["api_case_id"] == "RT-TEST-123"
    assert graph.last_params["approved_by"] == "test-analyst"
    assert graph.last_params["execution_actor"] == "test-analyst"
