"""FastAPI application for the RingTrace investigation engine.

All investigation and decision results are produced by the existing agent,
tools, risk scorer, and FalkorDB graph layer. The API never substitutes
fixture results when the graph is unavailable.
"""
from __future__ import annotations

import hmac
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import FileResponse, JSONResponse

from agent.decision import execute_recommended_action
from agent.investigator import Investigator, extract_account_id
from api.auth import (
    AuthSessionRegistry,
    AuthenticatedAnalyst,
    SESSION_COOKIE_NAME,
    clear_session_cookie,
    credentials_match,
    get_demo_auth_config,
    issue_session,
    read_session,
    reject_cross_site_fetch,
    require_action_analyst,
    set_session_cookie,
)
from api.graph_export import build_graph_export
from api.schemas import (
    ActionApprovalResponse,
    ActionExecutionRequest,
    ActionExecutionResponse,
    AnalystLoginRequest,
    AnalystSessionResponse,
    HealthResponse,
    InvestigationRequest,
    InvestigationSummary,
    Scenario,
)
from api.store import AnalystMismatch, CaseNotFound, InvestigationStore, InvalidCaseTransition
from graph.connection import get_graph, health_check
from graph.queries import GraphStore
from models.risk_scorer import RiskScorer
from tools.context import ToolContext

logger = logging.getLogger("ringtrace.api")
app = FastAPI(
    title="RingTrace API",
    description="Graph-backed fraud-ring investigation and simulated action API.",
    version="1.0.0",
)
app.state.investigations = InvestigationStore()
app.state.auth_sessions = AuthSessionRegistry()
FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(request: Request, exc: RequestValidationError):
    # Pydantic's default 422 body includes the invalid `input`; on the login
    # route that can echo a submitted password. Keep auth errors generic.
    if request.url.path == "/api/auth/login":
        return JSONResponse(
            status_code=422,
            content={"detail": "Invalid login request."},
            headers={"Cache-Control": "no-store"},
        )
    return await request_validation_exception_handler(request, exc)


SCENARIOS: tuple[dict[str, str], ...] = (
    {"id": "CASE-A", "account_id": "A1100", "title": "Isolated account", "description": "Clean reference account with no shared identity or money-flow links.", "risk_focus": "LOW / no action"},
    {"id": "CASE-B", "account_id": "A1200", "title": "Identity-linked only", "description": "Shared identity links without a corroborating money trail.", "risk_focus": "HIGH / manual review"},
    {"id": "CASE-C", "account_id": "A1027", "title": "Ring with money flow", "description": "Connected fraud-ring reference case with PageRank and multi-hop money movement.", "risk_focus": "CRITICAL / escalation"},
    {"id": "DEMO-01", "account_id": "A1300", "title": "Clean isolated account", "description": "Sanity check for an isolated low-risk account.", "risk_focus": "LOW"},
    {"id": "DEMO-02", "account_id": "A1310", "title": "Benign shared device", "description": "Household-style shared device with no money movement.", "risk_focus": "Benign look-alike"},
    {"id": "DEMO-03", "account_id": "A1320", "title": "Reciprocal wash-trading ring", "description": "Dense reciprocal transfers without shared identity.", "risk_focus": "Reciprocal-flow signal"},
    {"id": "DEMO-04", "account_id": "A1330", "title": "Layered movement", "description": "Multi-hop movement ending in broker cash-out and merchant spend.", "risk_focus": "Layering and cash-out"},
    {"id": "DEMO-05", "account_id": "A1340", "title": "Shared merchant look-alike", "description": "Unrelated accounts using the same popular merchant.", "risk_focus": "Avoid false positive"},
    {"id": "DEMO-06", "account_id": "A1350", "title": "Ambiguous low-volume links", "description": "One shared device and one small transfer.", "risk_focus": "Calibrated uncertainty"},
)
SCENARIO_BY_ID = {scenario["id"]: scenario for scenario in SCENARIOS}


def get_store(request: Request) -> InvestigationStore:
    return request.app.state.investigations


def _graph_health() -> dict[str, Any]:
    return health_check(retries=0)


def _serialize_result(result: Any) -> dict[str, Any]:
    data = asdict(result)
    return _json_safe(data)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item") and callable(value.item):
        try:
            return value.item()
        except (ValueError, TypeError):
            pass
    if isinstance(value, Path):
        return str(value)
    return value


def _find_case_or_404(store: InvestigationStore, case_id: str) -> dict[str, Any]:
    case = store.get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"Investigation case '{case_id}' was not found.")
    return case


