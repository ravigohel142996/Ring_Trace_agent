"""
graph/schema.py
---------------
Declares the RingTrace property-graph schema (labels, relationship types) and
creates the FalkorDB indexes that keep multi-hop investigation queries fast
as the graph grows (see README "Performance & Scalability").
"""
from __future__ import annotations

import logging

logger = logging.getLogger("ringtrace.graph.schema")

# ---------------------------------------------------------------------------
# Node labels
# ---------------------------------------------------------------------------
L_PERSON = "Person"
L_ACCOUNT = "Account"
L_DEVICE = "Device"
L_IP = "IP"
L_TRANSACTION = "Transaction"
L_BROKER = "Broker"
L_MERCHANT = "Merchant"
L_ALERT = "Alert"
L_CASE = "Case"
L_WATCHLIST = "WatchlistEntry"

# ---------------------------------------------------------------------------
# Relationship types
# ---------------------------------------------------------------------------
R_OWNS = "OWNS"
R_USED_DEVICE = "USED_DEVICE"          # Person -> Device
R_USES_DEVICE = "USES_DEVICE"          # Account -> Device
R_LOGGED_FROM_P = "LOGGED_FROM"        # Person -> IP
R_LOGGED_FROM_A = "LOGGED_FROM"        # Account -> IP (same rel type, different endpoints)
R_ROUTED_THROUGH = "ROUTED_THROUGH"    # Account/Transaction -> Broker
R_TRANSFERRED_TO = "TRANSFERRED_TO"    # Account -> Account (denormalized money-flow edge)
R_FROM = "FROM"                        # Transaction -> Account
R_TO = "TO"                            # Transaction -> Account
R_TO_MERCHANT = "TO_MERCHANT"          # Transaction -> Merchant
R_FLAGS = "FLAGS"                      # Alert -> Account
R_LINKED_TO = "LINKED_TO"              # Account -> Account (derived identity-resolution graph)
R_INVESTIGATES = "INVESTIGATES"        # Case -> Account
R_WATCHES = "WATCHES"                  # WatchlistEntry -> Account

# Index definitions: (label, property)
INDEXES = [
    (L_PERSON, "id"),
    (L_ACCOUNT, "id"),
    (L_ACCOUNT, "status"),
    (L_DEVICE, "id"),
    (L_IP, "id"),
    (L_TRANSACTION, "id"),
    (L_TRANSACTION, "timestamp"),
    (L_BROKER, "id"),
    (L_MERCHANT, "id"),
    (L_ALERT, "id"),
    (L_CASE, "id"),
    (L_WATCHLIST, "id"),
]


def ensure_schema(graph) -> list[str]:
    """Create indexes if they do not already exist. Idempotent & safe to call
    on every startup (ingestion, dashboard, tests)."""
    executed = []
    for label, prop in INDEXES:
        cypher = f"CREATE INDEX FOR (n:{label}) ON (n.{prop})"
        try:
            graph.query(cypher)
            executed.append(cypher)
        except Exception as exc:  # noqa: BLE001 - FalkorDB raises if index exists
            msg = str(exc).lower()
            if "already indexed" in msg or "already exists" in msg:
                continue
            logger.warning("Index creation skipped (%s): %s", cypher, exc)
    logger.info("Schema ensured: %d indexes active", len(INDEXES))
    return executed


def wipe_graph(graph) -> None:
    """Danger: deletes all nodes/relationships in the current graph. Used by
    the synthetic data loader before a fresh ingest."""
    try:
        graph.query("MATCH (n) DETACH DELETE n")
    except Exception as exc:  # noqa: BLE001
        logger.warning("wipe_graph: graph may not exist yet (%s)", exc)
