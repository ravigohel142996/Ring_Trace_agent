"""HTTP request and response contracts for RingTrace."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InvestigationRequest(ApiModel):
    account_id: str | None = Field(
        default=None,
        pattern=r"^[A-Z]{1,3}\d{3,6}$",
        description="Synthetic RingTrace account ID, such as A1027.",
    )
    query: str | None = Field(default=None, max_length=2000)
    scenario_id: str | None = Field(default=None, max_length=32)


class InvestigationSummary(ApiModel):
    case_id: str
    account_id: str
    created_at: str
    status: str
    result: dict[str, Any]
    approval: dict[str, Any] | None = None
    action: dict[str, Any] | None = None
    graph_case_id: str | None = None


class HealthResponse(ApiModel):
    status: Literal["ok", "degraded"]
    service: str


class Scenario(ApiModel):
    id: str
    account_id: str
    title: str
    description: str
    risk_focus: str


class ActionApprovalResponse(ApiModel):
    case_id: str
    status: str
    approved_at: str
    recommended_action: str
    simulated: Literal[True] = True


class ActionExecutionResponse(ApiModel):
    case_id: str
    status: str
    executed_at: str
    action: str
    graph_case_id: str | None = None
    graph_write_status: str
    results: list[dict[str, Any]]
    simulated: Literal[True] = True
