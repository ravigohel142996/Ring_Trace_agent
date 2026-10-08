"""
ingestion/load_to_falkordb.py
-------------------------------
Loads a SyntheticDataset into FalkorDB using batched, parameterized Cypher
(UNWIND ... MERGE/CREATE), then runs a post-processing pass that MATERIALIZES
the `LINKED_TO` identity-resolution graph: direct Account<->Account edges
derived from shared Device, shared IP, shared owning Person, shared Broker,
and direct money transfers.

This materialized `LINKED_TO` relationship is what makes FalkorDB's built-in
`algo.WCC` and `algo.pageRank` procedures directly usable for fraud-ring
detection and ring-leader discovery — the graph itself is doing identity
resolution, not a downstream Python script.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from graph.connection import get_graph
from graph.schema import ensure_schema, wipe_graph
from ingestion.generate_synthetic_data import GeneratorConfig, SyntheticDataset, generate

logger = logging.getLogger("ringtrace.ingestion")
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")


def _batch(graph, cypher: str, rows: list[dict], label: str, batch_size: int = 500) -> None:
    if not rows:
        return
    t0 = time.time()
    for i in range(0, len(rows), batch_size):
        chunk = rows[i:i + batch_size]
        graph.query(cypher, {"rows": chunk})
    logger.info("Loaded %d %s in %.2fs", len(rows), label, time.time() - t0)


def load_dataset(graph, ds: SyntheticDataset, wipe: bool = True) -> dict:
    if wipe:
        logger.info("Wiping existing graph contents...")
        wipe_graph(graph)

    ensure_schema(graph)

    _batch(graph, """
        UNWIND $rows AS row
        MERGE (p:Person {id: row.id})
        SET p.name = row.name, p.created_at = toInteger(row.created_at)
    """, ds.persons, "Person nodes")

    _batch(graph, """
        UNWIND $rows AS row
        MERGE (a:Account {id: row.id})
        SET a.account_type = row.account_type, a.status = row.status,
            a.country = row.country, a.created_at = toInteger(row.created_at)
    """, ds.accounts, "Account nodes")

    _batch(graph, """
        UNWIND $rows AS row
        MERGE (d:Device {id: row.id})
        SET d.device_type = row.device_type, d.first_seen = toInteger(row.first_seen)
    """, ds.devices, "Device nodes")

    _batch(graph, """
        UNWIND $rows AS row
        MERGE (ip:IP {id: row.id})
        SET ip.address = row.address, ip.geo = row.geo, ip.first_seen = toInteger(row.first_seen)
    """, ds.ips, "IP nodes")

    _batch(graph, """
        UNWIND $rows AS row
        MERGE (b:Broker {id: row.id})
        SET b.name = row.name, b.broker_type = row.broker_type, b.risk_level = row.risk_level
    """, ds.brokers, "Broker nodes")

    _batch(graph, """
        UNWIND $rows AS row
        MERGE (m:Merchant {id: row.id})
        SET m.name = row.name, m.category = row.category
    """, ds.merchants, "Merchant nodes")

    _batch(graph, """
        UNWIND $rows AS row
        MATCH (p:Person {id: row.person_id})
        MATCH (a:Account {id: row.account_id})
        MERGE (p)-[:OWNS]->(a)
    """, ds.person_account, "OWNS edges")

    _batch(graph, """
        UNWIND $rows AS row
        MATCH (a:Account {id: row.account_id})
        MATCH (d:Device {id: row.device_id})
        MERGE (a)-[:USES_DEVICE]->(d)
    """, ds.account_device, "USES_DEVICE edges")

    _batch(graph, """
        UNWIND $rows AS row
        MATCH (a:Account {id: row.account_id})
        MATCH (ip:IP {id: row.ip_id})
        MERGE (a)-[:LOGGED_FROM]->(ip)
    """, ds.account_ip, "LOGGED_FROM edges")

    _batch(graph, """
        UNWIND $rows AS row
        MATCH (a:Account {id: row.account_id})
        MATCH (b:Broker {id: row.broker_id})
        MERGE (a)-[:ROUTED_THROUGH]->(b)
    """, ds.account_broker, "ROUTED_THROUGH edges")

    # NOTE: FalkorDB can silently skip write clauses that occur *before* a
    # `WHERE` filter when the filter ultimately excludes a row (writes are
    # tied to the lazily-evaluated result stream). To guarantee every
    # transaction's FROM/TO/TRANSFERRED_TO edges are always created, we run
    # the unconditional writes in one batch and the optional broker-routing
    # edge as a second, separately-filtered batch. The same reasoning is why
    # account->account transfers and account->merchant purchases are split
    # into two DIFFERENT row lists (filtered in Python) and loaded as two
    # separate batches below, rather than one Cypher query with a branching
    # WHERE/CASE on to_account vs merchant_id.
    account_to_account_rows = [t for t in ds.transactions if t.get("to_account")]
    _batch(graph, """
        UNWIND $rows AS row
        MATCH (src:Account {id: row.from_account})
        MATCH (dst:Account {id: row.to_account})
        CREATE (t:Transaction {id: row.id, amount: toFloat(row.amount), timestamp: toInteger(row.timestamp),
                                timestamp_iso: row.timestamp_iso, channel: row.channel, status: row.status})
        CREATE (t)-[:FROM]->(src)
        CREATE (t)-[:TO]->(dst)
        CREATE (src)-[:TRANSFERRED_TO {amount: toFloat(row.amount), timestamp: toInteger(row.timestamp),
                                       txn_id: row.id}]->(dst)
    """, account_to_account_rows, "Transaction nodes + TRANSFERRED_TO edges")

    # Merchant purchases: one-sided spends (Account -> Merchant, no destination Account).
    # These complete realistic end-of-chain narratives (e.g. Account -> Broker -> Account ->
    # Merchant) that pure Account<->Account transfers can't represent, without polluting the
    # directed money-flow graph (TRANSFERRED_TO) that ring/leader/path algorithms run over.
    merchant_purchase_rows = [t for t in ds.transactions if not t.get("to_account") and t.get("merchant_id")]
    _batch(graph, """
        UNWIND $rows AS row
        MATCH (src:Account {id: row.from_account})
        MATCH (m:Merchant {id: row.merchant_id})
        CREATE (t:Transaction {id: row.id, amount: toFloat(row.amount), timestamp: toInteger(row.timestamp),
                                timestamp_iso: row.timestamp_iso, channel: row.channel, status: row.status})
        CREATE (t)-[:FROM]->(src)
        CREATE (t)-[:TO_MERCHANT {amount: toFloat(row.amount), timestamp: toInteger(row.timestamp),
                                  txn_id: row.id}]->(m)
    """, merchant_purchase_rows, "Transaction nodes + TO_MERCHANT edges")

    routed_rows = [t for t in ds.transactions if t.get("broker_id")]
    _batch(graph, """
        UNWIND $rows AS row
        MATCH (t:Transaction {id: row.id})
        MATCH (b:Broker {id: row.broker_id})
        CREATE (t)-[:ROUTED_THROUGH]->(b)
    """, routed_rows, "Transaction->Broker ROUTED_THROUGH edges")

    _batch(graph, """
        UNWIND $rows AS row
        MATCH (a:Account {id: row.account_id})
        MERGE (al:Alert {id: row.id})
        SET al.reason = row.reason, al.severity = row.severity,
            al.created_at = toInteger(row.created_at), al.status = row.status
        MERGE (al)-[:FLAGS]->(a)
    """, ds.alerts, "Alert nodes")

    materialize_linked_to(graph)

    stats = graph.query("MATCH (n) WITH count(n) AS nodes MATCH ()-[r]->() RETURN nodes, count(r) AS edges")
    nodes, edges = stats.result_set[0]
    logger.info("Graph load complete: %d nodes, %d edges", nodes, edges)
    return {"nodes": nodes, "edges": edges}


def materialize_linked_to(graph) -> None:
    """Derive the identity-resolution graph used by WCC / PageRank.

    Two accounts become LINKED_TO each other whenever the graph shows ANY of:
      - a shared Device        (via='DEVICE')
      - a shared IP            (via='IP')
      - a shared owning Person (via='PERSON')
      - a shared Broker        (via='BROKER')
      - a direct money transfer(via='TRANSACTION')
    Edges are created in BOTH directions so undirected-style reasoning
    (WCC, shortestPath) works with FalkorDB's directed traversal model.
    """
    t0 = time.time()
    graph.query("MATCH ()-[r:LINKED_TO]->() DELETE r")

    specs = [
        ("DEVICE", "MATCH (a:Account)-[:USES_DEVICE]->(x:Device)<-[:USES_DEVICE]-(b:Account) WHERE a.id < b.id "
                   "RETURN DISTINCT a.id AS a, b.id AS b, x.id AS ref"),
        ("IP", "MATCH (a:Account)-[:LOGGED_FROM]->(x:IP)<-[:LOGGED_FROM]-(b:Account) WHERE a.id < b.id "
               "RETURN DISTINCT a.id AS a, b.id AS b, x.id AS ref"),
        ("PERSON", "MATCH (p:Person)-[:OWNS]->(a:Account) MATCH (p)-[:OWNS]->(b:Account) WHERE a.id < b.id "
                   "RETURN DISTINCT a.id AS a, b.id AS b, p.id AS ref"),
        ("BROKER", "MATCH (a:Account)-[:ROUTED_THROUGH]->(x:Broker)<-[:ROUTED_THROUGH]-(b:Account) WHERE a.id < b.id "
                   "RETURN DISTINCT a.id AS a, b.id AS b, x.id AS ref"),
        ("TRANSACTION", "MATCH (a:Account)-[:TRANSFERRED_TO]->(b:Account) WHERE a.id <> b.id "
                         "RETURN DISTINCT a.id AS a, b.id AS b, 'txn' AS ref"),
    ]
    total = 0
    for via, match_cypher in specs:
        pairs = graph.query(match_cypher).result_set
        if not pairs:
            continue
        rows = [{"a": p[0], "b": p[1], "ref": p[2]} for p in pairs]
        graph.query(f"""
            UNWIND $rows AS row
            MATCH (a:Account {{id: row.a}}), (b:Account {{id: row.b}})
            MERGE (a)-[r1:LINKED_TO {{via: '{via}', ref: row.ref}}]->(b)
            MERGE (b)-[r2:LINKED_TO {{via: '{via}', ref: row.ref}}]->(a)
            SET r1.weight = 1.0, r2.weight = 1.0
        """, {"rows": rows})
        total += len(rows)
    logger.info("Materialized LINKED_TO graph: %d underlying identity signals in %.2fs", total, time.time() - t0)


def run(cfg: GeneratorConfig | None = None) -> dict:
    cfg = cfg or GeneratorConfig.from_env()
    logger.info("Generating synthetic dataset with config: %s", cfg)
    ds = generate(cfg)
    ds.to_csv()
    graph = get_graph()
    return load_dataset(graph, ds)


if __name__ == "__main__":
    stats = run()
    print(f"[RingTrace] FalkorDB graph ready: {stats['nodes']} nodes, {stats['edges']} edges")
