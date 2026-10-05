"""
tools/context.py
-----------------
Shared runtime context passed into every tool call: the live GraphStore, the
risk scorer, and small pieces of mutable session state (e.g. ID counters for
newly created Case / WatchlistEntry nodes).
"""
from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field

from graph.queries import GraphStore
from models.features import GraphFeatureCache
from models.risk_scorer import RiskScorer


@dataclass
class ToolContext:
    graph_store: GraphStore
    risk_scorer: RiskScorer
    evidence_trail: list = field(default_factory=list)
    _case_counter: itertools.count = field(default_factory=lambda: itertools.count(1))
    _watch_counter: itertools.count = field(default_factory=lambda: itertools.count(1))
    _feature_cache: GraphFeatureCache | None = None

    def feature_cache(self) -> GraphFeatureCache:
        if self._feature_cache is None:
            self._feature_cache = GraphFeatureCache.build(self.graph_store)
        return self._feature_cache

    def invalidate_cache(self) -> None:
        self._feature_cache = None

    def new_case_id(self) -> str:
        return f"CASE-{int(time.time()) % 100000}-{next(self._case_counter)}"

    def new_watchlist_id(self) -> str:
        return f"WL-{int(time.time()) % 100000}-{next(self._watch_counter)}"
