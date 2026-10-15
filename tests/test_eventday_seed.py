"""Safety and determinism checks for the event-day synthetic seed."""
from __future__ import annotations

import secrets

import pytest

from eventday import graph as eventday_graph
from eventday import seed
from eventday.graph import graph_settings


def test_eventday_graph_settings_do_not_inherit_legacy_graph_endpoint(monkeypatch):
    monkeypatch.setenv("FALKORDB_HOST", "legacy-db")
    monkeypatch.setenv("FALKORDB_PORT", "6379")
    monkeypatch.delenv("RINGTRACE_EVENTDAY_FALKORDB_HOST", raising=False)
    monkeypatch.delenv("RINGTRACE_EVENTDAY_FALKORDB_PORT", raising=False)
    monkeypatch.delenv("RINGTRACE_EVENTDAY_FALKORDB_TLS", raising=False)
    monkeypatch.delenv("RINGTRACE_EVENTDAY_GRAPH", raising=False)
    host, port, graph_name, _, _, tls = graph_settings()
    assert (host, port, graph_name, tls) == ("127.0.0.1", 6380, "ringtrace_eventday", False)


@pytest.mark.parametrize(
    ("host", "port", "graph_name", "tls", "username", "password", "message"),
    [
        ("127.0.0.1", "6379", "ringtrace_eventday_test", "0", "", "", "port 6379"),
        ("127.0.0.1", "6380", "legacy_shared_graph", "0", "", "", "graph name"),
        ("127.0.0.1", "6380", "ringtrace_eventdayevil", "0", "", "", "graph name"),
        ("cloud.example", "16380", "ringtrace_eventday_test", "0", "", "", "TLS"),
        ("cloud.example", "16380", "ringtrace_eventday_test", "1", "demo-user", "", "username and password"),
    ],
)
def test_eventday_graph_client_rejects_unsafe_target_before_connecting(
    monkeypatch, host, port, graph_name, tls, username, password, message
):
    monkeypatch.setenv("RINGTRACE_EVENTDAY_FALKORDB_HOST", host)
    monkeypatch.setenv("RINGTRACE_EVENTDAY_FALKORDB_PORT", port)
    monkeypatch.setenv("RINGTRACE_EVENTDAY_GRAPH", graph_name)
    monkeypatch.setenv("RINGTRACE_EVENTDAY_FALKORDB_TLS", tls)
    monkeypatch.setenv("RINGTRACE_EVENTDAY_FALKORDB_USERNAME", username)
    monkeypatch.setenv("RINGTRACE_EVENTDAY_FALKORDB_PASSWORD", password)
    monkeypatch.setattr(eventday_graph, "_graph_cache", {})
    monkeypatch.setattr(
        eventday_graph,
        "FalkorDB",
        lambda **_: pytest.fail("unsafe target must be rejected before client construction"),
    )

    with pytest.raises(RuntimeError, match=message):
        eventday_graph.get_event_graph()


def test_eventday_graph_client_refuses_implicit_local_defaults(monkeypatch):
    monkeypatch.delenv("RINGTRACE_EVENTDAY_FALKORDB_HOST", raising=False)
    monkeypatch.delenv("RINGTRACE_EVENTDAY_FALKORDB_PORT", raising=False)
    monkeypatch.setenv("RINGTRACE_EVENTDAY_FALKORDB_TLS", "0")
    monkeypatch.setenv("RINGTRACE_EVENTDAY_GRAPH", "ringtrace_eventday")
    monkeypatch.setattr(
        eventday_graph,
        "FalkorDB",
        lambda **_: pytest.fail("missing endpoint must not fall back to localhost"),
    )

    with pytest.raises(RuntimeError, match="explicitly configured event-day host and port"):
        eventday_graph.get_event_graph()


