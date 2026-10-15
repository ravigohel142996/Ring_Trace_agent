"""HTTP contract tests for the FastAPI layer; investigation outputs are
injected at the agent boundary, while production code always calls the real
RingTrace Investigator and FalkorDB-backed tools.
"""
from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

import api.main as api_main
from agent.investigator import InvestigationResult
from api.auth import AuthSessionRegistry
from api.store import InvestigationStore


VERDICT = {
    "account_id": "A1027",
    "verdict": "FRAUD RING CONFIRMED",
    "risk_score": 0.91,
    "risk_class": "CRITICAL",
    "confidence": 0.98,
    "recommended_action": "ESCALATE_FOR_MANUAL_INVESTIGATION",
    "reasoning": ["A1027 is connected to a suspicious component.", "A multi-hop money path is present."],
    "ring_members": ["A1027", "A1001"],
    "ring_leader": "A1001",
    "money_path": {"accounts": ["A1027", "A1001"], "hops": 1},
    "tools_used": ["find_fraud_ring", "rank_ring_leaders", "trace_money_path"],
    "risk_method": "random_forest (synthetic-data trained)",
}


def sample_result(account_id: str = "A1027") -> InvestigationResult:
    steps = [
        {
            "ok": True, "tool": "get_account_context", "summary": "Loaded account context.",
            "data": {
                "account": {"id": account_id, "status": "ACTIVE", "country": "US"},
                "owner": {"id": "P-1", "name": "Synthetic Owner"},
                "devices": [{"id": "D-1", "type": "mobile"}],
                "ips": [{"id": "IP-1", "address": "192.0.2.10"}],
                "brokers": [], "alerts": [],
                "outgoing_transfers": [{"to": "A1001", "amount": 500.0, "timestamp": 1000}],
                "incoming_transfers": [],
                "merchant_purchases": [{"merchant_id": "M-1", "merchant_name": "Synthetic Shop", "amount": 25.0}],
            },
            "evidence": [{"cypher": "MATCH (a:Account)", "params": {"id": account_id}, "row_count": 1}],
        },
        {
            "ok": True, "tool": "find_fraud_ring", "summary": "WCC component found.",
            "data": {
                "component_id": 4, "members": [account_id, "A1001"], "size": 2,
                "is_ring": False, "ring_score": 0.8,
                "edges": [{"source": account_id, "target": "A1001", "via": "device", "ref": "D-1", "weight": 1.0}],
                "member_summary": [{"id": account_id, "status": "ACTIVE", "account_type": "personal", "country": "US", "alert_count": 0}],
            },
            "evidence": [{"cypher": "CALL algo.WCC()", "params": {}, "row_count": 2}],
        },
        {
            "ok": True, "tool": "rank_ring_leaders", "summary": "PageRank leader A1001.",
            "data": {"ring_leader": "A1001", "ranking": [{"account_id": "A1001", "pagerank_money": 0.7, "pagerank_identity": 0.5}]},
            "evidence": [{"cypher": "CALL algo.pageRank()", "params": {}, "row_count": 2}],
        },
        {
            "ok": True, "tool": "trace_money_path", "summary": "Money path found.",
            "data": {"paths": [{"accounts": [account_id, "A1001"], "transfers": [{"amount": 500.0, "txn_id": "T-1"}], "hops": 1}]},
            "evidence": [{"cypher": "MATCH p=...", "params": {}, "row_count": 1}],
        },
        {
            "ok": True, "tool": "find_identity_links", "summary": "Shared device found.",
            "data": {"shared_devices": [{"device_id": "D-1", "device_type": "mobile", "other_accounts": ["A1001"]}], "shared_ips": [], "shared_owners": [], "shared_brokers": []},
            "evidence": [{"cypher": "MATCH (d:Device)", "params": {}, "row_count": 1}],
        },
        {
            "ok": True, "tool": "calculate_risk_score", "summary": "Risk score computed.",
            "data": {"account_id": account_id, "risk_score": 0.91, "risk_class": "CRITICAL", "method": "random_forest (synthetic-data trained)", "all_features": {"component_size": 2}},
            "evidence": [],
        },
        {"ok": True, "tool": "generate_verdict", "summary": "Verdict generated.", "data": {**VERDICT, "account_id": account_id}, "evidence": []},
    ]
    return InvestigationResult(account_id=account_id, mode="rule_based", steps=steps, verdict={**VERDICT, "account_id": account_id}, narrative=None, graph_health={"connected": True, "host": "localhost", "port": "6379", "graph": "ringtrace", "error": None})


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("RINGTRACE_AUTH_SECRET", "test-only-secret-for-ringtrace-auth-tests-2026")
    monkeypatch.setenv("RINGTRACE_DEMO_USERNAME", "demo-analyst")
    monkeypatch.setenv("RINGTRACE_DEMO_PASSWORD", "test-only-password")
    monkeypatch.setenv("RINGTRACE_SESSION_TTL_SECONDS", "28800")
    monkeypatch.setenv("RINGTRACE_APPROVAL_TTL_SECONDS", "300")
    monkeypatch.setenv("RINGTRACE_AUTH_COOKIE_SECURE", "false")  # TestClient uses local HTTP.
    old_store = api_main.app.state.investigations
    old_sessions = api_main.app.state.auth_sessions
    api_main.app.state.investigations = InvestigationStore()
    api_main.app.state.auth_sessions = AuthSessionRegistry()
    monkeypatch.setattr(api_main, "_graph_health", lambda: {
        "connected": False, "host": "test", "port": "offline", "graph": "ringtrace",
        "error": "graph disabled in API contract tests",
    })

    def disabled_graph():
        raise RuntimeError("graph disabled in API contract tests")

    monkeypatch.setattr(api_main, "get_graph", disabled_graph)
    try:
        with TestClient(api_main.app, base_url="http://localhost") as test_client:
            yield test_client
    finally:
        api_main.app.state.investigations = old_store
        api_main.app.state.auth_sessions = old_sessions


