"""
tests/conftest.py
-------------------
Shared pytest fixtures. These tests are integration-style: they run against
a real FalkorDB instance loaded with RingTrace's synthetic demo dataset
(`python -m ingestion.load_to_falkordb`). If no FalkorDB is reachable, the
whole suite is skipped with a clear message rather than failing noisily —
useful in CI environments that don't spin up the database.
"""
from __future__ import annotations

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
    try:
        return health_check()["connected"]
    except Exception:  # noqa: BLE001
        return False


requires_graph = pytest.mark.skipif(not _graph_available(), reason="FalkorDB is not reachable in this environment")


@pytest.fixture(scope="session")
def graph_store() -> GraphStore:
    return GraphStore(get_graph())


@pytest.fixture(scope="session")
def risk_scorer() -> RiskScorer:
    return RiskScorer()


@pytest.fixture
def ctx(graph_store, risk_scorer) -> ToolContext:
    return ToolContext(graph_store=graph_store, risk_scorer=risk_scorer)
