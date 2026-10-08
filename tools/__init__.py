"""
tools/ — RingTrace's MCP-style agent tool layer.

Importing this package registers every investigation + action tool into
`tools.base.REGISTRY`. Both the LLM tool-calling agent and the deterministic
rule-based planner share this single registry, so there is exactly one
definition of "what a tool does" in the whole system.
"""
from tools.base import REGISTRY  # noqa: F401
from tools import investigation  # noqa: F401,E402
from tools import actions  # noqa: F401,E402

__all__ = ["REGISTRY"]