def patch_investigator(monkeypatch, result=None, *, by_account=None):
    class FakeInvestigator:
        def investigate(self, account_id=None, query="", max_iterations=None):
            if by_account and account_id in by_account:
                return deepcopy(by_account[account_id])
            return deepcopy(result or sample_result(account_id or "A1027"))
    monkeypatch.setattr(api_main, "Investigator", FakeInvestigator)


def create_case(client, monkeypatch):
    patch_investigator(monkeypatch)
    response = client.post("/api/investigate", json={"account_id": "A1027"})
    assert response.status_code == 201
    return response.json()


def sign_in(client, username="demo-analyst", password="test-only-password"):
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()["csrf_token"]


def action_headers(csrf_token):
    return {"X-CSRF-Token": csrf_token}


def test_api_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "ringtrace-api"}


def test_root_serves_frontend_when_built_and_api_fallback_otherwise(client):
    response = client.get("/")
    assert response.status_code == 200
    if api_main.FRONTEND_DIST.joinpath("index.html").is_file():
        assert "<div id=\"root\"></div>" in response.text
        assert "RingTrace" in response.text
    else:
        assert response.json()["service"] == "RingTrace API"


@pytest.mark.parametrize("path", ["/cases", "/risk", "/graph", "/investigate/RT-DEMO"])
def test_spa_client_routes_serve_index(client, path):
    if not api_main.FRONTEND_DIST.joinpath("index.html").is_file():
        pytest.skip("frontend has not been built")
    response = client.get(path)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "<div id=\"root\"></div>" in response.text


def test_spa_serves_compiled_frontend_asset(client):
    assets_dir = api_main.FRONTEND_DIST / "assets"
    assets = sorted(assets_dir.glob("*.js"))
    if not assets:
        pytest.skip("frontend has not been built")
    response = client.get(f"/assets/{assets[0].name}")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]


def test_graph_health_returns_connection_state(client, monkeypatch):
    monkeypatch.setattr(api_main, "_graph_health", lambda: {"connected": True, "host": "db", "port": "6379", "graph": "ringtrace", "error": None})
    assert client.get("/api/graph/health").json()["connected"] is True


def test_graph_health_is_diagnostic_when_probe_raises(client, monkeypatch):
    def fail():
        raise RuntimeError("offline")
    monkeypatch.setattr(api_main, "_graph_health", fail)
    response = client.get("/api/graph/health")
    assert response.status_code == 200
    assert response.json()["connected"] is False
    assert response.json()["error"] == "offline"


def test_scenarios_include_seeded_demo_accounts(client):
    items = client.get("/api/scenarios").json()
    assert any(item["id"] == "DEMO-03" and item["account_id"] == "A1320" for item in items)
    assert any(item["id"] == "CASE-C" and item["account_id"] == "A1027" for item in items)


def test_unknown_scenario_is_404(client):
    response = client.post("/api/investigate", json={"scenario_id": "NO-SUCH-SCENARIO"})
    assert response.status_code == 404


def test_missing_investigation_target_is_422(client):
    response = client.post("/api/investigate", json={})
    assert response.status_code == 422


