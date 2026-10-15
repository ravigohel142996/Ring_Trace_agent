"""HTTP surface for the event-day temporal-corridor agent.

Investigation requests are graph-read-only. A proposed review is written only
through an authenticated, short-lived approval plus explicit confirmation, and
only for synthetic PaymentEvent nodes in the dedicated event-day dataset.
"""
from __future__ import annotations

import json
import os
import threading
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, StrictBool

from api.auth import AuthenticatedAnalyst, get_demo_auth_config, require_action_analyst
from eventday.engine import CorridorInvestigator
from eventday.graph import CorridorGraph, get_event_graph, graph_settings

router = APIRouter(prefix="/api/eventday", tags=["event-day corridor investigator"])

DATASET_ID = os.getenv("RINGTRACE_EVENTDAY_DATASET", "ringtrace_eventday_synthetic_v1")
APPROVAL_TTL_SECONDS = 300

SCENARIOS = [
    {"payment_event_id": "PAY-ALERT-1001", "title": "Fast multi-hop corridor", "label": "Synthetic"},
    {"payment_event_id": "PAY-BENIGN-2001", "title": "Low-value household transfer", "label": "Synthetic"},
    {"payment_event_id": "PAY-AMBIG-3001", "title": "Shared-device lookalike", "label": "Synthetic"},
]


class CorridorInvestigationRequest(BaseModel):
    payment_event_id: str = Field(pattern=r"^[A-Z0-9-]{4,48}$")
    window_minutes: int = Field(default=60, ge=1, le=1440)
    max_hops: int = Field(default=4, ge=1, le=6)


class CorridorExecutionRequest(BaseModel):
    confirmed: StrictBool


