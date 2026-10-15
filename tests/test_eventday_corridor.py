"""Unit regressions for the event-day temporal corridor agent.

These tests verify decision semantics and generated Cypher without pretending
to be FalkorDB integration tests. Real graph verification remains separately
opted in through the disposable-graph test gate.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from eventday.engine import CorridorInvestigator
from eventday.graph import CorridorGraph, GraphQueryError, QueryObservation


class QueryGraph:
    def __init__(self):
        self.calls = []

    def query(self, cypher, params):
        self.calls.append((cypher, params))
        return SimpleNamespace(result_set=[["ok"]])


def test_corridor_query_uses_bound_data_and_validated_hop_literal():
    graph = QueryGraph()
    service = CorridorGraph(graph, dataset_id="test-synthetic")

    result = service.trace_corridor("W-START", after_ts=100, until_ts=3700, max_hops=6)

    cypher, params = graph.calls[0]
    assert "FUNDED_TO*1..6" in cypher
    assert "CASHED_OUT_TO {dataset_id: $dataset_id, synthetic: true}" in cypher
    assert "$wallet_id" in cypher and "$dataset_id" in cypher
    assert params == {
        "wallet_id": "W-START",
        "dataset_id": "test-synthetic",
        "after_ts": 100,
        "until_ts": 3700,
    }
    assert result.rows == [["ok"]]
    with pytest.raises(ValueError):
        service.trace_corridor("W-START", after_ts=100, until_ts=3700, max_hops=99)


def _observation(name, rows):
    return QueryObservation(name, "MATCH ... RETURN ...", {"dataset_id": "test"}, rows)


class FakeInvestigationGraph:
    dataset_id = "test-synthetic"

    def __init__(self, *, paths=None, devices=None, owners=None, fail_on=None):
        self.paths = paths or []
        self.devices = devices or []
        self.owners = owners or []
        self.fail_on = set(fail_on or [])
        self.calls = []

    def _maybe_fail(self, name):
        self.calls.append(name)
        if name in self.fail_on:
            raise GraphQueryError(name, "MATCH ...", {}, RuntimeError("test query failure"))

    def prior_investigations(self, payment_event_id):
        self._maybe_fail("recall")
        return _observation("recall_prior_investigations", [])

    def inspect_payment(self, payment_event_id):
        self._maybe_fail("inspect")
        payment = {"id": payment_event_id, "occurred_at": 1000, "amount": 24000, "currency": "USD"}
        return _observation("inspect_payment_event", [[payment, "W-SOURCE", "W-MULE-1"]])

    def trace_corridor(self, wallet_id, *, after_ts, until_ts, max_hops):
        self._maybe_fail("corridor")
        return _observation("trace_time_respecting_corridor", self.paths)

    def shared_devices(self, wallet_ids):
        self._maybe_fail("devices")
        return _observation("find_shared_devices", self.devices)

    def shared_owners(self, wallet_ids):
        self._maybe_fail("owners")
        return _observation("find_shared_owners", self.owners)

    def rank_wallets(self, wallet_ids):
        self._maybe_fail("rank")
        return _observation("rank_corridor_wallets", [["W-MULE-3", 0.74]])

    def components(self, wallet_ids):
        self._maybe_fail("components")
        return _observation("group_coordinated_wallets", [["W-MULE-1", 4], ["W-MULE-2", 4]])


def test_multi_hop_payout_and_identity_evidence_recommend_review():
    graph = FakeInvestigationGraph(
        paths=[[["W-MULE-1", "W-MULE-2", "W-MULE-3"],
                [{"event_id": "PAY-2", "amount": 22000}, {"event_id": "PAY-3", "amount": 20400}],
                "W-MULE-3", "PAYOUT-1", 2]],
        devices=[["W-MULE-1", "W-MULE-2", "DEV-1"]],
        owners=[["W-MULE-1", "W-MULE-2", "OWNER-1"]],
    )

    result = CorridorInvestigator(graph).investigate("PAY-1", window_minutes=60, max_hops=4)

    assert result["status"] == "complete"
    assert result["decision"].startswith("REVIEW RECOMMENDED")
    assert result["recommended_action"] == "CREATE_SIMULATED_REVIEW_PROPOSAL"
    assert result["can_propose_review"] is True
    assert result["review_signal_score"] == 1.0
    assert result["paths"][0]["wallets"] == ["W-MULE-1", "W-MULE-2", "W-MULE-3"]
    assert {signal["kind"] for signal in result["signals"]} >= {
        "time_respecting_flow", "payout_destination", "shared_device", "shared_beneficial_owner"
    }
    assert "rank" in graph.calls and "components" in graph.calls


def test_payout_context_without_identity_corroboration_is_not_actionable():
    graph = FakeInvestigationGraph(paths=[[["W-MULE-1", "W-MULE-3"],
                                          [{"event_id": "PAY-2", "amount": 22000}],
                                          "W-MULE-3", "PAYOUT-1", 1]])
    result = CorridorInvestigator(graph).investigate("PAY-1")

    assert result["status"] == "complete"
    assert result["decision"].startswith("MONITOR")
    assert result["can_propose_review"] is False
    assert result["corroborating_identity_types"] == 0


def test_successful_empty_corridor_is_bounded_observation_not_fraud_verdict():
    graph = FakeInvestigationGraph()
    result = CorridorInvestigator(graph).investigate("PAY-CLEAN")

    assert "rank" not in graph.calls and "components" not in graph.calls
    assert result["status"] == "complete"
    assert result["decision"] == "NO DOWNSTREAM CORRIDOR OBSERVED WITHIN THE 60-MINUTE WINDOW"
    assert result["recommended_action"] == "NO_ACTION_REQUIRED"
    assert result["review_signal_score"] == 0.0
    assert "fraud probability" in result["score_note"]


def test_failed_corridor_or_identity_query_never_becomes_no_corridor_evidence():
    failed_path = CorridorInvestigator(FakeInvestigationGraph(fail_on={"corridor"})).investigate("PAY-1")
    assert failed_path["status"] == "incomplete"
    assert failed_path["review_signal_score"] is None
    assert "DO NOT INFER ABSENCE" in failed_path["decision"]
    assert failed_path["can_propose_review"] is False

    failed_identity = CorridorInvestigator(FakeInvestigationGraph(fail_on={"devices"})).investigate("PAY-1")
    assert failed_identity["status"] == "incomplete"
    assert failed_identity["review_signal_score"] is None
    assert "DO NOT INFER ABSENCE" in failed_identity["decision"]


def test_prior_memory_failure_is_disclosed_and_blocks_false_confident_absence():
    result = CorridorInvestigator(FakeInvestigationGraph(fail_on={"recall"})).investigate("PAY-1")

    assert result["status"] == "incomplete"
    assert "recall_prior_investigations" in result["failed_queries"]
    assert result["review_signal_score"] is None
    assert "DO NOT INFER ABSENCE" in result["decision"]