def test_invalid_account_id_is_rejected(client):
    response = client.post("/api/investigate", json={"account_id": "not-an-account"})
    assert response.status_code == 422


def test_query_can_supply_account_id(client, monkeypatch):
    patch_investigator(monkeypatch)
    response = client.post("/api/investigate", json={"query": "Investigate account A1027 now"})
    assert response.status_code == 201
    assert response.json()["account_id"] == "A1027"


def test_scenario_can_supply_account_id(client, monkeypatch):
    patch_investigator(monkeypatch)
    response = client.post("/api/investigate", json={"scenario_id": "DEMO-03"})
    assert response.status_code == 201
    assert response.json()["account_id"] == "A1320"


def test_investigation_returns_and_indexes_actual_steps(client, monkeypatch):
    patch_investigator(monkeypatch)
    response = client.post("/api/investigate", json={"account_id": "A1027"})
    assert response.status_code == 201
    data = response.json()
    assert data["result"]["steps"][0]["tool"] == "get_account_context"
    assert data["result"]["verdict"]["risk_class"] == "CRITICAL"
    assert data["status"] == "investigated"


def test_graph_unavailable_returns_503(client, monkeypatch):
    result = InvestigationResult(account_id="A1027", mode="none", error="FalkorDB is unreachable", graph_health={"connected": False})
    patch_investigator(monkeypatch, result)
    response = client.post("/api/investigate", json={"account_id": "A1027"})
    assert response.status_code == 503


def test_unknown_graph_account_returns_404(client, monkeypatch):
    result = InvestigationResult(account_id="A9999", mode="rule_based", steps=[{"tool": "get_account_context", "ok": False, "error": "account_not_found", "summary": "not found"}], verdict={}, graph_health={"connected": True})
    patch_investigator(monkeypatch, result)
    response = client.post("/api/investigate", json={"account_id": "A9999"})
    assert response.status_code == 404


def test_empty_engine_verdict_returns_502(client, monkeypatch):
    result = InvestigationResult(account_id="A1027", mode="rule_based", steps=[{"tool": "get_account_context", "ok": True}], verdict={}, graph_health={"connected": True})
    patch_investigator(monkeypatch, result)
    response = client.post("/api/investigate", json={"account_id": "A1027"})
    assert response.status_code == 502


def test_cases_list_and_case_retrieval(client, monkeypatch):
    case = create_case(client, monkeypatch)
    listing = client.get("/api/cases").json()
    # The endpoint also includes durable FalkorDB action cases from earlier
    # investigations, so assert presence rather than assuming an empty graph.
    assert listing["total"] >= 1
    assert any(item["case_id"] == case["case_id"] for item in listing["cases"])
    assert client.get(f"/api/cases/{case['case_id']}").json()["account_id"] == "A1027"


def test_durable_graph_case_is_normalized_as_read_only(client, monkeypatch):
    graph_case = {
        "id": "CASE-PERSISTED",
        "account_id": "A1027",
        "verdict": "FRAUD RING CONFIRMED",
        "risk_score": 0.91,
        "confidence": 0.98,
        "recommended_action": "ESCALATE_FOR_MANUAL_INVESTIGATION",
        "status": "ESCALATED",
        "notes": "Persisted synthetic action record.",
        "created_at": 1_700_000_000_000,
    }

    class FakeQueryResult:
        def __init__(self, data):
            self.data = data

    class FakeGraphStore:
        def __init__(self, _graph):
            pass

        def list_cases(self):
            return FakeQueryResult([[graph_case]])

        def get_case(self, case_id):
            return FakeQueryResult([[graph_case]] if case_id == graph_case["id"] else [])

    monkeypatch.setattr(api_main, "_graph_health", lambda: {"connected": True})
    monkeypatch.setattr(api_main, "get_graph", lambda: object())
    monkeypatch.setattr(api_main, "GraphStore", FakeGraphStore)

    listing = client.get("/api/cases").json()
    summary = next(item for item in listing["cases"] if item["case_id"] == graph_case["id"])
    detail = client.get(f"/api/cases/{graph_case['id']}").json()

    assert summary["read_only"] is True
    assert summary["result"]["mode"] == "durable_graph_record"
    assert summary["result"]["steps"] == []
    assert summary["result"]["verdict"]["risk_score"] == 0.91
    assert "risk_class" not in summary["result"]["verdict"]
    assert summary["created_at"].startswith("2023-11-14T22:13:20")
    assert detail["graph_record"]["notes"] == graph_case["notes"]


