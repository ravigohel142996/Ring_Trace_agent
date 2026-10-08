"""Thread-safe in-process investigation index.

The graph remains the system of record for graph evidence and executed action
writes. This small index keeps an investigator's active API session browsable
while exposing durable graph case records separately through GraphStore.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from typing import Any
from uuid import uuid4


class CaseNotFound(KeyError):
    pass


class InvalidCaseTransition(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class InvestigationStore:
    """Process-local index with guarded approval/execution transitions."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._cases: dict[str, dict[str, Any]] = {}

    def create(self, account_id: str, result: dict[str, Any]) -> dict[str, Any]:
        case_id = f"RT-{uuid4().hex[:12].upper()}"
        case = {
            "case_id": case_id,
            "account_id": account_id,
            "created_at": utc_now(),
            "status": "investigated",
            "result": deepcopy(result),
            "approval": None,
            "action": None,
            "graph_case_id": None,
            "execution_attempted": False,
        }
        with self._lock:
            self._cases[case_id] = case
            return deepcopy(case)

    def get(self, case_id: str) -> dict[str, Any] | None:
        with self._lock:
            case = self._cases.get(case_id)
            return deepcopy(case) if case is not None else None

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            cases = list(self._cases.values())
            cases.sort(key=lambda item: item["created_at"], reverse=True)
            return deepcopy(cases)

    def approve(self, case_id: str) -> dict[str, Any]:
        with self._lock:
            case = self._require(case_id)
            if case["status"] != "investigated":
                raise InvalidCaseTransition(f"Cannot approve a case in '{case['status']}' state.")
            approved_at = utc_now()
            case["status"] = "approved"
            case["approval"] = {"approved_at": approved_at, "approved_by": "investigator"}
            return deepcopy(case)

    def begin_execution(self, case_id: str) -> dict[str, Any]:
        with self._lock:
            case = self._require(case_id)
            if case["execution_attempted"] or case["status"] in {"executing", "executed", "action_failed"}:
                raise InvalidCaseTransition("Action execution has already been attempted for this case.")
            if case["status"] != "approved":
                raise InvalidCaseTransition("Approve the simulated action before executing it.")
            case["execution_attempted"] = True
            case["status"] = "executing"
            case["action"] = {"status": "executing", "started_at": utc_now(), "simulated": True}
            return deepcopy(case)

    def complete_execution(
        self,
        case_id: str,
        *,
        results: list[dict[str, Any]],
        graph_case_id: str | None,
        graph_write_status: str,
    ) -> dict[str, Any]:
        with self._lock:
            case = self._require(case_id)
            executed_at = utc_now()
            case["status"] = "executed"
            case["graph_case_id"] = graph_case_id
            case["action"] = {
                "status": "executed",
                "executed_at": executed_at,
                "results": deepcopy(results),
                "graph_write_status": graph_write_status,
                "simulated": True,
            }
            return deepcopy(case)

    def fail_execution(self, case_id: str, error: str) -> dict[str, Any]:
        with self._lock:
            case = self._require(case_id)
            failed_at = utc_now()
            case["status"] = "action_failed"
            case["action"] = {
                "status": "failed",
                "executed_at": failed_at,
                "error": error,
                "graph_write_status": "unknown; inspect graph evidence before retrying",
                "simulated": True,
            }
            return deepcopy(case)

    def _require(self, case_id: str) -> dict[str, Any]:
        case = self._cases.get(case_id)
        if case is None:
            raise CaseNotFound(case_id)
        return case
