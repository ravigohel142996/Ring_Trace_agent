"""
tools/context.py
-----------------
Shared runtime context passed into every tool call: the live GraphStore, the
risk scorer, evidence trail, feature cache, and helpers for collision-resistant
IDs for graph-backed Case / WatchlistEntry nodes.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from graph.queries import GraphStore
from models.features import GraphFeatureCache
from models.risk_scorer import RiskScorer


@dataclass
class ToolContext:
    graph_store: GraphStore
    risk_scorer: RiskScorer
    evidence_trail: list = field(default_factory=list)
    _feature_cache: GraphFeatureCache | None = None

    def feature_cache(self) -> GraphFeatureCache:
        if self._feature_cache is None:
            self._feature_cache = GraphFeatureCache.build(self.graph_store)
        return self._feature_cache

    def invalidate_cache(self) -> None:
        self._feature_cache = None

    def new_case_id(self) -> str:
        """Return a process-independent, collision-resistant graph case ID."""
        return f"CASE-{uuid.uuid4().hex.upper()}"

    def new_watchlist_id(self) -> str:
        """Return a process-independent, collision-resistant watchlist ID."""
        return f"WL-{uuid.uuid4().hex.upper()}"
