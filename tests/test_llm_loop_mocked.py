"""
tests/test_llm_loop_mocked.py
-------------------------------
P0 requirement: "LLM tool-calling mode was never exercised with a real key."
No live LLM_API_KEY is available in this environment (and must never be
committed to the repo), so this test exercises `Investigator._run_llm_loop`
against a FAKE OpenAI-compatible client that mimics the exact tool-calling
response shape `openai.chat.completions.create(...)` returns (`.choices[0]
.message.tool_calls[i].function.{name,arguments}`, `.model_dump()`, etc.).

This proves the LLM branch of the agent — the tool-call parsing, evidence
trail accumulation, verdict-triggered final-summary turn, and max-iteration
guard — is exercised and correct, independent of whether a real API key is
ever configured. It does NOT fake a real provider response; it is explicitly
a structural/contract test using a hand-built stand-in, which is the
documented, honest way to test this path without network access or secrets.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

import pytest

from agent.investigator import Investigator
from tests.conftest import requires_graph


@dataclass
class FakeFunction:
    name: str
    arguments: str


@dataclass
class FakeToolCall:
    id: str
    function: FakeFunction
    type: str = "function"

    def model_dump(self):
        return {"id": self.id, "type": self.type,
                "function": {"name": self.function.name, "arguments": self.function.arguments}}


@dataclass
class FakeMessage:
    content: Optional[str] = None
    tool_calls: Optional[list] = None


@dataclass
class FakeChoice:
    message: FakeMessage


@dataclass
class FakeResponse:
    choices: list = field(default_factory=list)


class FakeLLMClient:
    """Replays a scripted sequence of tool calls exactly like a real
    tool-calling-capable model would: one tool call per turn, then a final
    turn with no tool_calls and a plain narrative (mirrors the real OpenAI
    function-calling protocol RingTrace's loop is written against)."""

    def __init__(self, account_id: str):
        self.account_id = account_id
        self.call_count = 0
        self.script = [
            ("get_account_context", {"account_id": account_id}),
            ("find_fraud_ring", {"account_id": account_id}),
            ("rank_ring_leaders", {"account_ids": [account_id, "A1001"]}),
            ("calculate_risk_score", {"account_id": account_id}),
            ("generate_verdict", {"account_id": account_id}),
        ]

    def chat(self, messages, tools=None, tool_choice="auto"):
        self.call_count += 1
        step = self.call_count - 1
        if step < len(self.script):
            name, args = self.script[step]
            tc = FakeToolCall(id=f"call_{step}", function=FakeFunction(name=name, arguments=json.dumps(args)))
            return FakeResponse(choices=[FakeChoice(message=FakeMessage(content=None, tool_calls=[tc]))])
        # Final "no more tool calls" turn: plain narrative text, as real
        # tool-calling models produce once they're done.
        return FakeResponse(choices=[FakeChoice(message=FakeMessage(
            content=f"Investigation of {self.account_id} complete. See generate_verdict evidence for details.",
            tool_calls=None,
        ))])


@requires_graph
def test_llm_loop_executes_scripted_tool_calls_and_reaches_verdict():
    investigator = Investigator()
    ctx = investigator.new_context()
    fake_llm = FakeLLMClient("A1027")

    narrative = investigator._run_llm_loop(ctx, "A1027", "Investigate A1027", fake_llm, max_iterations=8)

    assert "A1027" in narrative
    tool_names_called = [e["tool"] for e in ctx.evidence_trail]
    assert tool_names_called == ["get_account_context", "find_fraud_ring", "rank_ring_leaders",
                                  "calculate_risk_score", "generate_verdict"]
    assert all(e["ok"] for e in ctx.evidence_trail)
    # The real OpenAI tool_call contract requires .model_dump() on each call
    # appended to the assistant message — confirm our fakes round-trip it.
    assert fake_llm.call_count == len(fake_llm.script) + 1  # +1 final narrative turn


@requires_graph
def test_llm_loop_respects_max_iterations_guard():
    investigator = Investigator()
    ctx = investigator.new_context()

    class InfiniteToolCaller:
        """A pathological fake that always wants to call another tool and
        never stops — proves the loop can't spin forever on a misbehaving
        or hallucinating model."""

        def __init__(self):
            self.call_count = 0

        def chat(self, messages, tools=None, tool_choice="auto"):
            self.call_count += 1
            tc = FakeToolCall(id=f"call_{self.call_count}",
                               function=FakeFunction(name="get_account_context",
                                                      arguments=json.dumps({"account_id": "A1027"})))
            return FakeResponse(choices=[FakeChoice(message=FakeMessage(content=None, tool_calls=[tc]))])

    fake_llm = InfiniteToolCaller()
    result = investigator._run_llm_loop(ctx, "A1027", "Investigate A1027", fake_llm, max_iterations=3)

    assert "maximum number of tool-call iterations" in result
    assert fake_llm.call_count == 3


@requires_graph
def test_llm_loop_rejects_unknown_or_non_investigation_tool():
    investigator = Investigator()
    ctx = investigator.new_context()

    class BadToolCaller:
        def __init__(self):
            self.call_count = 0

        def chat(self, messages, tools=None, tool_choice="auto"):
            self.call_count += 1
            if self.call_count == 1:
                tc = FakeToolCall(id="call_1", function=FakeFunction(
                    name="flag_account",  # an ACTION tool, not an investigation tool -> must be rejected
                    arguments=json.dumps({"account_id": "A1027", "reason": "test"})))
                return FakeResponse(choices=[FakeChoice(message=FakeMessage(content=None, tool_calls=[tc]))])
            return FakeResponse(choices=[FakeChoice(message=FakeMessage(
                content="done", tool_calls=None))])

    fake_llm = BadToolCaller()
    narrative = investigator._run_llm_loop(ctx, "A1027", "Investigate A1027", fake_llm, max_iterations=5)

    assert narrative == "done"
    # The disallowed tool must never have been executed against the real graph.
    assert ctx.evidence_trail == []
