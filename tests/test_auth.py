"""Authentication, CSRF, approval-binding, and one-time action contract tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import time

import pytest
from fastapi.testclient import TestClient

import api.main as api_main
from agent.investigator import InvestigationResult
from api.auth import AuthSessionRegistry, SESSION_COOKIE_NAME
from api.store import InvestigationStore


TEST_SECRET = "test-only-secret-for-ringtrace-auth-tests-2026"
TEST_USER = "demo-analyst"
TEST_PASSWORD = "test-only-password"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("RINGTRACE_AUTH_SECRET", TEST_SECRET)
    monkeypatch.setenv("RINGTRACE_DEMO_USERNAME", TEST_USER)
    monkeypatch.setenv("RINGTRACE_DEMO_PASSWORD", TEST_PASSWORD)
    monkeypatch.setenv("RINGTRACE_SESSION_TTL_SECONDS", "28800")
    monkeypatch.setenv("RINGTRACE_APPROVAL_TTL_SECONDS", "300")
    monkeypatch.setenv("RINGTRACE_AUTH_COOKIE_SECURE", "false")  # TestClient uses local HTTP.
    old_store = api_main.app.state.investigations
    old_sessions = api_main.app.state.auth_sessions
    api_main.app.state.investigations = InvestigationStore()
    api_main.app.state.auth_sessions = AuthSessionRegistry()
    try:
        with TestClient(api_main.app, base_url="http://localhost") as test_client:
            yield test_client
    finally:
        api_main.app.state.investigations = old_store
        api_main.app.state.auth_sessions = old_sessions


def login(client: TestClient, username: str = TEST_USER, password: str = TEST_PASSWORD) -> dict:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def create_case() -> dict:
    return api_main.app.state.investigations.create(
        "A1027",
        {"verdict": {"recommended_action": "ESCALATE_FOR_MANUAL_INVESTIGATION"}},
    )


def headers(csrf_token: str) -> dict[str, str]:
    return {"X-CSRF-Token": csrf_token}


def test_read_only_endpoints_remain_available_without_login(client):
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/scenarios").status_code == 200
    assert client.get("/api/auth/session").json()["authenticated"] is False


def test_investigation_route_remains_read_only_and_usable_without_login(client, monkeypatch):
    class FakeInvestigator:
        def investigate(self, account_id=None, query="", max_iterations=None):
            return InvestigationResult(
                account_id=account_id or "A1100",
                mode="rule_based",
                steps=[],
                verdict={"account_id": account_id or "A1100", "recommended_action": "NO_ACTION_REQUIRED"},
                narrative=None,
                graph_health={"connected": True, "host": "disposable-test", "port": "6380", "graph": "ringtrace", "error": None},
            )

    monkeypatch.setattr(api_main, "Investigator", FakeInvestigator)
    response = client.post("/api/investigate", json={"account_id": "A1100"})
    assert response.status_code == 201
    assert response.json()["case_id"].startswith("RT-")
    assert client.get("/api/auth/session").json()["authenticated"] is False


def test_actions_fail_closed_when_demo_auth_is_not_configured(client, monkeypatch):
    monkeypatch.delenv("RINGTRACE_AUTH_SECRET")
    session = client.get("/api/auth/session")
    assert session.status_code == 200
    assert session.json() == {"auth_enabled": False, "authenticated": False, "analyst": None, "csrf_token": None, "expires_at": None}
    assert client.post("/api/auth/login", json={"username": TEST_USER, "password": TEST_PASSWORD}).status_code == 503
    monkeypatch.setenv("RINGTRACE_AUTH_SECRET", "too-short")
    assert client.get("/api/auth/session").json()["auth_enabled"] is False
    monkeypatch.delenv("RINGTRACE_AUTH_SECRET")
    assert client.post("/api/actions/RT-MISSING/approve").status_code == 503
    assert client.post("/api/actions/RT-MISSING/execute", json={"confirmed": True}).status_code == 503


def test_all_action_routes_require_a_valid_session(client):
    assert client.post("/api/actions/RT-MISSING/approve").status_code == 401
    assert client.post("/api/actions/RT-MISSING/execute", json={"confirmed": True}).status_code == 401


def test_login_uses_http_only_signed_cookie_and_does_not_echo_password(client):
    failed = client.post("/api/auth/login", json={"username": TEST_USER, "password": "wrong"})
    assert failed.status_code == 401
    assert SESSION_COOKIE_NAME not in failed.cookies

    result = login(client)
    cookie = client.cookies.get(SESSION_COOKIE_NAME)
    assert cookie
    set_cookie = client.cookies.jar
    cookie_item = next(item for item in set_cookie if item.name == SESSION_COOKIE_NAME)
    assert cookie_item.has_nonstandard_attr("HttpOnly") or "httponly" in str(client.cookies).lower()
    assert cookie_item.path == "/api"
    assert result["authenticated"] is True
    assert result["analyst"] == TEST_USER
    assert result["csrf_token"]
    assert TEST_PASSWORD not in cookie
    assert TEST_PASSWORD not in failed.text
    assert client.get("/api/auth/session").json()["analyst"] == TEST_USER


def test_invalid_login_payload_does_not_echo_password(client):
    supplied_secret = "password-that-must-not-appear-" + "x" * 1100
    for password in (supplied_secret, [supplied_secret]):
        response = client.post(
            "/api/auth/login",
            json={"username": TEST_USER, "password": password},
        )
        assert response.status_code == 422
        assert response.json() == {"detail": "Invalid login request."}
        assert supplied_secret not in response.text
        assert response.headers["cache-control"] == "no-store"


def test_cookie_is_secure_when_request_is_https(client, monkeypatch):
    monkeypatch.setenv("RINGTRACE_AUTH_COOKIE_SECURE", "true")
    response = client.post(
        "/api/auth/login",
        json={"username": TEST_USER, "password": TEST_PASSWORD},
        headers={"X-Forwarded-Proto": "https"},
    )
    assert response.status_code == 200
    set_cookie = response.headers["set-cookie"].lower()
    assert "secure" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie


def test_cookie_defaults_secure_without_proxy_headers(client, monkeypatch):
    monkeypatch.delenv("RINGTRACE_AUTH_COOKIE_SECURE", raising=False)
    response = client.post(
        "/api/auth/login",
        json={"username": TEST_USER, "password": TEST_PASSWORD},
    )
    assert response.status_code == 200
    assert "secure" in response.headers["set-cookie"].lower()


def test_cookie_opt_out_is_limited_to_local_plain_http(client, monkeypatch):
    monkeypatch.setenv("RINGTRACE_AUTH_COOKIE_SECURE", "false")
    local = client.post(
        "/api/auth/login",
        json={"username": TEST_USER, "password": TEST_PASSWORD},
    )
    assert local.status_code == 200
    assert "secure" not in local.headers["set-cookie"].lower()

    remote = client.post(
        "/api/auth/login",
        json={"username": TEST_USER, "password": TEST_PASSWORD},
        headers={"Host": "demo.example.test", "X-Forwarded-Proto": "http"},
    )
    assert remote.status_code == 200
    assert "secure" in remote.headers["set-cookie"].lower()


def test_cross_site_login_is_rejected(client):
    response = client.post(
        "/api/auth/login",
        json={"username": TEST_USER, "password": TEST_PASSWORD},
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert response.status_code == 403


def test_approval_requires_csrf_and_ignores_client_claimed_actor(client):
    case = create_case()
    session = login(client)
    path = f"/api/actions/{case['case_id']}/approve"
    assert client.post(path).status_code == 403
    assert client.post(path, headers=headers("forged"), json={"approved_by": "attacker"}).status_code == 403
    response = client.post(path, headers=headers(session["csrf_token"]), json={"approved_by": "attacker"})
    assert response.status_code == 200
    assert response.json()["approved_by"] == TEST_USER
    assert api_main.app.state.investigations.get(case["case_id"])["approval"]["approved_by"] == TEST_USER


def test_logout_revokes_signed_session_and_requires_csrf(client):
    session = login(client)
    old_cookie = client.cookies.get(SESSION_COOKIE_NAME)
    response = client.post("/api/auth/logout", headers=headers(session["csrf_token"]))
    assert response.status_code == 200
    assert response.json()["authenticated"] is False
    client.cookies.set(SESSION_COOKIE_NAME, old_cookie, path="/api")
    assert client.get("/api/auth/session").json()["authenticated"] is False
    assert client.post("/api/actions/RT-MISSING/approve").status_code == 401


def test_signed_session_expires(client, monkeypatch):
    monkeypatch.setenv("RINGTRACE_SESSION_TTL_SECONDS", "1")
    session = login(client)
    assert session["authenticated"] is True
    time.sleep(1.1)
    assert client.get("/api/auth/session").json()["authenticated"] is False


def test_approval_expiry_blocks_execution_and_can_be_renewed(client, monkeypatch):
    clock = [datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)]
    monkeypatch.setattr("api.store.utc_now", lambda: clock[0].isoformat())
    case = create_case()
    session = login(client)
    path = f"/api/actions/{case['case_id']}/approve"
    csrf_headers = headers(session["csrf_token"])
    assert client.post(path, headers=csrf_headers).status_code == 200
    clock[0] += timedelta(seconds=301)
    execution = client.post(
        f"/api/actions/{case['case_id']}/execute",
        json={"confirmed": True},
        headers=csrf_headers,
    )
    assert execution.status_code == 409
    assert "expired" in execution.json()["detail"].lower()
    assert api_main.app.state.investigations.get(case["case_id"])["status"] == "approval_expired"
    renewed = client.post(path, headers=csrf_headers)
    assert renewed.status_code == 200
    history = api_main.app.state.investigations.get(case["case_id"])["approval_history"]
    assert len(history) == 2
    assert history[0]["approved_by"] == history[1]["approved_by"] == TEST_USER
    assert history[0]["expires_at"] < history[1]["expires_at"]


def test_same_analyst_must_approve_and_execute(client, monkeypatch):
    case = create_case()
    approver = login(client)
    approve_path = f"/api/actions/{case['case_id']}/approve"
    assert client.post(approve_path, headers=headers(approver["csrf_token"])).status_code == 200

    monkeypatch.setenv("RINGTRACE_DEMO_USERNAME", "second-analyst")
    monkeypatch.setenv("RINGTRACE_DEMO_PASSWORD", "second-test-password")
    executor = login(client, "second-analyst", "second-test-password")
    response = client.post(
        f"/api/actions/{case['case_id']}/execute",
        json={"confirmed": True},
        headers=headers(executor["csrf_token"]),
    )
    assert response.status_code == 403
    assert "same authenticated analyst" in response.json()["detail"]
    assert api_main.app.state.investigations.get(case["case_id"])["execution_attempted"] is False


def test_approval_is_bound_to_case_and_recommended_action(client):
    case = create_case()
    session = login(client)
    csrf_headers = headers(session["csrf_token"])
    assert client.post(f"/api/actions/{case['case_id']}/approve", headers=csrf_headers).status_code == 200
    internal = api_main.app.state.investigations._cases[case["case_id"]]
    internal["result"]["verdict"]["recommended_action"] = "ADD_TO_WATCHLIST"
    response = client.post(
        f"/api/actions/{case['case_id']}/execute",
        json={"confirmed": True},
        headers=csrf_headers,
    )
    assert response.status_code == 409
    assert "does not match" in response.json()["detail"]
    assert internal["execution_attempted"] is False


def test_execution_requires_explicit_confirmation_and_rejects_client_actor_fields(client):
    case = create_case()
    session = login(client)
    csrf_headers = headers(session["csrf_token"])
    assert client.post(f"/api/actions/{case['case_id']}/approve", headers=csrf_headers).status_code == 200
    unconfirmed = client.post(
        f"/api/actions/{case['case_id']}/execute",
        json={"confirmed": False},
        headers=csrf_headers,
    )
    assert unconfirmed.status_code == 409
    string_confirmation = client.post(
        f"/api/actions/{case['case_id']}/execute",
        json={"confirmed": "true"},
        headers=csrf_headers,
    )
    assert string_confirmation.status_code == 422
    forged = client.post(
        f"/api/actions/{case['case_id']}/execute",
        json={"confirmed": True, "execution_actor": "attacker"},
        headers=csrf_headers,
    )
    assert forged.status_code == 422
    assert api_main.app.state.investigations.get(case["case_id"])["execution_attempted"] is False
