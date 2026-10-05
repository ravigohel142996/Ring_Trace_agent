"""
graph/ — FalkorDB connection, schema management, and the central Cypher query
catalogue for RingTrace.

FalkorDB is NOT a storage/visualization afterthought here: every investigative
decision the agent makes is produced by executing one of the Cypher statements
defined in `graph.cypher` against a live FalkorDB graph. This package is the
single source of truth for how RingTrace talks to the graph.
"""
from .connection import get_graph, health_check, GraphConnectionError

__all__ = ["get_graph", "health_check", "GraphConnectionError"]
