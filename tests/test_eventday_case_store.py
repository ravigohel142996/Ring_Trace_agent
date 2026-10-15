"""One-time human gate transitions for simulated event-day graph writes."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from eventday import api as eventday_api
from fastapi import HTTPException

from eventday.api import (
    CorridorCaseError,
    CorridorCaseStore,
    CorridorInvestigationRequest,
    corridor_graph_health,
    investigate_corridor,
)


def test_case_write_requires_evidence_eligible_result_and_same_analyst():
    store = CorridorCaseStore()
    case = store.create({"can_propose_review": False})
    with pytest.raises(CorridorCaseError, match="does not support"):
        store.approve(case["case_id"], "analyst-a", 300)

    eligible = store.create({"can_propose_review": True})
    store.approve(eligible["case_id"], "analyst-a", 300)
    with pytest.raises(CorridorCaseError, match="approving analyst"):
        store.begin_execution(eligible["case_id"], "analyst-b", confirmed=True)
    with pytest.raises(CorridorCaseError, match="Explicit confirmation"):
        store.begin_execution(eligible["case_id"], "analyst-a", confirmed=False)

    store.begin_execution(eligible["case_id"], "analyst-a", confirmed=True)
    complete = store.complete(eligible["case_id"], {
        "proposal_id": "REVIEW-1", "graph_write_status": "written", "evidence_count": 2,
    })
    assert complete["status"] == "executed"
    with pytest.raises(CorridorCaseError, match="already been made"):
        store.begin_execution(eligible["case_id"], "analyst-a", confirmed=True)


def test_disabled_health_probe_does_not_open_any_graph_connection(monkeypatch):
    monkeypatch.setenv("RINGTRACE_EVENTDAY_ENABLED", "0")
    monkeypatch.setattr(eventday_api, "get_event_graph", lambda: (_ for _ in ()).throw(AssertionError("graph touched")))
    result = corridor_graph_health()
    assert result["enabled"] is False
    assert result["connected"] is False
    assert result["port"] == 6380


def test_disabled_eventday_route_does_not_open_any_graph_connection(monkeypatch):
    monkeypatch.setenv("RINGTRACE_EVENTDAY_ENABLED", "0")
    monkeypatch.setattr(eventday_api, "get_event_graph", lambda: (_ for _ in ()).throw(AssertionError("graph touched")))
    with pytest.raises(HTTPException) as error:
        investigate_corridor(CorridorInvestigationRequest(payment_event_id="PAY-ALERT-1001"))
    assert error.value.status_code == 503


def test_approval_expiry_blocks_graph_write(monkeypatch):
    now = datetime(2026, 10, 15, tzinfo=timezone.utc)
    monkeypatch.setattr(eventday_api, "_utc_now", lambda: now)
    store = CorridorCaseStore()
    case = store.create({"can_propose_review": True})
    store.approve(case["case_id"], "analyst-a", 10)
    monkeypatch.setattr(eventday_api, "_utc_now", lambda: now + timedelta(seconds=11))
    with pytest.raises(CorridorCaseError, match="expired"):
        store.begin_execution(case["case_id"], "analyst-a", confirmed=True)
    assert store.get(case["case_id"])["status"] == "approval_expired"
