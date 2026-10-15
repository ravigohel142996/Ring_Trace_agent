"""Opt-in real FalkorDB tests for the isolated event-day synthetic fixture.

Run only against the dedicated graph on a non-6379 port. Cloud targets must
use TLS and auth; the fixture will seed only after a read-only empty-graph
preflight succeeds. This module never contacts the legacy RingTrace graph.
"""
from __future__ import annotations

import os

import pytest

from eventday.engine import CorridorInvestigator
from eventday.graph import DEFAULT_DATASET_ID, CorridorGraph, get_event_graph, graph_settings
from eventday.seed import fixture, seed_eventday_graph


pytestmark = pytest.mark.skipif(
    os.getenv("RINGTRACE_TEST_DISPOSABLE") != "1",
    reason="set RINGTRACE_TEST_DISPOSABLE=1 only for the explicitly disposable event-day graph",
)


def _dataset_id() -> str:
    return os.getenv("RINGTRACE_EVENTDAY_DATASET", DEFAULT_DATASET_ID)


def _assert_disposable_target() -> None:
    if (not os.getenv("RINGTRACE_EVENTDAY_FALKORDB_HOST")
            or not os.getenv("RINGTRACE_EVENTDAY_FALKORDB_PORT")):
        pytest.fail("Integration tests require explicit event-day host and port; localhost defaults are refused.")
    host, port, graph_name, username, password, tls = graph_settings()
    loopback = host in {"127.0.0.1", "localhost", "::1"}
    if port == 6379:
        pytest.fail("Integration tests refuse port 6379; use a dedicated non-6379 endpoint.")
    if graph_name != "ringtrace_eventday_test":
        pytest.fail("Integration tests require the exact graph name ringtrace_eventday_test.")
    if not loopback and (not tls or not username or not password):
        pytest.fail("Remote integration targets require TLS plus configured username/password.")
    if os.getenv("RINGTRACE_EVENTDAY_ENABLED") != "1" or os.getenv("RINGTRACE_EVENTDAY_DISPOSABLE") != "1":
        pytest.fail("Set both event-day enable/disposable flags for this explicitly isolated test.")


@pytest.fixture(scope="module", autouse=True)
def seed_only_after_empty_graph_preflight():
    _assert_disposable_target()
    graph = get_event_graph()

    connected = graph.query("RETURN 1 AS connected").result_set
    if not connected or connected[0][0] != 1:
        pytest.fail("Read-only FalkorDB connectivity check did not return its sentinel.")
    node_rows = graph.query("MATCH (n) RETURN count(n) AS nodes").result_set
    edge_rows = graph.query("MATCH ()-[r]->() RETURN count(r) AS edges").result_set
    node_count = int(node_rows[0][0]) if node_rows else 0
    edge_count = int(edge_rows[0][0]) if edge_rows else 0
    if node_count != 0 or edge_count != 0:
        pytest.fail(
            f"Refusing to seed non-empty graph ringtrace_eventday_test: "
            f"nodes={node_count}, edges={edge_count}. Inspect it; no reset was run."
        )

    stats = seed_eventday_graph()
    if stats["dataset_id"] != _dataset_id() or stats["nodes"] != 19 or stats["edges"] != 31:
        pytest.fail(
            "Unexpected post-seed synthetic fixture: "
            f"dataset={stats['dataset_id']}, nodes={stats['nodes']}, edges={stats['edges']}."
        )


def _investigator() -> CorridorInvestigator:
    return CorridorInvestigator(CorridorGraph(get_event_graph(), dataset_id=_dataset_id()))


def test_seeded_payment_event_has_time_ordered_payout_corridor():
    result = _investigator().investigate("PAY-ALERT-1001", window_minutes=60, max_hops=4)

    assert result["payment"]["occurred_at"] == result["window_start_ts"]
    assert result["paths"], "FalkorDB returned no time-respecting synthetic corridor for the planted alert case."
    assert any(path["payout_id"] == "PAYOUT-EXT-01" for path in result["paths"])
    assert result["status"] == "complete"
    assert result["decision"].startswith("REVIEW RECOMMENDED")
    assert result["recommended_action"] == "CREATE_SIMULATED_REVIEW_PROPOSAL"
    assert result["can_propose_review"] is True
    assert result["failed_queries"] == []
    assert any(
        [transfer["event_id"] for transfer in path["transfers"]]
        == ["PAY-ALERT-1002", "PAY-ALERT-1003"]
        for path in result["paths"]
    )
    assert all(
        transfer["occurred_at"] > result["window_start_ts"]
        for path in result["paths"]
        for transfer in path["transfers"]
    )
    assert all(
        left["occurred_at"] < right["occurred_at"]
        for path in result["paths"]
        for left, right in zip(path["transfers"], path["transfers"][1:])
    )