def test_unknown_case_is_404(client):
    assert client.get("/api/cases/RT-MISSING").status_code == 404


def test_investigation_detail_route(client, monkeypatch):
    case = create_case(client, monkeypatch)
    assert client.get(f"/api/investigation/{case['case_id']}").json()["case_id"] == case["case_id"]


def test_graph_export_is_derived_from_tool_outputs(client, monkeypatch):
    case = create_case(client, monkeypatch)
    graph = client.get(f"/api/investigation/{case['case_id']}/graph").json()
    node_ids = {node["id"] for node in graph["nodes"]}
    edge_types = {edge["type"] for edge in graph["edges"]}
    assert "A1027" in node_ids and "D-1" in node_ids and "M-1" in node_ids
    assert "LINKED_TO" in edge_types and "TRANSFERRED_TO" in edge_types
    assert graph["source"].startswith("FalkorDB-backed")


def test_evidence_endpoint_preserves_query_evidence(client, monkeypatch):
    case = create_case(client, monkeypatch)
    evidence = client.get(f"/api/investigation/{case['case_id']}/evidence").json()
    assert evidence["total"] >= 1
    assert evidence["evidence"][0]["tool"] == "get_account_context"
    assert "cypher" in evidence["evidence"][0]


def test_trace_endpoint_returns_ordered_agent_steps(client, monkeypatch):
    case = create_case(client, monkeypatch)
    trace = client.get(f"/api/investigation/{case['case_id']}/trace").json()
    assert trace["steps"][0]["tool"] == "get_account_context"
    assert trace["steps"][-1]["tool"] == "generate_verdict"


def test_risk_endpoint_discloses_synthetic_evaluation(client, monkeypatch):
    case = create_case(client, monkeypatch)
    risk = client.get(f"/api/investigation/{case['case_id']}/risk").json()
    assert risk["risk_class"] == "CRITICAL"
    assert risk["risk_score"] == 0.91
    assert risk["evaluation_data"] == "Synthetic evaluation data"


def test_decision_endpoint_returns_agent_verdict(client, monkeypatch):
    case = create_case(client, monkeypatch)
    decision = client.get(f"/api/investigation/{case['case_id']}/decision").json()["decision"]
    assert decision["recommended_action"] == "ESCALATE_FOR_MANUAL_INVESTIGATION"
    assert decision["ring_leader"] == "A1001"


def test_approve_action_is_explicitly_simulated(client, monkeypatch):
    case = create_case(client, monkeypatch)
    csrf = sign_in(client)
    response = client.post(f"/api/actions/{case['case_id']}/approve", headers=action_headers(csrf))
    assert response.status_code == 200
    assert response.json()["simulated"] is True
    assert response.json()["status"] == "approved"
    assert response.json()["approved_by"] == "demo-analyst"
    assert response.json()["approval_expires_at"]


def test_approve_repeat_is_rejected(client, monkeypatch):
    case = create_case(client, monkeypatch)
    csrf = sign_in(client)
    path = f"/api/actions/{case['case_id']}/approve"
    assert client.post(path, headers=action_headers(csrf)).status_code == 200
    assert client.post(path, headers=action_headers(csrf)).status_code == 409


def test_execute_requires_prior_approval(client, monkeypatch):
    case = create_case(client, monkeypatch)
    csrf = sign_in(client)
    response = client.post(f"/api/actions/{case['case_id']}/execute", json={"confirmed": True}, headers=action_headers(csrf))
    assert response.status_code == 409
    assert "Approve" in response.json()["detail"]


def test_execute_action_records_graph_write_and_is_single_use(client, monkeypatch):
    case = create_case(client, monkeypatch)
    monkeypatch.setattr(api_main, "_execute_graph_action", lambda record: ([{"ok": True, "tool": "create_investigation_case", "data": {"case_id": "CASE-1"}}], "CASE-1", "written"))
    csrf = sign_in(client)
    headers = action_headers(csrf)
    client.post(f"/api/actions/{case['case_id']}/approve", headers=headers)
    path = f"/api/actions/{case['case_id']}/execute"
    unconfirmed = client.post(path, json={"confirmed": False}, headers=headers)
    assert unconfirmed.status_code == 409
    assert "confirm" in unconfirmed.json()["detail"].lower()
    response = client.post(path, json={"confirmed": True}, headers=headers)
    assert response.status_code == 200
    assert response.json()["graph_case_id"] == "CASE-1"
    assert response.json()["graph_write_status"] == "written"
    assert response.json()["approved_by"] == "demo-analyst"
    assert response.json()["executed_by"] == "demo-analyst"
    assert client.post(path, json={"confirmed": True}, headers=headers).status_code == 409