def _case_summary(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "account_id": case["account_id"],
        "created_at": case["created_at"],
        "status": case["status"],
        "result": case["result"],
        "approval": case.get("approval"),
        "approval_history": case.get("approval_history", []),
        "action": case.get("action"),
        "graph_case_id": case.get("graph_case_id"),
    }


def _graph_created_at(value: Any) -> str:
    """Convert FalkorDB's millisecond timestamp into a browser-safe ISO date."""
    if value is None:
        return ""
    try:
        numeric = float(value)
        seconds = numeric / 1000 if abs(numeric) >= 100_000_000_000 else numeric
        return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return str(value)


def _graph_case_summary(graph_case: dict[str, Any]) -> dict[str, Any]:
    """Expose persisted action cases without fabricating a lost agent trace."""
    case_id = str(graph_case["id"])
    account_id = str(graph_case.get("account_id") or "")
    raw_score = graph_case.get("risk_score")
    raw_confidence = graph_case.get("confidence")
    try:
        risk_score = float(raw_score) if raw_score is not None else None
    except (TypeError, ValueError):
        risk_score = None
    try:
        confidence = float(raw_confidence) if raw_confidence is not None else None
    except (TypeError, ValueError):
        confidence = None
    verdict = {
        "account_id": account_id,
        "verdict": str(graph_case.get("verdict") or "Stored graph case"),
        "risk_score": risk_score,
        "confidence": confidence,
        "recommended_action": str(graph_case.get("recommended_action") or ""),
        "reasoning": [],
    }
    approval = None
    if graph_case.get("approved_by") and graph_case.get("approved_at"):
        approval = {
            "case_id": graph_case.get("api_case_id") or case_id,
            "action_type": graph_case.get("action_type") or verdict["recommended_action"],
            "approved_by": graph_case.get("approved_by"),
            "approved_at": graph_case.get("approved_at"),
            "expires_at": graph_case.get("approval_expires_at"),
        }
    action = None
    if graph_case.get("action_type") or graph_case.get("execution_actor"):
        action_outcome = graph_case.get("action_outcome")
        graph_write_status = graph_case.get("graph_write_status")
        if action_outcome == "succeeded" and graph_write_status == "written":
            action_status = "executed"
        elif action_outcome == "failed":
            action_status = "failed"
        else:
            action_status = "pending"
        action = {
            "status": action_status,
            "action_type": graph_case.get("action_type"),
            "approved_by": graph_case.get("approved_by"),
            "approved_at": graph_case.get("approved_at"),
            "execution_actor": graph_case.get("execution_actor"),
            "execution_started_at": graph_case.get("execution_started_at"),
            "executed_at": graph_case.get("executed_at"),
            "graph_case_id": case_id,
            "graph_write_status": graph_write_status or "unknown",
            "error": graph_case.get("action_error"),
            "simulated": True,
        }
    return {
        "case_id": case_id,
        "account_id": account_id,
        "created_at": _graph_created_at(graph_case.get("created_at")),
        "status": str(graph_case.get("status") or "OPEN").lower(),
        "result": {
            "account_id": account_id,
            "mode": "durable_graph_record",
            "steps": [],
            "verdict": verdict,
            "narrative": graph_case.get("notes"),
        },
        "approval": approval,
        "action": action,
        "graph_case_id": case_id,
        "source": "FalkorDB",
        "read_only": True,
        "graph_record": graph_case,
    }


@app.get("/api/health", response_model=HealthResponse)
def api_health() -> dict[str, str]:
    return {"status": "ok", "service": "ringtrace-api"}


@app.get("/api/graph/health")
def graph_health() -> dict[str, Any]:
    try:
        result = _graph_health()
    except Exception as exc:  # the liveness endpoint must return a diagnostic, not crash
        logger.warning("Graph health probe failed: %s", exc)
        return {"connected": False, "host": "unknown", "port": "unknown", "graph": "ringtrace", "error": str(exc)}
    return result


@app.get("/api/scenarios", response_model=list[Scenario])
def scenarios() -> list[dict[str, str]]:
    return list(SCENARIOS)


