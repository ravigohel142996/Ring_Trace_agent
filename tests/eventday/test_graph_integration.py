"""Opt-in real FalkorDB test for the isolated event-day synthetic fixture.

Run only against a disposable FalkorDB endpoint on a non-6379 port. This test
never contacts the pre-existing RingTrace preview/graph configuration.
"""
from __future__ import annotations

import os

import pytest

from eventday.engine import CorridorInvestigator
from eventday.graph import CorridorGraph, get_event_graph, graph_settings
from eventday.seed import seed_eventday_graph


pytestmark = pytest.mark.skipif(
    os.getenv("RINGTRACE_TEST_DISPOSABLE") != "1",
    reason="set RINGTRACE_TEST_DISPOSABLE=1 only for an isolated throwaway FalkorDB instance",
)


def _assert_disposable_target() -> None:
    host, port, graph_name, _, _ = graph_settings()
    if host not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("Integration tests are restricted to a loopback disposable FalkorDB host.")
    if port == 6379:
        pytest.fail("Integration tests refuse port 6379; use a separately published port such as 6380.")
    if not graph_name.startswith("ringtrace_eventday"):
        pytest.fail("Integration tests require a graph name prefixed ringtrace_eventday.")
    if os.getenv("RINGTRACE_EVENTDAY_ENABLED") != "1" or os.getenv("RINGTRACE_EVENTDAY_DISPOSABLE") != "1":
        pytest.fail("Set both event-day enable/disposable flags for this explicitly isolated test.")


def test_seeded_payment_event_has_time_ordered_payout_corridor():
    _assert_disposable_target()
    seed_eventday_graph()
    graph = CorridorGraph(get_event_graph())
    result = CorridorInvestigator(graph).investigate("PAY-ALERT-1001", window_minutes=60, max_hops=4)

    assert result["payment"]["occurred_at"] == result["window_start_ts"]
    assert result["paths"], "FalkorDB returned no time-respecting synthetic corridor for the planted alert case."
    assert any(path["payout_id"] == "PAYOUT-EXT-01" for path in result["paths"])
    assert all(
        transfer["occurred_at"] > result["window_start_ts"]
        for path in result["paths"]
        for transfer in path["transfers"]
    )


def test_out_of_window_payment_has_no_downstream_path():
    _assert_disposable_target()
    seed_eventday_graph()
    from eventday.graph import get_event_graph

    graph = CorridorGraph(get_event_graph())
    result = CorridorInvestigator(graph).investigate("PAY-BENIGN-2001", window_minutes=60, max_hops=4)

    assert result["status"] in {"complete", "partial"}
    assert result["paths"] == []
