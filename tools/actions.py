"""
tools/actions.py
-----------------
The ACTION layer. These tools write real nodes/properties back into FalkorDB
(Case, WatchlistEntry, Account.status/risk_level/flagged) so an investigation
doesn't just end with a printed opinion — it leaves an auditable graph trail.

For hackathon demo safety these are simulated (no real financial system is
contacted), but the graph mutation itself is real and immediately queryable.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from agent.decision import build_verdict
from agent.report import build_case_report_markdown
from tools.base import REGISTRY, ToolResult, ToolSpec
from tools.context import ToolContext

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"


class CreateInvestigationCaseInput(BaseModel):
    account_id: str
    notes: str = Field("", description="Free-text investigator notes to attach to the case.")


def _create_investigation_case(ctx: ToolContext, inp: CreateInvestigationCaseInput) -> ToolResult:
    verdict = build_verdict(ctx, inp.account_id)
    case_id = ctx.new_case_id()
    res = ctx.graph_store.create_case(
        case_id=case_id, account_id=inp.account_id, verdict=verdict["verdict"],
        risk_score=verdict["risk_score"], confidence=verdict["confidence"],
        recommended_action=verdict["recommended_action"], notes=inp.notes,
    )
    summary = f"Created investigation case {case_id} for {inp.account_id} (verdict={verdict['verdict']})."
    return ToolResult(ok=True, tool="create_investigation_case", summary=summary,
                       data={"case_id": case_id, "verdict": verdict}, evidence=[res.as_evidence()])


class FlagAccountInput(BaseModel):
    account_id: str
    reason: str


def _flag_account(ctx: ToolContext, inp: FlagAccountInput) -> ToolResult:
    res = ctx.graph_store.flag_account(inp.account_id, inp.reason)
    return ToolResult(ok=True, tool="flag_account",
                       summary=f"Flagged {inp.account_id}: {inp.reason}",
                       data={"account": res.data[0][0] if res.data else None}, evidence=[res.as_evidence()])


class MarkHighRiskInput(BaseModel):
    account_id: str
    risk_score: float = Field(..., ge=0.0, le=1.0)


def _mark_high_risk(ctx: ToolContext, inp: MarkHighRiskInput) -> ToolResult:
    res = ctx.graph_store.mark_high_risk(inp.account_id, inp.risk_score)
    return ToolResult(ok=True, tool="mark_high_risk",
                       summary=f"Marked {inp.account_id} as HIGH risk (score={inp.risk_score:.2f}).",
                       data={"account": res.data[0][0] if res.data else None}, evidence=[res.as_evidence()])


class EscalateCaseInput(BaseModel):
    case_id: str
    reason: str


def _escalate_case(ctx: ToolContext, inp: EscalateCaseInput) -> ToolResult:
    res = ctx.graph_store.escalate_case(inp.case_id, inp.reason)
    if not res.data:
        return ToolResult(ok=False, tool="escalate_case", summary=f"Case {inp.case_id} not found.",
                           error="case_not_found")
    return ToolResult(ok=True, tool="escalate_case",
                       summary=f"Escalated case {inp.case_id}: {inp.reason}",
                       data={"case": res.data[0][0]}, evidence=[res.as_evidence()])


class RequestManualReviewInput(BaseModel):
    account_id: str
    reason: str


def _request_manual_review(ctx: ToolContext, inp: RequestManualReviewInput) -> ToolResult:
    res = ctx.graph_store.request_manual_review(inp.account_id, inp.reason)
    return ToolResult(ok=True, tool="request_manual_review",
                       summary=f"Requested manual review for {inp.account_id}: {inp.reason}",
                       data={"account": res.data[0][0] if res.data else None}, evidence=[res.as_evidence()])


class AddToWatchlistInput(BaseModel):
    entity_id: str
    entity_type: str = Field(..., description="Account, Device, IP, Person, or Broker")
    reason: str


def _add_to_watchlist(ctx: ToolContext, inp: AddToWatchlistInput) -> ToolResult:
    entry_id = ctx.new_watchlist_id()
    res = ctx.graph_store.add_to_watchlist(entry_id, inp.entity_id, inp.entity_type, inp.reason)
    if not res.data:
        return ToolResult(ok=False, tool="add_to_watchlist",
                           summary=f"Could not find {inp.entity_type} '{inp.entity_id}' to watch.",
                           error="entity_not_found")
    return ToolResult(ok=True, tool="add_to_watchlist",
                       summary=f"Added {inp.entity_type} {inp.entity_id} to watchlist ({entry_id}): {inp.reason}",
                       data={"watchlist_entry": res.data[0][0]}, evidence=[res.as_evidence()])


class ExportCaseSummaryInput(BaseModel):
    account_id: str


def _export_case_summary(ctx: ToolContext, inp: ExportCaseSummaryInput) -> ToolResult:
    verdict = build_verdict(ctx, inp.account_id)
    markdown = build_case_report_markdown(inp.account_id, ctx.evidence_trail, verdict)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"case_report_{inp.account_id}.md"
    path.write_text(markdown)
    return ToolResult(ok=True, tool="export_case_summary",
                       summary=f"Exported case summary for {inp.account_id} to {path.name}.",
                       data={"path": str(path), "markdown": markdown}, evidence=[])


class GenerateCaseReportInput(BaseModel):
    account_id: str


def _generate_case_report(ctx: ToolContext, inp: GenerateCaseReportInput) -> ToolResult:
    verdict = build_verdict(ctx, inp.account_id)
    markdown = build_case_report_markdown(inp.account_id, ctx.evidence_trail, verdict)
    return ToolResult(ok=True, tool="generate_case_report",
                       summary=f"Generated case report for {inp.account_id} ({len(markdown)} chars).",
                       data={"markdown": markdown}, evidence=[])


REGISTRY.register(ToolSpec(
    name="create_investigation_case",
    description="Open a formal investigation case for an account once a verdict has been reached. Writes a Case node into the graph linked to the account.",
    input_model=CreateInvestigationCaseInput, handler=_create_investigation_case, category="action",
))
REGISTRY.register(ToolSpec(
    name="flag_account",
    description="Mark an account as flagged with a reason, visible to any future investigation of it.",
    input_model=FlagAccountInput, handler=_flag_account, category="action",
))
REGISTRY.register(ToolSpec(
    name="mark_high_risk",
    description="Set an account's risk_level to HIGH and status to UNDER_REVIEW in the graph.",
    input_model=MarkHighRiskInput, handler=_mark_high_risk, category="action",
))
REGISTRY.register(ToolSpec(
    name="escalate_case",
    description="Escalate an already-open investigation Case for senior manual review.",
    input_model=EscalateCaseInput, handler=_escalate_case, category="action",
))
REGISTRY.register(ToolSpec(
    name="request_manual_review",
    description="Request a human investigator manually review an account before further activity is allowed.",
    input_model=RequestManualReviewInput, handler=_request_manual_review, category="action",
))
REGISTRY.register(ToolSpec(
    name="add_to_watchlist",
    description="Add any entity (account, device, IP, person, or broker) to the investigation watchlist for ongoing monitoring.",
    input_model=AddToWatchlistInput, handler=_add_to_watchlist, category="action",
))
REGISTRY.register(ToolSpec(
    name="export_case_summary",
    description="Write a downloadable Markdown case summary report to disk for this investigation.",
    input_model=ExportCaseSummaryInput, handler=_export_case_summary, category="action",
))
REGISTRY.register(ToolSpec(
    name="generate_case_report",
    description="Produce a full Markdown investigation report (verdict, reasoning, ring, money path, tool history) for display or export.",
    input_model=GenerateCaseReportInput, handler=_generate_case_report, category="investigation",
))