class CorridorCaseError(RuntimeError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


class CorridorCaseStore:
    """Short-lived session state; the confirmed review/evidence is graph-backed."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._cases: dict[str, dict[str, Any]] = {}

    def create(self, result: dict[str, Any]) -> dict[str, Any]:
        case_id = f"COR-{uuid4().hex[:12].upper()}"
        case = {
            "case_id": case_id,
            "run_id": f"RUN-{uuid4().hex.upper()}",
            "created_at": _iso(_utc_now()),
            "status": "investigated",
            "result": deepcopy(result),
            "approval": None,
            "execution_attempted": False,
            "proposal": None,
        }
        with self._lock:
            self._cases[case_id] = case
            return deepcopy(case)

    def get(self, case_id: str) -> dict[str, Any] | None:
        with self._lock:
            case = self._cases.get(case_id)
            return deepcopy(case) if case is not None else None

    def approve(self, case_id: str, analyst: str, ttl_seconds: int) -> dict[str, Any]:
        with self._lock:
            case = self._require(case_id)
            if case["status"] not in {"investigated", "approval_expired"}:
                raise CorridorCaseError(f"Cannot approve a corridor case in '{case['status']}' state.")
            if not case["result"].get("can_propose_review"):
                raise CorridorCaseError("This graph result does not support a simulated review proposal.")
            approved_at = _utc_now()
            approval = {
                "approved_by": analyst,
                "approved_at": _iso(approved_at),
                "expires_at": _iso(approved_at + timedelta(seconds=ttl_seconds)),
                "action": "CREATE_SIMULATED_REVIEW_PROPOSAL",
            }
            case["approval"] = approval
            case["status"] = "approved"
            return deepcopy(case)

    def begin_execution(self, case_id: str, analyst: str, confirmed: bool) -> dict[str, Any]:
        with self._lock:
            case = self._require(case_id)
            if case["execution_attempted"] or case["status"] in {"executing", "executed", "action_failed"}:
                raise CorridorCaseError("A write attempt has already been made for this case.")
            approval = case.get("approval") or {}
            if case["status"] != "approved":
                raise CorridorCaseError("Approve the simulated review proposal first.")
            if approval.get("approved_by") != analyst:
                raise CorridorCaseError("The approving analyst must execute this proposal.")
            try:
                if datetime.fromisoformat(approval["expires_at"]) <= _utc_now():
                    case["status"] = "approval_expired"
                    raise CorridorCaseError("Approval expired; approve the proposal again.")
            except (KeyError, TypeError, ValueError):
                raise CorridorCaseError("Approval is invalid; approve the proposal again.") from None
            if confirmed is not True:
                raise CorridorCaseError("Explicit confirmation is required before graph write-back.")
            case["execution_attempted"] = True
            case["status"] = "executing"
            case["executed_by"] = analyst
            case["execution_started_at"] = _iso(_utc_now())
            return deepcopy(case)

    def complete(self, case_id: str, proposal: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            case = self._require(case_id)
            if case["status"] != "executing" or not case["execution_attempted"]:
                raise CorridorCaseError("No active one-time execution attempt exists.")
            if proposal.get("graph_write_status") != "written" or not proposal.get("proposal_id"):
                raise CorridorCaseError("The expected FalkorDB review write was not verified.")
            case["status"] = "executed"
            case["proposal"] = deepcopy(proposal)
            case["executed_at"] = _iso(_utc_now())
            return deepcopy(case)

    def fail(self, case_id: str, error: str) -> dict[str, Any]:
        with self._lock:
            case = self._require(case_id)
            case["status"] = "action_failed"
            case["failure"] = error
            return deepcopy(case)

    def _require(self, case_id: str) -> dict[str, Any]:
        case = self._cases.get(case_id)
        if case is None:
            raise CorridorCaseError("Corridor investigation was not found in this API session.")
        return case


cases = CorridorCaseStore()


@router.get("/health")
def corridor_graph_health() -> dict[str, Any]:
    host, port, graph_name, _, _, _ = graph_settings()
    if os.getenv("RINGTRACE_EVENTDAY_ENABLED") != "1":
        return {"enabled": False, "connected": False, "host": host, "port": port,
                "graph": graph_name, "error": "Event-day graph is disabled."}
    try:
        result = get_event_graph().query("RETURN 1 AS ok")
        connected = bool(result.result_set and result.result_set[0] and result.result_set[0][0] == 1)
        return {"enabled": True, "connected": connected, "host": host, "port": port,
                "graph": graph_name, "error": None if connected else "FalkorDB did not return the health sentinel."}
    except Exception as exc:
        return {"enabled": True, "connected": False, "host": host, "port": port,
                "graph": graph_name, "error": str(exc)[:300]}


@router.get("/scenarios")
def list_corridor_scenarios() -> dict[str, Any]:
    """Return fixture identifiers only; results are always read from FalkorDB."""
    return {"dataset_id": DATASET_ID, "scenarios": SCENARIOS}


@router.post("/investigations")
def investigate_corridor(payload: CorridorInvestigationRequest) -> dict[str, Any]:
    if os.getenv("RINGTRACE_EVENTDAY_ENABLED") != "1":
        raise HTTPException(status_code=503, detail="Event-day graph is disabled; configure its dedicated FalkorDB endpoint to enable it.")
    try:
        graph = CorridorGraph(get_event_graph(), dataset_id=DATASET_ID)
        result = CorridorInvestigator(graph).investigate(
            payload.payment_event_id,
            window_minutes=payload.window_minutes,
            max_hops=payload.max_hops,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Event-day FalkorDB graph unavailable: {exc}") from exc
    if result["status"] == "not_found":
        raise HTTPException(status_code=404, detail="Payment event not found in the selected synthetic dataset.")
    if result["status"] == "incomplete" and "inspect_payment_event" in result.get("failed_queries", []):
        raise HTTPException(status_code=503, detail=result["decision"])
    case = cases.create(result)
    return {"case_id": case["case_id"], "status": case["status"], "investigation": result}


@router.get("/investigations/{case_id}")
def get_corridor_case(case_id: str) -> dict[str, Any]:
    case = cases.get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Corridor investigation not found in this API session.")
    return case


@router.post("/investigations/{case_id}/approve")
def approve_corridor_review(
    case_id: str,
    analyst: AuthenticatedAnalyst = Depends(require_action_analyst),
) -> dict[str, Any]:
    config = get_demo_auth_config()
    if config is None:
        raise HTTPException(status_code=503, detail="Demo analyst authentication is not configured.")
    try:
        case = cases.approve(case_id, analyst.username, config.approval_ttl_seconds)
    except CorridorCaseError as exc:
        status = 404 if cases.get(case_id) is None else 409
        raise HTTPException(status_code=status, detail=str(exc)) from None
    return {
        "case_id": case_id,
        "status": case["status"],
        "approval": case["approval"],
        "simulated": True,
    }


@router.post("/investigations/{case_id}/execute")
def execute_corridor_review(
    case_id: str,
    payload: CorridorExecutionRequest,
    analyst: AuthenticatedAnalyst = Depends(require_action_analyst),
) -> dict[str, Any]:
    try:
        case = cases.begin_execution(case_id, analyst.username, payload.confirmed)
    except CorridorCaseError as exc:
        status = 404 if cases.get(case_id) is None else 409
        raise HTTPException(status_code=status, detail=str(exc)) from None

    try:
        result = case["result"]
        evidence_rows: list[dict[str, Any]] = []
        evidence_index = 0
        for step in result.get("steps", []):
            for evidence in step.get("evidence", []):
                if not evidence.get("cypher"):
                    continue
                evidence_index += 1
                evidence_rows.append({
                    "id": f"{case['run_id']}-E{evidence_index:03d}",
                    "query_name": str(evidence.get("query_name", step.get("tool", "unknown"))),
                    "cypher": str(evidence["cypher"]),
                    "params_json": json.dumps(evidence.get("params", {}), sort_keys=True),
                    "row_count": int(evidence["row_count"]) if isinstance(evidence.get("row_count"), int) else -1,
                    "summary": str(step.get("summary", "Graph evidence captured.")),
                })
        if not evidence_rows:
            raise RuntimeError("No successful Cypher evidence is available to support a review proposal.")

        graph = CorridorGraph(get_event_graph(), dataset_id=DATASET_ID)
        approval = case["approval"]
        write = graph.record_review_proposal(
            payment_event_id=result["payment_event_id"],
            run_id=case["run_id"],
            proposal_id=f"REVIEW-{uuid4().hex.upper()}",
            created_by=analyst.username,
            approved_at=approval["approved_at"],
            approval_expires_at=approval["expires_at"],
            decision=result["decision"],
            review_signal_score=float(result["review_signal_score"]),
            evidence_rows=evidence_rows,
        )
        if not write.rows or not isinstance(write.rows[0], (tuple, list)) or len(write.rows[0]) < 3:
            raise RuntimeError("FalkorDB did not confirm the expected proposal/evidence write.")
        row = write.rows[0]
        if row[0] != case["run_id"] or int(row[2]) != len(evidence_rows):
            raise RuntimeError("FalkorDB write verification did not match this run and evidence count.")
        proposal = {
            "proposal_id": row[1],
            "run_id": row[0],
            "evidence_count": int(row[2]),
            "graph_write_status": "written",
            "action": "CREATE_SIMULATED_REVIEW_PROPOSAL",
            "simulated": True,
        }
        complete = cases.complete(case_id, proposal)
    except Exception as exc:
        cases.fail(case_id, str(exc))
        raise HTTPException(status_code=502, detail=f"Review proposal failed; inspect the event-day graph before any manual retry: {exc}") from exc

    return {
        "case_id": case_id,
        "status": complete["status"],
        "proposal": complete["proposal"],
        "approved_by": complete["approval"]["approved_by"],
        "executed_by": complete["executed_by"],
        "executed_at": complete["executed_at"],
        "simulated": True,
    }
