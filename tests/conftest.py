"""
tests/conftest.py
-------------------
Shared pytest fixtures. Graph-backed tests run against an explicitly opted-in,
disposable FalkorDB instance loaded with RingTrace's synthetic demo dataset.
The harness refuses to probe or mutate the default/live preview port 6379; if a
safe disposable target is not configured, only graph-dependent tests are skipped.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools  # noqa: E402  (registers all tools)
from graph.connection import health_check  # noqa: E402
from graph.connection import get_graph  # noqa: E402
from graph.queries import GraphStore  # noqa: E402
from models.risk_scorer import RiskScorer  # noqa: E402
from tools.context import ToolContext  # noqa: E402


def _graph_available() -> bool:
    # Graph-backed tests include simulated writes. Require an explicit disposable
    # target and refuse the default/live preview port before making any connection.
    try:
        port = int(os.getenv("FALKORDB_PORT", "6379"))
    except ValueError:
        return False
    if port == 6379 or os.getenv("RINGTRACE_TEST_DISPOSABLE") != "1":
        return False
    try:
        return health_check()["connected"]
    except Exception:  # noqa: BLE001
        return False


requires_graph = pytest.mark.skipif(
    not _graph_available(),
    reason=("FalkorDB tests require RINGTRACE_TEST_DISPOSABLE=1 and a reachable "
            "non-6379 FALKORDB_PORT; graph-backed tests can mutate their target"),
)


@pytest.fixture(scope="session")
def graph_store() -> GraphStore:
    return GraphStore(get_graph())


@pytest.fixture(scope="session")
def risk_scorer() -> RiskScorer:
    return RiskScorer()


@pytest.fixture
def ctx(graph_store, risk_scorer) -> ToolContext:
    return ToolContext(graph_store=graph_store, risk_scorer=risk_scorer)
