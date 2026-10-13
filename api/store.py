"""Thread-safe in-process investigation index and action state machine.

The graph remains the system of record for graph evidence and completed action
writes. This index binds a short-lived approval to one case, one recommended
action, and one authenticated analyst; execution attempts are single-use.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Any
from uuid import uuid4


class CaseNotFound(KeyError):
    pass


class InvalidCaseTransition(RuntimeError):
    pass


class AnalystMismatch(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _recommended_action(case: dict[str, Any]) -> str:
    verdict = case.get("result", {}).get("verdict", {})
    action = verdict.get("recommended_action") if isinstance(verdict, dict) else None
    return str(action or "NO_ACTION_REQUIRED")


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
            "approval_history": [],
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

    def approve(self, case_id: str, *, approved_by: str, approval_ttl_seconds: int) -> dict[str, Any]:
        with self._lock:
            case = self._require(case_id)
            if case["status"] not in {"investigated", "approval_expired"}:
                raise InvalidCaseTransition(f"Cannot approve a case in '{case['status']}' state.")
            approved_at = utc_now()
            expires_at = (_parse_utc(approved_at) + timedelta(seconds=approval_ttl_seconds)).isoformat()
            action_type = _recommended_action(case)
            approval = {
                "case_id": case_id,
                "action_type": action_type,
                "approved_by": approved_by,
                "approved_at": approved_at,
                "expires_at": expires_at,
                "policy_seconds": approval_ttl_seconds,
            }
            case["status"] = "approved"
            case["approval"] = approval
            case.setdefault("approval_history", []).append(deepcopy(approval))
            case["action"] = None
            return deepcopy(case)

    def begin_execution(self, case_id: str, *, analyst: str, confirmed: bool) -> dict[str, Any]:
        with self._lock:
            case = self._require(case_id)
            if case["execution_attempted"] or case["status"] in {"executing", "executed", "action_failed"}:
                raise InvalidCaseTransition("Action execution has already been attempted for this case.")
            if case["status"] != "approved" or not isinstance(case.get("approval"), dict):
                raise InvalidCaseTransition("Approve the simulated action before executing it.")

            approval = case["approval"]
            action_type = _recommended_action(case)
            if approval.get("case_id") != case_id or approval.get("action_type") != action_type:
                raise InvalidCaseTransition("The approval does not match this case and recommended action.")
            now = utc_now()
            try:
                expired = _parse_utc(approval["expires_at"]) <= _parse_utc(now)
            except (KeyError, TypeError, ValueError):
                raise InvalidCaseTransition("The case approval is invalid and must be renewed.") from None
            if expired:
                case["status"] = "approval_expired"
                approval["expired_at"] = now
                raise InvalidCaseTransition("This approval has expired. Approve the action again before executing it.")
            if approval.get("approved_by") != analyst:
                raise AnalystMismatch("The same authenticated analyst who approved this action must execute it.")
            if not confirmed:
                raise InvalidCaseTransition("Explicitly confirm the simulated action before executing it.")

            case["execution_attempted"] = True
            case["status"] = "executing"
            case["action"] = {
                "status": "executing",
                "started_at": now,
                "approved_by": approval["approved_by"],
                "approved_at": approval["approved_at"],
                "execution_actor": analyst,
                "action_type": action_type,
                "simulated": True,
            }
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
            if case["status"] != "executing" or not case.get("execution_attempted"):
                raise InvalidCaseTransition("No active one-time execution attempt exists for this case.")
            if not graph_case_id or graph_write_status != "written":
                raise InvalidCaseTransition("The graph write was not verified; execution cannot be reported as successful.")
            executed_at = utc_now()
            action = case.get("action") or {}
            case["status"] = "executed"
            case["graph_case_id"] = graph_case_id
            case["action"] = {
                **action,
                "status": "executed",
                "executed_at": executed_at,
                "results": deepcopy(results),
                "graph_case_id": graph_case_id,
                "graph_write_status": graph_write_status,
                "simulated": True,
            }
            return deepcopy(case)

    def fail_execution(self, case_id: str, error: str) -> dict[str, Any]:
        with self._lock:
            case = self._require(case_id)
            failed_at = utc_now()
            previous_action = case.get("action") or {}
            case["status"] = "action_failed"
            case["action"] = {
                **previous_action,
                "status": "failed",
                "failed_at": failed_at,
                "error": error,
                "graph_write_status": "unknown",
                "simulated": True,
            }
            return deepcopy(case)

    def _require(self, case_id: str) -> dict[str, Any]:
        case = self._cases.get(case_id)
        if case is None:
            raise CaseNotFound(case_id)
        return case
