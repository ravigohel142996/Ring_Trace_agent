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
    old_store = api_main.app.state.investigations
    api_main.app.state.investigations = InvestigationStore()
    with TestClient(api_main.app) as test_client:
        yield test_client
    api_main.app.state.investigations = old_store


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
    assert listing["total"] == 1
    assert listing["cases"][0]["case_id"] == case["case_id"]
    assert client.get(f"/api/cases/{case['case_id']}").json()["account_id"] == "A1027"


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
    response = client.post(f"/api/actions/{case['case_id']}/approve")
    assert response.status_code == 200
    assert response.json()["simulated"] is True
    assert response.json()["status"] == "approved"


def test_approve_repeat_is_rejected(client, monkeypatch):
    case = create_case(client, monkeypatch)
    path = f"/api/actions/{case['case_id']}/approve"
    assert client.post(path).status_code == 200
    assert client.post(path).status_code == 409


def test_execute_requires_prior_approval(client, monkeypatch):
    case = create_case(client, monkeypatch)
    assert client.post(f"/api/actions/{case['case_id']}/execute").status_code == 409


def test_execute_action_records_graph_write_and_is_single_use(client, monkeypatch):
    case = create_case(client, monkeypatch)
    monkeypatch.setattr(api_main, "_execute_graph_action", lambda record: ([{"ok": True, "tool": "create_investigation_case", "data": {"case_id": "CASE-1"}}], "CASE-1", "written"))
    client.post(f"/api/actions/{case['case_id']}/approve")
    path = f"/api/actions/{case['case_id']}/execute"
    response = client.post(path)
    assert response.status_code == 200
    assert response.json()["graph_case_id"] == "CASE-1"
    assert response.json()["graph_write_status"] == "written"
    assert client.post(path).status_code == 409


def test_unknown_case_action_is_404(client):
    assert client.post("/api/actions/RT-MISSING/approve").status_code == 404


def test_failed_action_attempt_cannot_be_replayed(client, monkeypatch):
    case = create_case(client, monkeypatch)
    def fail(_record):
        raise RuntimeError("database write failed")
    monkeypatch.setattr(api_main, "_execute_graph_action", fail)
    client.post(f"/api/actions/{case['case_id']}/approve")
    path = f"/api/actions/{case['case_id']}/execute"
    assert client.post(path).status_code == 502
    assert client.post(path).status_code == 409


def test_case_listing_is_available_when_graph_probe_fails(client, monkeypatch):
    case = create_case(client, monkeypatch)
    monkeypatch.setattr(api_main, "_graph_health", lambda: {"connected": False})
    data = client.get("/api/cases").json()
    assert data["graph_connected"] is False
    assert data["cases"][0]["case_id"] == case["case_id"]


def test_api_404_does_not_fall_through_to_spa(client):
    response = client.get("/api/no-such-route")
    assert response.status_code == 404
