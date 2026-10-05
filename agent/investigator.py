"""
agent/investigator.py
-----------------------
The top-level RingTrace agent. Orchestrates a real investigation loop:

    user query -> identify target account -> dynamically choose + execute
    graph tools -> observe evidence -> decide next tool -> ... -> stop once
    sufficient evidence exists -> structured, evidence-backed verdict.

Two tool-selection strategies are supported:
  * LLM mode  (LLM_PROVIDER configured): an OpenAI-compatible model with
    function/tool-calling dynamically decides which graph tool to call next,
    reading each tool's real output before deciding on the next step.
  * Rule-based mode (default / fallback): a deterministic planner
    (`agent/rule_based.py`) follows the same investigative methodology.

In BOTH modes, the actual verdict shown to the investigator is always
produced by `agent.decision.build_verdict`, reading the structured evidence
trail — never by free-form LLM text — so RingTrace's decisions stay fully
auditable regardless of which planner ran.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from agent.decision import build_verdict
from agent.llm import get_llm_client
from agent.rule_based import run_investigation as run_rule_based_investigation
from graph.connection import get_graph, health_check
from graph.queries import GraphStore
from models.risk_scorer import RiskScorer
from tools.base import REGISTRY
from tools.context import ToolContext

logger = logging.getLogger("ringtrace.agent.investigator")

SYSTEM_PROMPT = """You are RingTrace, a fraud-ring investigation agent. You investigate suspicious \
financial accounts by querying a live FalkorDB property graph through the tools available to you. \
You must reason step by step and choose tools based on the evidence each call returns — do not call \
every tool blindly, and do not guess facts that aren't in the graph.

Recommended methodology (skip steps the evidence doesn't justify):
1. get_account_context — understand the account's direct graph neighborhood.
2. find_fraud_ring — check if the account belongs to a connected suspicious component.
3. rank_ring_leaders — if a ring was found, identify the likely ring leader.
4. trace_money_path — trace how funds move between the account and the ring leader / suspicious endpoints.
5. find_identity_links — confirm shared devices/IPs/brokers that explain the connections.
6. calculate_risk_score — compute a graph-derived ML risk score.
7. generate_verdict — once you have sufficient evidence, synthesize everything into a final verdict.

Call generate_verdict exactly once, as your last tool call. After that, write a short natural-language \
summary of your findings for the investigator."""


@dataclass
class InvestigationResult:
    account_id: str
    mode: str
    steps: list[dict] = field(default_factory=list)
    verdict: dict = field(default_factory=dict)
    narrative: Optional[str] = None
    graph_health: dict = field(default_factory=dict)
    error: Optional[str] = None


ACCOUNT_ID_PATTERN = re.compile(r"\b([A-Z]{1,3}\d{3,6})\b")


def extract_account_id(query: str) -> Optional[str]:
    match = ACCOUNT_ID_PATTERN.search(query or "")
    return match.group(1) if match else None


class Investigator:
    def __init__(self, graph_name: Optional[str] = None):
        self.graph_name = graph_name
        self._graph = None
        self._risk_scorer = None

    @property
    def graph(self):
        if self._graph is None:
            self._graph = get_graph(self.graph_name)
        return self._graph

    @property
    def risk_scorer(self) -> RiskScorer:
        if self._risk_scorer is None:
            self._risk_scorer = RiskScorer()
        return self._risk_scorer

    def new_context(self) -> ToolContext:
        ctx = ToolContext(graph_store=GraphStore(self.graph), risk_scorer=self.risk_scorer)
        ctx.evidence_trail = []  # type: ignore[attr-defined]
        return ctx

    def investigate(self, account_id: Optional[str] = None, query: str = "",
                     max_iterations: Optional[int] = None) -> InvestigationResult:
        health = health_check(self.graph_name)
        if not health["connected"]:
            return InvestigationResult(account_id=account_id or "", mode="none", error=(
                f"FalkorDB is unreachable at {health['host']}:{health['port']} — {health['error']}. "
                "RingTrace cannot investigate without its graph context layer."
            ), graph_health=health)

        target = account_id or extract_account_id(query)
        if not target:
            return InvestigationResult(account_id="", mode="none",
                                        error="Could not determine which account to investigate. "
                                              "Provide an account ID (e.g. 'A1027').", graph_health=health)

        ctx = self.new_context()
        llm = get_llm_client()
        if llm is not None:
            try:
                narrative = self._run_llm_loop(ctx, target, query, llm, max_iterations)
                mode = "llm"
            except Exception as exc:  # noqa: BLE001
                logger.warning("LLM investigation loop failed (%s); falling back to rule-based planner.", exc)
                ctx = self.new_context()
                run_rule_based_investigation(ctx, target)
                narrative = None
                mode = "rule_based_fallback"
        else:
            run_rule_based_investigation(ctx, target)
            narrative = None
            mode = "rule_based"

        verdict = build_verdict(ctx, target)
        return InvestigationResult(account_id=target, mode=mode, steps=ctx.evidence_trail,
                                    verdict=verdict, narrative=narrative, graph_health=health)

    # ------------------------------------------------------------------
    def _run_llm_loop(self, ctx: ToolContext, account_id: str, query: str, llm, max_iterations: Optional[int]) -> str:
        import os

        max_iterations = max_iterations or int(os.getenv("LLM_MAX_TOOL_ITERATIONS", "8"))
        tools_schema = REGISTRY.openai_schemas(category="investigation")

        user_msg = query.strip() if query and query.strip() else f"Investigate account {account_id}."
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"{user_msg}\n\nTarget account ID: {account_id}"},
        ]

        verdict_called = False
        for _ in range(max_iterations):
            response = llm.chat(messages, tools=tools_schema)
            msg = response.choices[0].message
            tool_calls = getattr(msg, "tool_calls", None)

            if not tool_calls:
                return msg.content or ""

            messages.append({"role": "assistant", "content": msg.content or "",
                              "tool_calls": [tc.model_dump() for tc in tool_calls]})

            for tc in tool_calls:
                name = tc.function.name
                try:
                    import json
                    args = json.loads(tc.function.arguments or "{}")
                except Exception:  # noqa: BLE001
                    args = {}
                spec = REGISTRY.get(name)
                if spec is None or spec.category != "investigation":
                    tool_result_text = f'{{"ok": false, "error": "unknown or disallowed tool {name}"}}'
                else:
                    result = spec.run(ctx, **args)
                    ctx.evidence_trail.append(result.to_dict())
                    if name == "generate_verdict" and result.ok:
                        verdict_called = True
                    import json as _json
                    tool_result_text = _json.dumps({"ok": result.ok, "summary": result.summary,
                                                     "data": result.data, "error": result.error}, default=str)[:6000]
                messages.append({"role": "tool", "tool_call_id": tc.id, "name": name, "content": tool_result_text})

            if verdict_called:
                messages.append({"role": "user", "content": "Write a brief (3-5 sentence) summary of your "
                                                              "findings and final verdict for the investigator."})
                final = llm.chat(messages, tools=None)
                return final.choices[0].message.content or ""

        return "Investigation stopped after reaching the maximum number of tool-call iterations."