def test_cloud_target_is_restricted_to_the_dedicated_test_graph(monkeypatch):
    monkeypatch.setenv("RINGTRACE_EVENTDAY_FALKORDB_HOST", "cloud.example")
    monkeypatch.setenv("RINGTRACE_EVENTDAY_FALKORDB_PORT", "16380")
    monkeypatch.setenv("RINGTRACE_EVENTDAY_FALKORDB_USERNAME", "demo-user")
    monkeypatch.setenv("RINGTRACE_EVENTDAY_FALKORDB_PASSWORD", secrets.token_urlsafe(24))
    monkeypatch.setenv("RINGTRACE_EVENTDAY_FALKORDB_TLS", "1")
    monkeypatch.setenv("RINGTRACE_EVENTDAY_GRAPH", "ringtrace_eventday_stage")
    monkeypatch.setattr(eventday_graph, "_graph_cache", {})
    monkeypatch.setattr(
        eventday_graph,
        "FalkorDB",
        lambda **_: pytest.fail("non-test cloud graph must be rejected before client construction"),
    )

    with pytest.raises(RuntimeError, match="restricted to graph 'ringtrace_eventday_test'"):
        eventday_graph.get_event_graph()


def test_tls_requires_explicit_host_and_port_to_prevent_local_fallback(monkeypatch):
    monkeypatch.delenv("RINGTRACE_EVENTDAY_FALKORDB_HOST", raising=False)
    monkeypatch.delenv("RINGTRACE_EVENTDAY_FALKORDB_PORT", raising=False)
    monkeypatch.setenv("RINGTRACE_EVENTDAY_FALKORDB_TLS", "1")
    monkeypatch.setenv("RINGTRACE_EVENTDAY_GRAPH", "ringtrace_eventday_test")
    monkeypatch.setattr(
        eventday_graph,
        "FalkorDB",
        lambda **_: pytest.fail("missing cloud endpoint must not fall back to localhost"),
    )

    with pytest.raises(RuntimeError, match="explicitly configured event-day host and port"):
        eventday_graph.get_event_graph()


def test_tls_cloud_target_passes_auth_and_verified_tls_to_falkordb_client(monkeypatch):
    captured = {}

    class FakeGraph:
        pass

    class FakeClient:
        def __init__(self, **options):
            captured.update(options)

        def select_graph(self, graph_name):
            captured["graph_name"] = graph_name
            return FakeGraph()

    test_password = secrets.token_urlsafe(24)
    monkeypatch.setenv("RINGTRACE_EVENTDAY_FALKORDB_HOST", "cloud.example")
    monkeypatch.setenv("RINGTRACE_EVENTDAY_FALKORDB_PORT", "16380")
    monkeypatch.setenv("RINGTRACE_EVENTDAY_FALKORDB_USERNAME", "demo-user")
    monkeypatch.setenv("RINGTRACE_EVENTDAY_FALKORDB_PASSWORD", test_password)
    monkeypatch.setenv("RINGTRACE_EVENTDAY_FALKORDB_TLS", "1")
    monkeypatch.setenv("RINGTRACE_EVENTDAY_GRAPH", "ringtrace_eventday_test")
    monkeypatch.setattr(eventday_graph, "_graph_cache", {})
    monkeypatch.setattr(eventday_graph, "FalkorDB", FakeClient)

    graph = eventday_graph.get_event_graph()

    assert isinstance(graph, FakeGraph)
    assert captured["host"] == "cloud.example"
    assert captured["port"] == 16380
    assert captured["username"] == "demo-user"
    assert secrets.compare_digest(captured.get("password", ""), test_password)
    assert captured["ssl"] is True
    assert captured["ssl_check_hostname"] is True
    assert captured["graph_name"] == "ringtrace_eventday_test"


def test_fixture_is_deterministic_and_all_payment_ids_are_synthetic():
    first = seed.fixture()
    second = seed.fixture()
    assert first == second
    assert {item["id"] for item in first["payments"]} == {
        "PAY-ALERT-1001", "PAY-ALERT-1002", "PAY-ALERT-1003",
        "PAY-BENIGN-2001", "PAY-AMBIG-3001",
    }
    assert all(item["currency"] == "USD" for item in first["payments"])
    assert first["payments"][0]["occurred_at"] < first["payments"][1]["occurred_at"] < first["payments"][2]["occurred_at"]


