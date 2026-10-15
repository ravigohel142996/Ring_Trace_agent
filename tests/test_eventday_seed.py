"""Safety and determinism checks for the event-day synthetic seed."""
from __future__ import annotations

import pytest

from eventday import graph as eventday_graph
from eventday import seed
from eventday.graph import graph_settings


def test_eventday_graph_settings_do_not_inherit_legacy_graph_endpoint(monkeypatch):
    monkeypatch.setenv("FALKORDB_HOST", "legacy-db")
    monkeypatch.setenv("FALKORDB_PORT", "6379")
    monkeypatch.delenv("RINGTRACE_EVENTDAY_FALKORDB_HOST", raising=False)
    monkeypatch.delenv("RINGTRACE_EVENTDAY_FALKORDB_PORT", raising=False)
    monkeypatch.delenv("RINGTRACE_EVENTDAY_GRAPH", raising=False)
    host, port, graph_name, _, _ = graph_settings()
    assert (host, port, graph_name) == ("127.0.0.1", 6380, "ringtrace_eventday")


@pytest.mark.parametrize(
    ("host", "port", "graph_name", "message"),
    [
        ("127.0.0.1", "6379", "ringtrace_eventday_test", "port 6379"),
        ("127.0.0.1", "6380", "legacy_shared_graph", "graph name"),
        ("127.0.0.1", "6380", "ringtrace_eventdayevil", "graph name"),
        ("shared-graph.example", "6380", "ringtrace_eventday_test", "loopback"),
    ],
)
def test_eventday_graph_client_rejects_unsafe_target_before_connecting(
    monkeypatch, host, port, graph_name, message
):
    monkeypatch.setenv("RINGTRACE_EVENTDAY_FALKORDB_HOST", host)
    monkeypatch.setenv("RINGTRACE_EVENTDAY_FALKORDB_PORT", port)
    monkeypatch.setenv("RINGTRACE_EVENTDAY_GRAPH", graph_name)
    monkeypatch.setattr(eventday_graph, "_graph_cache", {})
    monkeypatch.setattr(
        eventday_graph,
        "FalkorDB",
        lambda **_: pytest.fail("unsafe target must be rejected before client construction"),
    )

    with pytest.raises(RuntimeError, match=message):
        eventday_graph.get_event_graph()


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


def test_seed_refuses_non_loopback_host_even_with_disposable_opt_in(monkeypatch):
    monkeypatch.setenv("RINGTRACE_EVENTDAY_ENABLED", "1")
    monkeypatch.setenv("RINGTRACE_EVENTDAY_DISPOSABLE", "1")
    monkeypatch.setenv("RINGTRACE_EVENTDAY_FALKORDB_HOST", "shared-graph.example")
    monkeypatch.setenv("RINGTRACE_EVENTDAY_FALKORDB_PORT", "6380")
    monkeypatch.setenv("RINGTRACE_EVENTDAY_GRAPH", "ringtrace_eventday_test")
    with pytest.raises(RuntimeError, match="non-loopback"):
        seed.seed_eventday_graph()


def test_seed_refuses_port_6379_even_with_disposable_opt_in(monkeypatch):
    monkeypatch.setenv("RINGTRACE_EVENTDAY_ENABLED", "1")
    monkeypatch.setenv("RINGTRACE_EVENTDAY_DISPOSABLE", "1")
    monkeypatch.setenv("RINGTRACE_EVENTDAY_FALKORDB_PORT", "6379")
    monkeypatch.setenv("RINGTRACE_EVENTDAY_GRAPH", "ringtrace_eventday_test")
    with pytest.raises(RuntimeError, match="Refusing to seed port 6379"):
        seed.seed_eventday_graph()