@pytest.mark.parametrize(
    ("graph_case_id", "write_status"),
    [(None, "written"), ("CASE-UNVERIFIED", "unknown")],
)
def test_unverified_graph_write_is_never_reported_as_executed(client, monkeypatch, graph_case_id, write_status):
    case = create_case(client, monkeypatch)
    monkeypatch.setattr(
        api_main,
        "_execute_graph_action",
        lambda _record: ([{"ok": True, "tool": "create_investigation_case", "data": {"case_id": graph_case_id}}], graph_case_id, write_status),
    )
    csrf = sign_in(client)
    headers = action_headers(csrf)
    client.post(f"/api/actions/{case['case_id']}/approve", headers=headers)
    path = f"/api/actions/{case['case_id']}/execute"
    response = client.post(path, json={"confirmed": True}, headers=headers)
    assert response.status_code == 502
    assert "failed" in response.json()["detail"].lower()
    stored = client.get(f"/api/cases/{case['case_id']}").json()
    assert stored["status"] == "action_failed"
    assert stored["action"]["graph_write_status"] == "unknown"
    assert client.post(path, json={"confirmed": True}, headers=headers).status_code == 409


def test_unknown_case_action_is_404(client):
    csrf = sign_in(client)
    assert client.post("/api/actions/RT-MISSING/approve", headers=action_headers(csrf)).status_code == 404


def test_failed_action_attempt_cannot_be_replayed(client, monkeypatch):
    case = create_case(client, monkeypatch)
    def fail(_record):
        raise RuntimeError("database write failed")
    monkeypatch.setattr(api_main, "_execute_graph_action", fail)
    csrf = sign_in(client)
    headers = action_headers(csrf)
    client.post(f"/api/actions/{case['case_id']}/approve", headers=headers)
    path = f"/api/actions/{case['case_id']}/execute"
    assert client.post(path, json={"confirmed": True}, headers=headers).status_code == 502
    assert client.post(path, json={"confirmed": True}, headers=headers).status_code == 409


@pytest.mark.parametrize("reported_api_case_id, should_pass", [("RT-EXPECTED", True), ("RT-OTHER", False)])
def test_graph_action_requires_final_audit_bound_to_expected_api_case(monkeypatch, reported_api_case_id, should_pass):
    case = {
        "case_id": "RT-EXPECTED",
        "account_id": "A1027",
        "approval": {
            "approved_by": "demo-analyst",
            "approved_at": "2026-10-13T12:00:00+00:00",
            "expires_at": "2026-10-13T12:05:00+00:00",
        },
        "action": {
            "action_type": "ESCALATE_FOR_MANUAL_INVESTIGATION",
            "execution_actor": "demo-analyst",
            "started_at": "2026-10-13T12:01:00+00:00",
        },
        "result": {
            "steps": [],
            "verdict": {"recommended_action": "ESCALATE_FOR_MANUAL_INVESTIGATION"},
        },
    }
    monkeypatch.setattr(api_main, "get_graph", lambda: object())
    monkeypatch.setattr(api_main, "GraphStore", lambda _graph: object())
    monkeypatch.setattr(api_main, "RiskScorer", lambda: object())
    monkeypatch.setattr(api_main, "execute_recommended_action", lambda *_args: [
        {"tool": "create_investigation_case", "ok": True, "data": {"case_id": "GRAPH-CASE-1"}},
        {
            "tool": "finalize_case_action_audit",
            "ok": True,
            "data": {
                "case_id": "GRAPH-CASE-1",
                "api_case_id": reported_api_case_id,
                "action_outcome": "succeeded",
                "graph_write_status": "written",
            },
        },
    ])

    if should_pass:
        results, graph_case_id, write_status = api_main._execute_graph_action(case)
        assert results
        assert graph_case_id == "GRAPH-CASE-1"
        assert write_status == "written"
    else:
        with pytest.raises(RuntimeError, match="expected case"):
            api_main._execute_graph_action(case)


def test_case_listing_is_available_when_graph_probe_fails(client, monkeypatch):
    case = create_case(client, monkeypatch)
    monkeypatch.setattr(api_main, "_graph_health", lambda: {"connected": False})
    data = client.get("/api/cases").json()
    assert data["graph_connected"] is False
    assert data["cases"][0]["case_id"] == case["case_id"]


def test_api_404_does_not_fall_through_to_spa(client):
    response = client.get("/api/no-such-route")
    assert response.status_code == 404