def test_seed_refuses_without_disposable_opt_in(monkeypatch):
    monkeypatch.setenv("RINGTRACE_EVENTDAY_ENABLED", "1")
    monkeypatch.delenv("RINGTRACE_EVENTDAY_DISPOSABLE", raising=False)
    with pytest.raises(RuntimeError, match="RINGTRACE_EVENTDAY_DISPOSABLE=1"):
        seed.seed_eventday_graph()


def test_seed_refuses_implicit_local_defaults(monkeypatch):
    monkeypatch.setenv("RINGTRACE_EVENTDAY_ENABLED", "1")
    monkeypatch.setenv("RINGTRACE_EVENTDAY_DISPOSABLE", "1")
    monkeypatch.delenv("RINGTRACE_EVENTDAY_FALKORDB_HOST", raising=False)
    monkeypatch.delenv("RINGTRACE_EVENTDAY_FALKORDB_PORT", raising=False)
    with pytest.raises(RuntimeError, match="explicitly configured event-day host and port"):
        seed.seed_eventday_graph()


def test_seed_refuses_remote_host_without_tls_and_auth(monkeypatch):
    monkeypatch.setenv("RINGTRACE_EVENTDAY_ENABLED", "1")
    monkeypatch.setenv("RINGTRACE_EVENTDAY_DISPOSABLE", "1")
    monkeypatch.setenv("RINGTRACE_EVENTDAY_FALKORDB_HOST", "shared-graph.example")
    monkeypatch.setenv("RINGTRACE_EVENTDAY_FALKORDB_PORT", "6380")
    monkeypatch.setenv("RINGTRACE_EVENTDAY_FALKORDB_TLS", "0")
    monkeypatch.delenv("RINGTRACE_EVENTDAY_FALKORDB_USERNAME", raising=False)
    monkeypatch.delenv("RINGTRACE_EVENTDAY_FALKORDB_PASSWORD", raising=False)
    monkeypatch.setenv("RINGTRACE_EVENTDAY_GRAPH", "ringtrace_eventday_test")
    with pytest.raises(RuntimeError, match="remote seed without TLS"):
        seed.seed_eventday_graph()


def test_seed_allows_only_explicit_tls_cloud_test_target_without_connecting(monkeypatch):
    monkeypatch.setenv("RINGTRACE_EVENTDAY_ENABLED", "1")
    monkeypatch.setenv("RINGTRACE_EVENTDAY_DISPOSABLE", "1")
    monkeypatch.setenv("RINGTRACE_EVENTDAY_FALKORDB_HOST", "cloud.example")
    monkeypatch.setenv("RINGTRACE_EVENTDAY_FALKORDB_PORT", "16380")
    monkeypatch.setenv("RINGTRACE_EVENTDAY_FALKORDB_USERNAME", "demo-user")
    monkeypatch.setenv("RINGTRACE_EVENTDAY_FALKORDB_PASSWORD", secrets.token_urlsafe(24))
    monkeypatch.setenv("RINGTRACE_EVENTDAY_FALKORDB_TLS", "1")
    monkeypatch.setenv("RINGTRACE_EVENTDAY_GRAPH", "ringtrace_eventday_test")

    def stub_connection():
        raise RuntimeError("stubbed before connection")

    monkeypatch.setattr(seed, "get_event_graph", stub_connection)
    with pytest.raises(RuntimeError, match="stubbed before connection"):
        seed.seed_eventday_graph()


def test_seed_refuses_port_6379_even_with_disposable_opt_in(monkeypatch):
    monkeypatch.setenv("RINGTRACE_EVENTDAY_ENABLED", "1")
    monkeypatch.setenv("RINGTRACE_EVENTDAY_DISPOSABLE", "1")
    monkeypatch.setenv("RINGTRACE_EVENTDAY_FALKORDB_HOST", "127.0.0.1")
    monkeypatch.setenv("RINGTRACE_EVENTDAY_FALKORDB_PORT", "6379")
    monkeypatch.setenv("RINGTRACE_EVENTDAY_GRAPH", "ringtrace_eventday_test")
    with pytest.raises(RuntimeError, match="Refusing to seed port 6379"):
        seed.seed_eventday_graph()