def test_benign_and_ambiguous_lookalikes_do_not_become_fraud_verdicts():
    investigator = _investigator()

    benign = investigator.investigate("PAY-BENIGN-2001", window_minutes=60, max_hops=4)
    assert benign["paths"] == []
    assert benign["status"] in {"complete", "partial"}
    assert benign["decision"].startswith("MONITOR") or benign["decision"].startswith("NO DOWNSTREAM")
    assert benign["recommended_action"] != "CREATE_SIMULATED_REVIEW_PROPOSAL"

    ambiguous = investigator.investigate("PAY-AMBIG-3001", window_minutes=60, max_hops=4)
    assert ambiguous["paths"] == []
    assert any(signal["kind"] == "shared_device" for signal in ambiguous["signals"])
    assert not any(signal["kind"] == "shared_beneficial_owner" for signal in ambiguous["signals"])
    assert ambiguous["decision"].startswith("MONITOR")
    assert ambiguous["can_propose_review"] is False


def test_eventday_api_smoke_reads_health_scenarios_and_real_investigation():
    from fastapi.testclient import TestClient
    from api.main import app

    with TestClient(app, base_url="https://testserver") as client:
        health = client.get("/api/eventday/health")
        assert health.status_code == 200
        assert health.json()["enabled"] is True
        assert health.json()["connected"] is True
        assert health.json()["graph"] == "ringtrace_eventday_test"

        scenarios = client.get("/api/eventday/scenarios")
        assert scenarios.status_code == 200
        assert {item["payment_event_id"] for item in scenarios.json()["scenarios"]} == {
            "PAY-ALERT-1001", "PAY-BENIGN-2001", "PAY-AMBIG-3001",
        }

        investigation = client.post(
            "/api/eventday/investigations",
            json={"payment_event_id": "PAY-ALERT-1001", "window_minutes": 60, "max_hops": 4},
        )
        assert investigation.status_code == 200
        observed = investigation.json()["investigation"]
        assert observed["payment_event_id"] == "PAY-ALERT-1001"
        assert observed["paths"]
        assert observed["failed_queries"] == []


def test_real_query_failure_is_not_reported_as_an_empty_corridor():
    class InvalidTraceGraph(CorridorGraph):
        def trace_corridor(self, *args, **kwargs):
            # Intentionally malformed read-only Cypher to verify that a server
            # query error remains unavailable evidence, not a zero-row result.
            return self._run("trace_time_respecting_corridor", "MATCH (", {})

    investigator = CorridorInvestigator(
        InvalidTraceGraph(get_event_graph(), dataset_id=_dataset_id())
    )
    result = investigator.investigate("PAY-ALERT-1001", window_minutes=60, max_hops=4)

    assert result["status"] == "incomplete"
    assert "trace_time_respecting_corridor" in result["failed_queries"]
    assert result["paths"] == []
    assert "DO NOT INFER ABSENCE" in result["decision"]


def test_decision_changes_when_transfer_time_moves_outside_window_and_is_restored():
    graph = get_event_graph()
    fixture_data = fixture()
    anchor_ts = next(row["occurred_at"] for row in fixture_data["payments"] if row["id"] == "PAY-ALERT-1001")
    original_ts = next(row["occurred_at"] for row in fixture_data["payments"] if row["id"] == "PAY-ALERT-1002")
    moved_ts = anchor_ts + 60 * 60 + 1
    params = {
        "event_id": "PAY-ALERT-1002",
        "dataset_id": _dataset_id(),
        "occurred_at": moved_ts,
    }

    def set_transfer_time(occurred_at: int) -> None:
        query_params = {**params, "occurred_at": occurred_at}
        rows = graph.query("""
            MATCH ()-[flow:FUNDED_TO {
                event_id: $event_id, dataset_id: $dataset_id, synthetic: true
            }]->()
            SET flow.occurred_at = $occurred_at
            RETURN count(flow) AS changed
        """, query_params).result_set
        if not rows or int(rows[0][0]) != 1:
            pytest.fail("Could not update exactly the synthetic test transfer for the timestamp mutation check.")

    before = _investigator().investigate("PAY-ALERT-1001", window_minutes=60, max_hops=4)
    assert before["decision"].startswith("REVIEW RECOMMENDED")
    assert before["can_propose_review"] is True

    try:
        set_transfer_time(moved_ts)
        changed = _investigator().investigate("PAY-ALERT-1001", window_minutes=60, max_hops=4)
        assert changed["paths"] == []
        assert changed["decision"].startswith("MONITOR")
        assert changed["can_propose_review"] is False
    finally:
        set_transfer_time(original_ts)

    restored = _investigator().investigate("PAY-ALERT-1001", window_minutes=60, max_hops=4)
    assert restored["decision"].startswith("REVIEW RECOMMENDED")
    assert restored["paths"]


