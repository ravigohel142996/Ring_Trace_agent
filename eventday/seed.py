"""Deterministic synthetic payment-corridor fixture for event-day development.

This loader is additive and idempotent: it never wipes a graph. It refuses to
run unless an explicit disposable-graph opt-in is set and port 6379 is avoided.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from eventday.graph import DEFAULT_DATASET_ID, get_event_graph, graph_settings


def fixture() -> dict[str, list[dict[str, Any]]]:
    anchor = int(datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc).timestamp())
    payments = [
        {"id": "PAY-ALERT-1001", "source": "W-ORIGIN-01", "target": "W-MULE-01", "occurred_at": anchor, "amount": 24000.0, "currency": "USD", "channel": "instant"},
        {"id": "PAY-ALERT-1002", "source": "W-MULE-01", "target": "W-MULE-02", "occurred_at": anchor + 240, "amount": 22100.0, "currency": "USD", "channel": "instant"},
        {"id": "PAY-ALERT-1003", "source": "W-MULE-02", "target": "W-MULE-03", "occurred_at": anchor + 510, "amount": 20400.0, "currency": "USD", "channel": "instant"},
        {"id": "PAY-BENIGN-2001", "source": "W-FAMILY-01", "target": "W-FAMILY-02", "occurred_at": anchor + 86400, "amount": 95.0, "currency": "USD", "channel": "scheduled"},
        {"id": "PAY-AMBIG-3001", "source": "W-SHOPPER-01", "target": "W-SHOPPER-02", "occurred_at": anchor + 172800, "amount": 180.0, "currency": "USD", "channel": "card"},
    ]
    wallets = sorted({wallet for payment in payments for wallet in (payment["source"], payment["target"])})
    devices = [
        {"wallet_id": "W-MULE-01", "device_id": "DEV-MULE-01"},
        {"wallet_id": "W-MULE-02", "device_id": "DEV-MULE-01"},
        {"wallet_id": "W-FAMILY-01", "device_id": "DEV-FAMILY-01"},
        {"wallet_id": "W-FAMILY-02", "device_id": "DEV-FAMILY-01"},
        {"wallet_id": "W-SHOPPER-01", "device_id": "DEV-SHARED-HOME-01"},
        {"wallet_id": "W-SHOPPER-02", "device_id": "DEV-SHARED-HOME-01"},
    ]
    owners = [
        {"wallet_id": "W-MULE-01", "owner_id": "OWNER-MULE-01"},
        {"wallet_id": "W-MULE-02", "owner_id": "OWNER-MULE-01"},
        {"wallet_id": "W-FAMILY-01", "owner_id": "OWNER-FAMILY-01"},
        {"wallet_id": "W-FAMILY-02", "owner_id": "OWNER-FAMILY-01"},
    ]
    payouts = [{"wallet_id": "W-MULE-03", "payout_id": "PAYOUT-EXT-01", "kind": "cash-out"}]
    return {"payments": payments, "wallets": [{"id": item} for item in wallets],
            "devices": devices, "owners": owners, "payouts": payouts}


def _query(graph, cypher: str, params: dict[str, Any]) -> None:
    graph.query(cypher, params)


def seed_eventday_graph() -> dict[str, int | str]:
    if os.getenv("RINGTRACE_EVENTDAY_ENABLED") != "1":
        raise RuntimeError("Refusing to seed while RINGTRACE_EVENTDAY_ENABLED is not 1.")
    if os.getenv("RINGTRACE_EVENTDAY_DISPOSABLE") != "1":
        raise RuntimeError("Refusing to seed without RINGTRACE_EVENTDAY_DISPOSABLE=1.")
    host, port, graph_name, username, password, tls = graph_settings()
    if (not os.getenv("RINGTRACE_EVENTDAY_FALKORDB_HOST")
            or not os.getenv("RINGTRACE_EVENTDAY_FALKORDB_PORT")):
        raise RuntimeError("Refusing to seed without an explicitly configured event-day host and port.")
    if port == 6379:
        raise RuntimeError("Refusing to seed port 6379; choose a dedicated non-6379 endpoint.")
    if graph_name != "ringtrace_eventday" and not graph_name.startswith("ringtrace_eventday_"):
        raise RuntimeError("Refusing to seed a graph outside the 'ringtrace_eventday' underscore prefix.")
    loopback = host in {"127.0.0.1", "localhost", "::1"}
    railway_private = host.lower().rstrip(".").endswith(".railway.internal")

    if not loopback:
        # Railway private-network traffic is encrypted by Railway's private
        # WireGuard network. Other remote endpoints must use TLS.
        if not railway_private and not tls:
            raise RuntimeError(
                "Refusing remote seed without TLS and configured username/password."
            )
        if not username or not password:
            raise RuntimeError(
                "Refusing remote seed without TLS and configured username/password."
            )
        if graph_name != "ringtrace_eventday_test":
            raise RuntimeError(
                "Remote seeding is restricted to graph 'ringtrace_eventday_test'."
            )

    dataset_id = os.getenv("RINGTRACE_EVENTDAY_DATASET", DEFAULT_DATASET_ID)
    data = fixture()
    graph = get_event_graph()
    _query(graph, """
        UNWIND $rows AS row
        MERGE (wallet:Wallet {id: row.id, dataset_id: $dataset_id})
        SET wallet.synthetic = true
    """, {"rows": data["wallets"], "dataset_id": dataset_id})
    _query(graph, """
        UNWIND $rows AS row
        MERGE (device:Device {id: row.device_id, dataset_id: $dataset_id})
        SET device.synthetic = true
        WITH row, device
        MATCH (wallet:Wallet {id: row.wallet_id, dataset_id: $dataset_id, synthetic: true})
        MERGE (wallet)-[link:AUTHENTICATED_ON {dataset_id: $dataset_id}]->(device)
        SET link.synthetic = true
    """, {"rows": data["devices"], "dataset_id": dataset_id})
    _query(graph, """
        UNWIND $rows AS row
        MERGE (owner:BeneficialOwner {id: row.owner_id, dataset_id: $dataset_id})
        SET owner.synthetic = true
        WITH row, owner
        MATCH (wallet:Wallet {id: row.wallet_id, dataset_id: $dataset_id, synthetic: true})
        MERGE (owner)-[link:CONTROLS {dataset_id: $dataset_id}]->(wallet)
        SET link.synthetic = true
    """, {"rows": data["owners"], "dataset_id": dataset_id})
    _query(graph, """
        UNWIND $rows AS row
        MATCH (source:Wallet {id: row.source, dataset_id: $dataset_id, synthetic: true})
        MATCH (target:Wallet {id: row.target, dataset_id: $dataset_id, synthetic: true})
        MERGE (payment:PaymentEvent {id: row.id, dataset_id: $dataset_id})
        SET payment.synthetic = true,
            payment.occurred_at = toInteger(row.occurred_at),
            payment.amount = toFloat(row.amount),
            payment.currency = row.currency,
            payment.channel = row.channel
        MERGE (payment)-[fromLink:FROM {dataset_id: $dataset_id}]->(source)
        SET fromLink.synthetic = true
        MERGE (payment)-[toLink:TO {dataset_id: $dataset_id}]->(target)
        SET toLink.synthetic = true
        MERGE (source)-[flow:FUNDED_TO {event_id: row.id, dataset_id: $dataset_id}]->(target)
        SET flow.synthetic = true,
            flow.occurred_at = toInteger(row.occurred_at),
            flow.amount = toFloat(row.amount),
            flow.currency = row.currency
    """, {"rows": data["payments"], "dataset_id": dataset_id})
    _query(graph, """
        UNWIND $rows AS row
        MERGE (payout:PayoutDestination {id: row.payout_id, dataset_id: $dataset_id})
        SET payout.synthetic = true, payout.kind = row.kind
        WITH row, payout
        MATCH (wallet:Wallet {id: row.wallet_id, dataset_id: $dataset_id, synthetic: true})
        MERGE (wallet)-[cashout:CASHED_OUT_TO {dataset_id: $dataset_id}]->(payout)
        SET cashout.synthetic = true
    """, {"rows": data["payouts"], "dataset_id": dataset_id})
    _query(graph, """
        MATCH (left:Wallet {dataset_id: $dataset_id, synthetic: true})
              -[:AUTHENTICATED_ON {dataset_id: $dataset_id, synthetic: true}]->
              (device:Device {dataset_id: $dataset_id, synthetic: true})
              <-[:AUTHENTICATED_ON {dataset_id: $dataset_id, synthetic: true}]-
              (right:Wallet {dataset_id: $dataset_id, synthetic: true})
        WHERE left.id < right.id
        MERGE (left)-[edge:COORDINATED_WITH {dataset_id: $dataset_id, signal: 'shared_device'}]->(right)
        SET edge.synthetic = true
    """, {"dataset_id": dataset_id})
    _query(graph, """
        MATCH (owner:BeneficialOwner {dataset_id: $dataset_id, synthetic: true})
              -[:CONTROLS {dataset_id: $dataset_id, synthetic: true}]->
              (left:Wallet {dataset_id: $dataset_id, synthetic: true})
        MATCH (owner)-[:CONTROLS {dataset_id: $dataset_id, synthetic: true}]->
              (right:Wallet {dataset_id: $dataset_id, synthetic: true})
        WHERE left.id < right.id
        MERGE (left)-[edge:COORDINATED_WITH {dataset_id: $dataset_id, signal: 'shared_owner'}]->(right)
        SET edge.synthetic = true
    """, {"dataset_id": dataset_id})
    stats = graph.query("""
        MATCH (n {dataset_id: $dataset_id, synthetic: true})
        WITH count(n) AS nodes
        MATCH (a {dataset_id: $dataset_id, synthetic: true})-[r]->(b {dataset_id: $dataset_id, synthetic: true})
        RETURN nodes, count(r) AS edges
    """, {"dataset_id": dataset_id}).result_set
    node_count, edge_count = stats[0] if stats else (0, 0)
    return {"graph": graph_name, "host": host, "port": port,
            "dataset_id": dataset_id, "nodes": int(node_count), "edges": int(edge_count)}


def main() -> None:
    stats = seed_eventday_graph()
    print("Seeded synthetic event-day graph:", stats)


if __name__ == "__main__":
    main()
