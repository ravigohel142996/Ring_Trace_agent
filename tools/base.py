"""
tools/base.py
-------------
Defines `ToolSpec` — the contract every RingTrace agent tool implements —
and a lightweight registry used both by the deterministic rule-based planner
and by the LLM tool-calling agent (converted to OpenAI-style JSON schemas).

Every tool returns a `ToolResult` with a uniform shape so the dashboard can
render ANY tool's output as an "evidence card" without special-casing it:
    { ok, tool, summary, data, evidence, error }
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from pydantic import BaseModel, ValidationError

logger = logging.getLogger("ringtrace.tools")


@dataclass
class ToolResult:
    ok: bool
    tool: str
    summary: str
    data: Any = None
    evidence: list[dict] = field(default_factory=list)
    error: Optional[str] = None
    duration_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "tool": self.tool,
            "summary": self.summary,
            "data": self.data,
            "evidence": self.evidence,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


@dataclass
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: Callable[..., ToolResult]
    category: str = "investigation"  # "investigation" | "action"

    def openai_schema(self) -> dict:
        """Convert the pydantic input model into an OpenAI-style function
        tool-calling schema."""
        schema = self.input_model.model_json_schema()
        schema.pop("title", None)
        for prop in schema.get("properties", {}).values():
            prop.pop("title", None)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": schema,
            },
        }

    def run(self, context, **kwargs) -> ToolResult:
        t0 = time.time()
        try:
            validated = self.input_model(**kwargs)
        except ValidationError as exc:
            return ToolResult(ok=False, tool=self.name, summary=f"Invalid input for {self.name}",
                               error=str(exc), duration_ms=(time.time() - t0) * 1000)
        try:
            result = self.handler(context, validated)
            result.duration_ms = (time.time() - t0) * 1000
            return result
        except Exception as exc:  # noqa: BLE001 — tools must NEVER crash the agent loop
            logger.exception("Tool '%s' failed", self.name)
            return ToolResult(ok=False, tool=self.name, summary=f"{self.name} failed: {exc}",
                               error=str(exc), duration_ms=(time.time() - t0) * 1000)


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def all(self, category: Optional[str] = None) -> list[ToolSpec]:
        specs = list(self._tools.values())
        if category:
            specs = [s for s in specs if s.category == category]
        return specs

    def openai_schemas(self, category: Optional[str] = None) -> list[dict]:
        return [s.openai_schema() for s in self.all(category)]

    def names(self, category: Optional[str] = None) -> list[str]:
        return [s.name for s in self.all(category)]


REGISTRY = ToolRegistry()
