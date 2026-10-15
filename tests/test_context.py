"""Unit tests for identifiers used by graph-backed simulated actions."""
from __future__ import annotations

from tools.context import ToolContext


def test_case_and_watchlist_ids_are_unique_across_contexts() -> None:
    contexts = [ToolContext(graph_store=None, risk_scorer=None) for _ in range(500)]
    case_ids = [context.new_case_id() for context in contexts]
    watchlist_ids = [context.new_watchlist_id() for context in contexts]

    assert len(set(case_ids)) == len(case_ids)
    assert len(set(watchlist_ids)) == len(watchlist_ids)
    assert all(case_id.startswith("CASE-") and len(case_id) == 37 for case_id in case_ids)
    assert all(entry_id.startswith("WL-") and len(entry_id) == 35 for entry_id in watchlist_ids)