def test_authenticated_review_write_requires_approval_confirmation_and_blocks_replay(monkeypatch):
    from fastapi.testclient import TestClient

    from api import main as api_main
    from api.auth import SESSION_COOKIE_NAME, get_demo_auth_config
    from eventday import api as eventday_api

    auth_config = get_demo_auth_config()
    if auth_config is None:
        pytest.skip("secure demo analyst auth secrets are not configured in the runtime")

    monkeypatch.setattr(eventday_api, "cases", eventday_api.CorridorCaseStore())
    with TestClient(api_main.app, base_url="https://testserver") as client:
        login = client.post(
            "/api/auth/login",
            json={"username": auth_config.username, "password": auth_config.password},
        )
        assert login.status_code == 200
        assert SESSION_COOKIE_NAME in client.cookies
        csrf_token = login.json()["csrf_token"]

        investigated = client.post(
            "/api/eventday/investigations",
            json={"payment_event_id": "PAY-ALERT-1001", "window_minutes": 60, "max_hops": 4},
        )
        assert investigated.status_code == 200
        case_id = investigated.json()["case_id"]
        assert investigated.json()["investigation"]["can_propose_review"] is True

        approve_path = f"/api/eventday/investigations/{case_id}/approve"
        assert client.post(approve_path).status_code == 403
        approved = client.post(approve_path, headers={"X-CSRF-Token": csrf_token})
        assert approved.status_code == 200
        assert approved.json()["simulated"] is True

        execute_path = f"/api/eventday/investigations/{case_id}/execute"
        unconfirmed = client.post(
            execute_path,
            json={"confirmed": False},
            headers={"X-CSRF-Token": csrf_token},
        )
        assert unconfirmed.status_code == 409
        assert "confirmation" in unconfirmed.json()["detail"].lower()

        executed = client.post(
            execute_path,
            json={"confirmed": True},
            headers={"X-CSRF-Token": csrf_token},
        )
        assert executed.status_code == 200
        execution = executed.json()
        assert execution["status"] == "executed"
        assert execution["simulated"] is True
        assert execution["proposal"]["graph_write_status"] == "written"

        replay = client.post(
            execute_path,
            json={"confirmed": True},
            headers={"X-CSRF-Token": csrf_token},
        )
        assert replay.status_code == 409
        stored_case = client.get(f"/api/eventday/investigations/{case_id}").json()
        assert stored_case["execution_attempted"] is True
        assert stored_case["proposal"]["proposal_id"] == execution["proposal"]["proposal_id"]

        params = {
            "run_id": execution["proposal"]["run_id"],
            "proposal_id": execution["proposal"]["proposal_id"],
            "payment_event_id": "PAY-ALERT-1001",
            "dataset_id": _dataset_id(),
        }
        rows = get_event_graph().query("""
            MATCH (run:CorridorInvestigation {
                id: $run_id, dataset_id: $dataset_id, synthetic: true
            })-[:ANALYZED_PAYMENT {dataset_id: $dataset_id, synthetic: true}]->
            (payment:PaymentEvent {
                id: $payment_event_id, dataset_id: $dataset_id, synthetic: true
            })
            MATCH (proposal:ReviewProposal {
                id: $proposal_id, dataset_id: $dataset_id, synthetic: true
            })-[:ABOUT_PAYMENT {dataset_id: $dataset_id, synthetic: true}]->(payment)
            MATCH (proposal)-[:BASED_ON {dataset_id: $dataset_id, synthetic: true}]->(run)
            MATCH (run)-[:SUPPORTED_BY {dataset_id: $dataset_id, synthetic: true}]->
                  (evidence:GraphEvidence {dataset_id: $dataset_id, synthetic: true})
            RETURN run.id AS run_id, proposal.id AS proposal_id,
                   payment.id AS payment_event_id, count(evidence) AS evidence_count,
                   collect(evidence.query_name) AS query_names,
                   collect(evidence.cypher) AS evidence_queries
        """, params).result_set
        assert rows and rows[0][0] == params["run_id"]
        assert rows[0][1] == params["proposal_id"]
        assert rows[0][2] == params["payment_event_id"]
        assert int(rows[0][3]) == execution["proposal"]["evidence_count"]
        assert {"inspect_payment_event", "trace_time_respecting_corridor"}.issubset(set(rows[0][4]))
        assert all(isinstance(query, str) and query.strip() for query in rows[0][5])

        proposal_rows = get_event_graph().query("""
            MATCH (proposal:ReviewProposal {
                id: $proposal_id, dataset_id: $dataset_id, synthetic: true
            })
            RETURN count(proposal) AS proposals
        """, {"proposal_id": params["proposal_id"], "dataset_id": params["dataset_id"]}).result_set
        assert proposal_rows and int(proposal_rows[0][0]) == 1