@app.get("/api/auth/session", response_model=AnalystSessionResponse)
def analyst_session(request: Request, response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    config = get_demo_auth_config()
    if config is None:
        clear_session_cookie(response, request)
        return {"auth_enabled": False, "authenticated": False}
    session = read_session(
        request.cookies.get(SESSION_COOKIE_NAME), config, request.app.state.auth_sessions
    )
    if session is None:
        if request.cookies.get(SESSION_COOKIE_NAME):
            clear_session_cookie(response, request)
        return {"auth_enabled": True, "authenticated": False}
    return {
        "auth_enabled": True,
        "authenticated": True,
        "analyst": session.username,
        "csrf_token": session.csrf_token,
        "expires_at": session.expires_at_iso,
    }


@app.post("/api/auth/login", response_model=AnalystSessionResponse)
def analyst_login(
    payload: AnalystLoginRequest,
    request: Request,
    response: Response,
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    config = get_demo_auth_config()
    if config is None:
        raise HTTPException(status_code=503, detail="Demo analyst authentication is not configured.")
    reject_cross_site_fetch(request)
    if not credentials_match(payload.username, payload.password.get_secret_value(), config):
        raise HTTPException(status_code=401, detail="The configured analyst credentials were not accepted.")
    token, session = issue_session(payload.username, config, request.app.state.auth_sessions)
    set_session_cookie(response, request, token, config)
    return {
        "auth_enabled": True,
        "authenticated": True,
        "analyst": session.username,
        "csrf_token": session.csrf_token,
        "expires_at": session.expires_at_iso,
    }


@app.post("/api/auth/logout", response_model=AnalystSessionResponse)
def analyst_logout(
    request: Request,
    response: Response,
    x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    config = get_demo_auth_config()
    if config is not None:
        session = read_session(
            request.cookies.get(SESSION_COOKIE_NAME), config, request.app.state.auth_sessions
        )
        if session is not None:
            reject_cross_site_fetch(request)
            if not x_csrf_token or not hmac.compare_digest(session.csrf_token, x_csrf_token):
                raise HTTPException(status_code=403, detail="A valid same-origin CSRF token is required.")
            request.app.state.auth_sessions.revoke(session.session_id)
    clear_session_cookie(response, request)
    return {"auth_enabled": config is not None, "authenticated": False}


@app.post("/api/investigate", response_model=InvestigationSummary, status_code=201)
def investigate(
    payload: InvestigationRequest,
    store: InvestigationStore = Depends(get_store),
) -> dict[str, Any]:
    scenario = None
    if payload.scenario_id:
        scenario = SCENARIO_BY_ID.get(payload.scenario_id)
        if scenario is None:
            raise HTTPException(status_code=404, detail=f"Unknown scenario '{payload.scenario_id}'.")

    target = payload.account_id or (scenario["account_id"] if scenario else None) or extract_account_id(payload.query or "")
    if not target:
        raise HTTPException(status_code=422, detail="Provide an account_id, scenario_id, or query containing an account ID.")

    result = Investigator().investigate(account_id=target, query=payload.query or "")
    result_data = _serialize_result(result)
    if result.error:
        message = result.error
        if not result.graph_health.get("connected", False) or "unreachable" in message.lower():
            raise HTTPException(status_code=503, detail=message)
        raise HTTPException(status_code=422, detail=message)

    steps = result_data.get("steps") or []
    context_step = next((step for step in steps if step.get("tool") == "get_account_context"), None)
    if context_step and not context_step.get("ok"):
        if context_step.get("error") == "account_not_found":
            raise HTTPException(status_code=404, detail=f"Account '{target}' does not exist in the current FalkorDB graph.")
        raise HTTPException(status_code=422, detail=context_step.get("error") or context_step.get("summary"))
    if not result_data.get("verdict"):
        raise HTTPException(status_code=502, detail="The investigation engine returned no evidence-backed verdict.")

    case = store.create(account_id=result.account_id or target, result=result_data)
    return _case_summary(case)


@app.get("/api/cases")
def list_cases(store: InvestigationStore = Depends(get_store)) -> dict[str, Any]:
    cases_by_id = {case["case_id"]: _case_summary(case) for case in store.list()}
    graph_connected = False
    try:
        graph_health_result = _graph_health()
        graph_connected = bool(graph_health_result.get("connected"))
        if graph_connected:
            rows = GraphStore(get_graph()).list_cases().data
            for row in rows:
                graph_case = row[0] if row else None
                if not isinstance(graph_case, dict) or not graph_case.get("id"):
                    continue
                case_id = str(graph_case["id"])
                cases_by_id.setdefault(case_id, _graph_case_summary(graph_case))
    except Exception as exc:  # list in-memory sessions even when FalkorDB is down
        logger.info("Could not add durable graph cases to the API listing: %s", exc)
    cases = list(cases_by_id.values())
    cases.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return {"cases": cases, "total": len(cases), "graph_connected": graph_connected}


@app.get("/api/cases/{case_id}")
def get_case(case_id: str, store: InvestigationStore = Depends(get_store)) -> dict[str, Any]:
    case = store.get(case_id)
    if case is not None:
        return _case_summary(case)
    # Cases written by the existing action layer are durable in FalkorDB and
    # remain readable even if this process-local investigation index is gone.
    try:
        result = GraphStore(get_graph()).get_case(case_id)
    except Exception:
        result = None
    if result and result.data and isinstance(result.data[0][0], dict):
        return _graph_case_summary(result.data[0][0])
    raise HTTPException(status_code=404, detail=f"Case '{case_id}' was not found.")


@app.get("/api/investigation/{case_id}")
def get_investigation(case_id: str, store: InvestigationStore = Depends(get_store)) -> dict[str, Any]:
    return _case_summary(_find_case_or_404(store, case_id))


@app.get("/api/investigation/{case_id}/graph")
def get_investigation_graph(case_id: str, store: InvestigationStore = Depends(get_store)) -> dict[str, Any]:
    case = _find_case_or_404(store, case_id)
    return build_graph_export(case["account_id"], case["result"].get("steps") or [])


@app.get("/api/investigation/{case_id}/evidence")
def get_investigation_evidence(case_id: str, store: InvestigationStore = Depends(get_store)) -> dict[str, Any]:
    case = _find_case_or_404(store, case_id)
    evidence = []
    for step in case["result"].get("steps") or []:
        for item in step.get("evidence") or []:
            evidence.append({"tool": step.get("tool"), "summary": step.get("summary"), **item})
    if case.get("action"):
        for step in case["action"].get("results") or []:
            for item in step.get("evidence") or []:
                evidence.append({"tool": step.get("tool"), "summary": step.get("summary"), **item})
    return {"case_id": case_id, "evidence": evidence, "total": len(evidence)}


@app.get("/api/investigation/{case_id}/trace")
def get_investigation_trace(case_id: str, store: InvestigationStore = Depends(get_store)) -> dict[str, Any]:
    case = _find_case_or_404(store, case_id)
    steps = case["result"].get("steps") or []
    if case.get("action"):
        steps = [*steps, *(case["action"].get("results") or [])]
    return {"case_id": case_id, "mode": case["result"].get("mode"), "steps": steps, "total": len(steps)}


@app.get("/api/investigation/{case_id}/risk")
def get_investigation_risk(case_id: str, store: InvestigationStore = Depends(get_store)) -> dict[str, Any]:
    case = _find_case_or_404(store, case_id)
    result = case["result"]
    risk_step = next((step for step in reversed(result.get("steps") or []) if step.get("tool") == "calculate_risk_score" and step.get("ok")), None)
    verdict = result.get("verdict") or {}
    return {"case_id": case_id, "risk": (risk_step or {}).get("data", {}), "risk_score": verdict.get("risk_score"), "risk_class": verdict.get("risk_class"), "method": verdict.get("risk_method"), "evaluation_data": "Synthetic evaluation data"}


@app.get("/api/investigation/{case_id}/decision")
def get_investigation_decision(case_id: str, store: InvestigationStore = Depends(get_store)) -> dict[str, Any]:
    case = _find_case_or_404(store, case_id)
    return {"case_id": case_id, "decision": case["result"].get("verdict") or {}}


@app.post("/api/actions/{case_id}/approve", response_model=ActionApprovalResponse)
def approve_action(
    case_id: str,
    analyst: AuthenticatedAnalyst = Depends(require_action_analyst),
    store: InvestigationStore = Depends(get_store),
) -> dict[str, Any]:
    config = get_demo_auth_config()
    if config is None:  # fail closed if environment configuration changed mid-request
        raise HTTPException(status_code=503, detail="Demo analyst authentication is not configured.")
    try:
        case = store.approve(
            case_id,
            approved_by=analyst.username,
            approval_ttl_seconds=config.approval_ttl_seconds,
        )
    except CaseNotFound:
        raise HTTPException(status_code=404, detail=f"Case '{case_id}' was not found.") from None
    except InvalidCaseTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    verdict = case["result"].get("verdict") or {}
    approval = case["approval"]
    return {
        "case_id": case_id,
        "status": case["status"],
        "approved_at": approval["approved_at"],
        "approval_expires_at": approval["expires_at"],
        "approved_by": approval["approved_by"],
        "recommended_action": verdict.get("recommended_action", "NO_ACTION_REQUIRED"),
        "simulated": True,
    }


def _execute_graph_action(case: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None, str]:
    graph = get_graph()
    approval = case.get("approval") or {}
    action = case.get("action") or {}
    audit = {
        "api_case_id": case["case_id"],
        "action_type": action.get("action_type"),
        "approved_by": approval.get("approved_by"),
        "approved_at": approval.get("approved_at"),
        "approval_expires_at": approval.get("expires_at"),
        "execution_actor": action.get("execution_actor"),
        "execution_started_at": action.get("started_at"),
    }
    context = ToolContext(graph_store=GraphStore(graph), risk_scorer=RiskScorer(), action_audit=audit)
    context.evidence_trail.extend(case["result"].get("steps") or [])
    verdict = case["result"].get("verdict") or {}
    results = execute_recommended_action(context, case["account_id"], verdict)
    graph_case_id = next(
        (entry.get("data", {}).get("case_id") for entry in results
         if entry.get("tool") == "create_investigation_case" and entry.get("ok")),
        None,
    )
    failed = [entry for entry in results if not entry.get("ok")]
    if failed:
        raise RuntimeError("Simulated graph action failed: " + "; ".join(entry.get("summary", "unknown error") for entry in failed))
    if not graph_case_id:
        raise RuntimeError("The action engine did not return a persisted FalkorDB case ID.")
    audit_write = next(
        (entry.get("data") for entry in results
         if entry.get("tool") == "finalize_case_action_audit" and entry.get("ok")),
        None,
    )
    if (not isinstance(audit_write, dict)
            or audit_write.get("case_id") != graph_case_id
            or audit_write.get("api_case_id") != case["case_id"]
            or audit_write.get("graph_write_status") != "written"
            or audit_write.get("action_outcome") != "succeeded"):
        raise RuntimeError("FalkorDB did not confirm the expected case and completed action-audit write.")
    return results, graph_case_id, "written"


@app.post("/api/actions/{case_id}/execute", response_model=ActionExecutionResponse)
def execute_action(
    case_id: str,
    payload: ActionExecutionRequest,
    analyst: AuthenticatedAnalyst = Depends(require_action_analyst),
    store: InvestigationStore = Depends(get_store),
) -> dict[str, Any]:
    try:
        case = store.begin_execution(case_id, analyst=analyst.username, confirmed=payload.confirmed)
    except CaseNotFound:
        raise HTTPException(status_code=404, detail=f"Case '{case_id}' was not found.") from None
    except AnalystMismatch as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except InvalidCaseTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None

    try:
        results, graph_case_id, write_status = _execute_graph_action(case)
        complete = store.complete_execution(
            case_id,
            results=results,
            graph_case_id=graph_case_id,
            graph_write_status=write_status,
        )
    except Exception as exc:  # the multi-query write may have partially succeeded; replay is blocked
        logger.exception("Action execution failed for %s", case_id)
        store.fail_execution(case_id, str(exc))
        raise HTTPException(status_code=502, detail=f"Action execution failed; inspect FalkorDB before any manual retry: {exc}") from exc

    verdict = complete["result"].get("verdict") or {}
    action = complete["action"]
    approval = complete["approval"]
    return {
        "case_id": case_id,
        "status": complete["status"],
        "executed_at": action["executed_at"],
        "action": verdict.get("recommended_action", "NO_ACTION_REQUIRED"),
        "approved_by": approval["approved_by"],
        "approved_at": approval["approved_at"],
        "executed_by": action["execution_actor"],
        "graph_case_id": graph_case_id,
        "graph_write_status": write_status,
        "results": action.get("results", []),
        "simulated": True,
    }


@app.get("/")
def root() -> Any:
    index = FRONTEND_DIST / "index.html"
    if index.is_file():
        return FileResponse(index)
    return {"service": "RingTrace API", "frontend": "not built", "docs": "/docs"}


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str) -> Any:
    if full_path == "api" or full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API route not found.")
    dist = FRONTEND_DIST.resolve()
    requested = (dist / full_path).resolve()
    if requested.is_relative_to(dist) and requested.is_file():
        return FileResponse(requested)
    index = dist / "index.html"
    if index.is_file():
        return FileResponse(index)
    raise HTTPException(status_code=404, detail="Frontend has not been built.")
