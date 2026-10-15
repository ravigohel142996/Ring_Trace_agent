"""Focused regressions for graph-query direction and missing evidence handling."""
from __future__ import annotations

from types import SimpleNamespace

from agent.decision import build_verdict
from graph.queries import GraphStore


class RecordingGraph:
    def __init__(self, result_set):
        self.result_set = result_set
        self.cypher = None
        self.params = None

    def query(self, cypher, params):
        self.cypher = cypher
        self.params = params
        return SimpleNamespace(result_set=self.result_set)


def test_person_entity_pivot_follows_outgoing_owns_relationship():
    graph = RecordingGraph([[{"id": "P-CASEB-0"}, ["A1200"], 1]])

    result = GraphStore(graph).investigate_entity("person", "P-CASEB-0")

    assert "(n:Person {id: $id})-[:OWNS]->(a:Account)" in graph.cypher
    assert "(n:Person {id: $id})<-[:OWNS]-(a:Account)" not in graph.cypher
    assert graph.params == {"id": "P-CASEB-0"}
    assert result.data == [[{"id": "P-CASEB-0"}, ["A1200"], 1]]


def _risk_entry(account_id="A1027", risk_class="LOW", score=0.18):
    return {
        "ok": True,
        "tool": "calculate_risk_score",
        "data": {"account_id": account_id, "risk_score": score, "risk_class": risk_class},
    }


def _context(*entries):
    return SimpleNamespace(evidence_trail=list(entries))


def test_failed_latest_ring_query_is_unknown_not_absent_evidence():
    previous_success = {
        "ok": True,
        "tool": "find_fraud_ring",
        "data": {"size": 9, "members": ["A1027", "A1001"], "ring_score": 0.8, "ring_confidence": 0.9},
    }
    latest_failure = {
        "ok": False,
        "tool": "find_fraud_ring",
        "summary": "find_fraud_ring failed",
        "error": "synthetic query failure",
    }

    verdict = build_verdict(
        _context(previous_success, latest_failure, _risk_entry("A1027", "CRITICAL", 0.95)),
        "A1027",
    )

    assert verdict["ring_evidence_status"] == "query_failed"
    assert verdict["ring_members"] == []
    assert verdict["ring_score"] is None
    assert verdict["ring_confidence"] is None
    assert verdict["verdict"] == "CRITICAL RISK — RING EVIDENCE UNVERIFIED"
    assert not any("has no identity or money-flow links" in item for item in verdict["reasoning"])
    assert any("evidence for A1027 is unavailable" in item for item in verdict["reasoning"])


def test_unqueried_ring_is_unknown_but_successful_singleton_is_observed_zero():
    unqueried = build_verdict(_context(_risk_entry("A1100")), "A1100")
    assert unqueried["ring_evidence_status"] == "not_collected"
    assert unqueried["ring_members"] == []
    assert unqueried["ring_score"] is None
    assert not any("has no identity or money-flow links" in item for item in unqueried["reasoning"])

    observed_singleton = {
        "ok": True,
        "tool": "find_fraud_ring",
        "data": {
            "size": 1,
            "members": ["A1100"],
            "is_ring": False,
            "ring_score": 0.0,
            "ring_confidence": 0.0,
            "ring_reasons": [],
        },
    }
    observed = build_verdict(_context(observed_singleton, _risk_entry("A1100")), "A1100")

    assert observed["ring_evidence_status"] == "observed"
    assert observed["ring_members"] == ["A1100"]
    assert observed["ring_score"] == 0.0
    assert any("has no identity or money-flow links" in item for item in observed["reasoning"])
