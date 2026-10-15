"""HTTP request and response contracts for RingTrace."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictBool, StrictStr


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
    approval_history: list[dict[str, Any]] = Field(default_factory=list)
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


class AnalystLoginRequest(ApiModel):
    username: StrictStr = Field(min_length=1, max_length=128)
    password: SecretStr = Field(min_length=1, max_length=1024)


class AnalystSessionResponse(ApiModel):
    auth_enabled: bool
    authenticated: bool
    analyst: str | None = None
    csrf_token: str | None = None
    expires_at: str | None = None


class ActionApprovalResponse(ApiModel):
    case_id: str
    status: str
    approved_at: str
    approval_expires_at: str
    approved_by: str
    recommended_action: str
    simulated: Literal[True] = True


class ActionExecutionRequest(ApiModel):
    confirmed: StrictBool = Field(..., description="Explicit confirmation from the final simulated-action review.")


class ActionExecutionResponse(ApiModel):
    case_id: str
    status: str
    executed_at: str
    action: str
    approved_by: str
    approved_at: str
    executed_by: str
    graph_case_id: str
    graph_write_status: Literal["written"]
    results: list[dict[str, Any]]
    simulated: Literal[True] = True
