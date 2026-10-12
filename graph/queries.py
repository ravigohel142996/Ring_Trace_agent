"""
graph/queries.py
-----------------
`GraphStore` is the ONLY interface RingTrace's tools use to touch data.
Every public method here issues real, parameterized Cypher against FalkorDB
and returns a `QueryResult` that carries the exact Cypher text alongside the
parsed data — this is what lets the dashboard show judges the literal query
that produced each piece of evidence ("graph evidence", not a black box).

Design notes
~~~~~~~~~~~~
* Money-flow questions ("where did the funds go?") are answered with the
  directed, weighted `TRANSFERRED_TO` edges and `Transaction` nodes.
* Identity-resolution / ring-detection questions ("who is really connected to
  whom?") are answered with the derived `LINKED_TO` edges, which are created
  at ingestion time whenever two accounts share a device, an IP, an owning
  person, or a broker. Running WCC / PageRank on `LINKED_TO` is what lets
  FalkorDB — not string matching, not a dashboard filter — decide which
  accounts form a fraud ring and who the likely ring leader is.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from graph.schema import (
    L_ACCOUNT,
    R_LINKED_TO,
    R_TRANSFERRED_TO,
)

logger = logging.getLogger("ringtrace.graph.queries")


@dataclass
class QueryResult:
    """Every GraphStore call returns one of these so the caller (a tool) can
    surface the exact Cypher + params as evidence."""

    data: Any
    cypher: str
    params: dict = field(default_factory=dict)
    row_count: int = 0

    def as_evidence(self) -> dict:
        return {"cypher": self.cypher, "params": self.params, "row_count": self.row_count}


class GraphStore:
    def __init__(self, graph):
        self.graph = graph

    # ------------------------------------------------------------------
    # internal helper
    # ------------------------------------------------------------------
    def _run(self, cypher: str, params: Optional[dict] = None) -> QueryResult:
        params = params or {}
        result = self.graph.query(cypher, params)
        rows = result.result_set or []
        return QueryResult(data=rows, cypher=cypher, params=params, row_count=len(rows))

    # ------------------------------------------------------------------
    # 1. get_account_context
    # ------------------------------------------------------------------
    def account_context(self, account_id: str) -> QueryResult:
        cypher = """
        MATCH (a:Account {id: $id})
        OPTIONAL MATCH (p:Person)-[:OWNS]->(a)
        OPTIONAL MATCH (a)-[:USES_DEVICE]->(d:Device)
        OPTIONAL MATCH (a)-[:LOGGED_FROM]->(ip:IP)
        OPTIONAL MATCH (a)-[:ROUTED_THROUGH]->(br:Broker)
        OPTIONAL MATCH (al:Alert)-[:FLAGS]->(a)
        OPTIONAL MATCH (a)-[out:TRANSFERRED_TO]->(dest:Account)
        OPTIONAL MATCH (src:Account)-[inn:TRANSFERRED_TO]->(a)
        OPTIONAL MATCH (a)<-[:FROM]-(mt:Transaction)-[:TO_MERCHANT]->(m:Merchant)
        RETURN a {.*} AS account,
               p {.*} AS owner,
               collect(DISTINCT d {.*}) AS devices,
               collect(DISTINCT ip {.*}) AS ips,
               collect(DISTINCT br {.*}) AS brokers,
               collect(DISTINCT al {.*}) AS alerts,
               collect(DISTINCT {to: dest.id, amount: out.amount, timestamp: out.timestamp}) AS outgoing,
               collect(DISTINCT {from: src.id, amount: inn.amount, timestamp: inn.timestamp}) AS incoming,
               collect(DISTINCT {merchant_id: m.id, merchant_name: m.name, category: m.category,
                                  amount: mt.amount, timestamp: mt.timestamp}) AS merchant_purchases
        """
        return self._run(cypher, {"id": account_id})

    def account_exists(self, account_id: str) -> bool:
        res = self._run("MATCH (a:Account {id: $id}) RETURN a.id LIMIT 1", {"id": account_id})
        return res.row_count > 0

    # ------------------------------------------------------------------
    # 2. find_fraud_ring  (Weakly Connected Components over LINKED_TO)
    # ------------------------------------------------------------------
    def weakly_connected_components(self) -> QueryResult:
        cypher = (
            "CALL algo.WCC({nodeLabels: ['Account'], relationshipTypes: ['LINKED_TO']}) "
            "YIELD node, componentId "
            "RETURN node.id AS account_id, componentId"
        )
        return self._run(cypher)

    def component_edges(self, account_ids: list[str]) -> QueryResult:
        cypher = """
        MATCH (a:Account)-[r:LINKED_TO]->(b:Account)
        WHERE a.id IN $ids AND b.id IN $ids
        RETURN a.id AS source, b.id AS target, r.via AS via, r.ref AS ref, r.weight AS weight
        """
        return self._run(cypher, {"ids": account_ids})

    def accounts_summary(self, account_ids: list[str]) -> QueryResult:
        cypher = """
        MATCH (a:Account) WHERE a.id IN $ids
        OPTIONAL MATCH (al:Alert)-[:FLAGS]->(a)
        RETURN a.id AS id, a.status AS status, a.account_type AS account_type,
               a.country AS country, count(DISTINCT al) AS alert_count
        """
        return self._run(cypher, {"ids": account_ids})

    # ------------------------------------------------------------------
    # Ring-score signal bundle — feeds the transparent composite ring score
    # in tools/investigation.py::_find_fraud_ring. Each method isolates ONE
    # graph-native signal so the final score is fully auditable: every
    # number in it traces back to one parameterized Cypher query.
    # ------------------------------------------------------------------
    def shared_identity_pair_counts(self, account_ids: list[str]) -> QueryResult:
        """Within this set of accounts, how many distinct PAIRS share a device
        and how many share an IP. A real coordinated ring tends to have many
        such pairs; a component that only happens to be money-linked usually
        has few or none."""
        cypher = """
        UNWIND $ids AS id1
        UNWIND $ids AS id2
        WITH id1, id2 WHERE id1 < id2
        MATCH (a:Account {id: id1}), (b:Account {id: id2})
        OPTIONAL MATCH (a)-[:USES_DEVICE]->(d:Device)<-[:USES_DEVICE]-(b)
        OPTIONAL MATCH (a)-[:LOGGED_FROM]->(ip:IP)<-[:LOGGED_FROM]-(b)
        WITH id1, id2, count(DISTINCT d) AS shared_devices, count(DISTINCT ip) AS shared_ips
        RETURN sum(CASE WHEN shared_devices > 0 THEN 1 ELSE 0 END) AS shared_device_pairs,
               sum(CASE WHEN shared_ips > 0 THEN 1 ELSE 0 END) AS shared_ip_pairs
        """
        return self._run(cypher, {"ids": account_ids})

    def reciprocal_transfer_pairs(self, account_ids: list[str]) -> QueryResult:
        """Counts account pairs where money flows BOTH ways (A->B and B->A) —
        a classic wash-trading / layering signature that a plain component-size
        check cannot see."""
        cypher = """
        MATCH (a:Account)-[:TRANSFERRED_TO]->(b:Account)
        WHERE a.id IN $ids AND b.id IN $ids AND a.id < b.id
        MATCH (b)-[:TRANSFERRED_TO]->(a)
        RETURN count(DISTINCT (a.id + '|' + b.id)) AS reciprocal_pairs
        """
        return self._run(cypher, {"ids": account_ids})

    def component_txn_stats(self, account_ids: list[str]) -> QueryResult:
        """Internal transaction density/volume: how much money moved, and how
        many transfers, strictly BETWEEN members of this component."""
        cypher = """
        MATCH (a:Account)-[t:TRANSFERRED_TO]->(b:Account)
        WHERE a.id IN $ids AND b.id IN $ids
        RETURN count(t) AS txn_count, sum(t.amount) AS total_amount,
               min(t.timestamp) AS earliest_ts, max(t.timestamp) AS latest_ts
        """
        return self._run(cypher, {"ids": account_ids})

    def component_broker_count(self, account_ids: list[str]) -> QueryResult:
        """Distinct brokers/mixers collectively used by this component — a
        shared high-risk broker across multiple members is a strong
        money-laundering signal on its own."""
        cypher = """
        MATCH (a:Account)-[:ROUTED_THROUGH]->(b:Broker)
        WHERE a.id IN $ids
        RETURN count(DISTINCT b) AS broker_count
        """
        return self._run(cypher, {"ids": account_ids})

    def component_alert_count(self, account_ids: list[str]) -> QueryResult:
        """How many members of this component already carry an open fraud alert."""
        cypher = """
        MATCH (al:Alert)-[:FLAGS]->(a:Account)
        WHERE a.id IN $ids
        RETURN count(DISTINCT a) AS alerted_member_count
        """
        return self._run(cypher, {"ids": account_ids})
        return self._run(cypher, {"ids": account_ids})

    # ------------------------------------------------------------------
    # 3. rank_ring_leaders (PageRank over LINKED_TO)
    # ------------------------------------------------------------------
    def pagerank(self, relationship_type: str = R_TRANSFERRED_TO) -> QueryResult:
        """Rank accounts by centrality. Defaults to the DIRECTED money-flow
        graph (`TRANSFERRED_TO`) because ring-leader discovery cares about
        *where funds accumulate* — a node many mule accounts pay into will
        naturally receive a high PageRank score. Pass `LINKED_TO` instead to
        rank by identity-resolution centrality (who is structurally most
        central to the identity graph, regardless of money flow)."""
        cypher = (
            f"CALL algo.pageRank('{L_ACCOUNT}', '{relationship_type}') "
            "YIELD node, score "
            "RETURN node.id AS account_id, score "
            "ORDER BY score DESC"
        )
        return self._run(cypher)

    # ------------------------------------------------------------------
    # 4. trace_money_path
    # ------------------------------------------------------------------
    def money_path_to_target(self, source_id: str, destination_id: str, max_hops: int = 6) -> QueryResult:
        cypher = f"""
        MATCH p = (a:Account {{id: $src}})-[:{R_TRANSFERRED_TO}*1..{int(max_hops)}]->(b:Account {{id: $dst}})
        RETURN [n IN nodes(p) | n.id] AS account_path,
               [r IN relationships(p) | {{amount: r.amount, timestamp: r.timestamp, txn_id: r.txn_id}}] AS transfers,
               length(p) AS hops
        ORDER BY hops ASC
        LIMIT 5
        """
        return self._run(cypher, {"src": source_id, "dst": destination_id})

    def money_path_exploration(self, source_id: str, max_hops: int = 6) -> QueryResult:
        """No destination given: surface the most interesting outbound money
        trails — longest chains that terminate at a broker-routed or
        previously-alerted account (classic layering / cash-out signature)."""
        cypher = f"""
        MATCH p = (a:Account {{id: $src}})-[:{R_TRANSFERRED_TO}*1..{int(max_hops)}]->(b:Account)
        WHERE a <> b
        OPTIONAL MATCH (b)-[:ROUTED_THROUGH]->(br:Broker)
        OPTIONAL MATCH (al:Alert)-[:FLAGS]->(b)
        WITH p, b, br, al, length(p) AS hops
        RETURN [n IN nodes(p) | n.id] AS account_path,
               [r IN relationships(p) | {{amount: r.amount, timestamp: r.timestamp, txn_id: r.txn_id}}] AS transfers,
               hops,
               br.id AS broker_id,
               (al IS NOT NULL) AS ends_at_alerted_account
        ORDER BY (CASE WHEN br IS NOT NULL THEN 1 ELSE 0 END) DESC,
                 (CASE WHEN al IS NOT NULL THEN 1 ELSE 0 END) DESC,
                 hops DESC
        LIMIT 5
        """
        return self._run(cypher, {"src": source_id})

    # ------------------------------------------------------------------
    # 5. find_identity_links
    # ------------------------------------------------------------------
    def shared_devices(self, account_id: str) -> QueryResult:
        cypher = """
        MATCH (a:Account {id: $id})-[:USES_DEVICE]->(d:Device)<-[:USES_DEVICE]-(other:Account)
        WHERE other.id <> $id
        RETURN d.id AS device_id, d.device_type AS device_type, collect(DISTINCT other.id) AS other_accounts
        """
        return self._run(cypher, {"id": account_id})

    def shared_ips(self, account_id: str) -> QueryResult:
        cypher = """
        MATCH (a:Account {id: $id})-[:LOGGED_FROM]->(ip:IP)<-[:LOGGED_FROM]-(other:Account)
        WHERE other.id <> $id
        RETURN ip.id AS ip_id, ip.address AS address, collect(DISTINCT other.id) AS other_accounts
        """
        return self._run(cypher, {"id": account_id})

    def shared_owners(self, account_id: str) -> QueryResult:
        cypher = """
        MATCH (p:Person)-[:OWNS]->(a:Account {id: $id})
        MATCH (p)-[:OWNS]->(other:Account)
        WHERE other.id <> $id
        RETURN p.id AS person_id, p.name AS person_name, collect(DISTINCT other.id) AS other_accounts
        """
        return self._run(cypher, {"id": account_id})

    def shared_brokers(self, account_id: str) -> QueryResult:
        cypher = """
        MATCH (a:Account {id: $id})-[:ROUTED_THROUGH]->(b:Broker)<-[:ROUTED_THROUGH]-(other:Account)
        WHERE other.id <> $id
        RETURN b.id AS broker_id, b.name AS broker_name, collect(DISTINCT other.id) AS other_accounts
        """
        return self._run(cypher, {"id": account_id})

    # ------------------------------------------------------------------
    # 6. calculate_risk_score — graph feature extraction
    # ------------------------------------------------------------------
    def degree_stats(self, account_id: str) -> QueryResult:
        # Aggregate each transfer direction before matching the next relationship
        # family. Keeping the stages separate prevents outgoing, incoming, and
        # LINKED_TO fan-out from multiplying one another's financial totals.
        cypher = """
        MATCH (a:Account {id: $id})
        OPTIONAL MATCH (a)-[out:TRANSFERRED_TO]->()
        WITH a, count(DISTINCT out) AS out_txn_count,
             coalesce(sum(out.amount), 0.0) AS total_out_amount
        OPTIONAL MATCH ()-[inn:TRANSFERRED_TO]->(a)
        WITH a, out_txn_count, total_out_amount,
             count(DISTINCT inn) AS in_txn_count,
             coalesce(sum(inn.amount), 0.0) AS total_in_amount
        OPTIONAL MATCH (a)-[l:LINKED_TO]-()
        RETURN out_txn_count AS out_txn_count,
               total_out_amount AS total_out_amount,
               in_txn_count AS in_txn_count,
               total_in_amount AS total_in_amount,
               count(DISTINCT l) AS linked_degree
        """
        return self._run(cypher, {"id": account_id})

    def broker_count(self, account_id: str) -> QueryResult:
        cypher = """
        MATCH (a:Account {id: $id})-[:ROUTED_THROUGH]->(b:Broker)
        RETURN count(DISTINCT b) AS broker_count
        """
        return self._run(cypher, {"id": account_id})

    def hops_to_nearest_alert(self, account_id: str, max_hops: int = 6) -> QueryResult:
        cypher = f"""
        MATCH (a:Account {{id: $id}})
        MATCH (al:Alert)-[:FLAGS]->(s:Account)
        WHERE s.id <> $id
        WITH a, s
        WITH shortestPath((a)-[:LINKED_TO*..{int(max_hops)}]->(s)) AS p
        RETURN min(length(p)) AS hops_to_alert
        """
        return self._run(cypher, {"id": account_id})

    def own_alert_count(self, account_id: str) -> QueryResult:
        cypher = """
        MATCH (al:Alert)-[:FLAGS]->(a:Account {id: $id})
        RETURN count(DISTINCT al) AS alert_count
        """
        return self._run(cypher, {"id": account_id})

    def suspicious_neighbor_ratio(self, account_id: str) -> QueryResult:
        cypher = """
        MATCH (a:Account {id: $id})-[:LINKED_TO]-(n:Account)
        WITH a, count(DISTINCT n) AS total_neighbors
        OPTIONAL MATCH (a:Account {id: $id})-[:LINKED_TO]-(n2:Account)<-[:FLAGS]-(:Alert)
        RETURN total_neighbors, count(DISTINCT n2) AS alerted_neighbors
        """
        return self._run(cypher, {"id": account_id})

    # ------------------------------------------------------------------
    # Optional tools: timeline / broker analysis / compare / generic entity
    # ------------------------------------------------------------------
    def timeline(self, account_id: str) -> QueryResult:
        cypher = """
        MATCH (t:Transaction)-[:FROM|TO]-(a:Account {id: $id})
        OPTIONAL MATCH (t)-[:FROM]->(src:Account)
        OPTIONAL MATCH (t)-[:TO]->(dst:Account)
        RETURN DISTINCT t.id AS txn_id, t.amount AS amount, t.timestamp AS timestamp,
               t.channel AS channel, src.id AS from_account, dst.id AS to_account
        ORDER BY t.timestamp ASC
        """
        return self._run(cypher, {"id": account_id})

    def broker_analysis(self, broker_id: Optional[str] = None) -> QueryResult:
        if broker_id:
            cypher = """
            MATCH (a:Account)-[:ROUTED_THROUGH]->(b:Broker {id: $broker_id})
            RETURN b.id AS broker_id, b.name AS name, b.broker_type AS broker_type,
                   b.risk_level AS risk_level, collect(DISTINCT a.id) AS accounts,
                   count(DISTINCT a) AS account_count
            """
            return self._run(cypher, {"broker_id": broker_id})
        cypher = """
        MATCH (a:Account)-[:ROUTED_THROUGH]->(b:Broker)
        RETURN b.id AS broker_id, b.name AS name, b.broker_type AS broker_type,
               b.risk_level AS risk_level, count(DISTINCT a) AS account_count
        ORDER BY account_count DESC
        """
        return self._run(cypher)

    def compare_accounts(self, account_a: str, account_b: str) -> QueryResult:
        cypher = """
        MATCH (a:Account {id: $a}), (b:Account {id: $b})
        OPTIONAL MATCH (a)-[:USES_DEVICE]->(da:Device)<-[:USES_DEVICE]-(b)
        OPTIONAL MATCH (a)-[:LOGGED_FROM]->(ipa:IP)<-[:LOGGED_FROM]-(b)
        OPTIONAL MATCH (a)-[:ROUTED_THROUGH]->(bra:Broker)<-[:ROUTED_THROUGH]-(b)
        WITH a, b, collect(DISTINCT da.id) AS shared_devices,
               collect(DISTINCT ipa.id) AS shared_ips,
               collect(DISTINCT bra.id) AS shared_brokers
        WITH shared_devices, shared_ips, shared_brokers, shortestPath((a)-[:LINKED_TO*..8]->(b)) AS p
        RETURN shared_devices, shared_ips, shared_brokers,
               CASE WHEN p IS NULL THEN null ELSE length(p) END AS link_distance
        """
        return self._run(cypher, {"a": account_a, "b": account_b})

    def investigate_entity(self, entity_type: str, entity_id: str) -> QueryResult:
        label_map = {"device": "Device", "ip": "IP", "person": "Person", "broker": "Broker"}
        label = label_map.get(entity_type.lower())
        if not label:
            raise ValueError(f"Unsupported entity_type '{entity_type}'. Use one of {list(label_map)}")
        rel = {
            "Device": "USES_DEVICE",
            "IP": "LOGGED_FROM",
            "Broker": "ROUTED_THROUGH",
            "Person": "OWNS",
        }[label]
        direction = "<-" if label == "Person" else "<-"
        cypher = f"""
        MATCH (n:{label} {{id: $id}})<-[:{rel}]-(a:Account)
        RETURN n {{.*}} AS entity, collect(DISTINCT a.id) AS connected_accounts, count(DISTINCT a) AS account_count
        """
        return self._run(cypher, {"id": entity_id})

    # ------------------------------------------------------------------
    # Alerts
    # ------------------------------------------------------------------
    def get_alert(self, alert_id: str) -> QueryResult:
        cypher = """
        MATCH (al:Alert {id: $id})-[:FLAGS]->(a:Account)
        RETURN al {.*} AS alert, a.id AS account_id
        """
        return self._run(cypher, {"id": alert_id})

    # ------------------------------------------------------------------
    # ACTION LAYER (graph-native writes)
    # ------------------------------------------------------------------
    def create_case(self, case_id: str, account_id: str, verdict: str, risk_score: float,
                     confidence: float, recommended_action: str, notes: str) -> QueryResult:
        cypher = """
        MATCH (a:Account {id: $account_id})
        CREATE (c:Case {
            id: $case_id, account_id: $account_id, verdict: $verdict,
            risk_score: $risk_score, confidence: $confidence,
            recommended_action: $recommended_action, status: 'OPEN',
            notes: $notes, created_at: timestamp()
        })-[:INVESTIGATES]->(a)
        RETURN c {.*} AS case
        """
        return self._run(cypher, {
            "case_id": case_id, "account_id": account_id, "verdict": verdict,
            "risk_score": risk_score, "confidence": confidence,
            "recommended_action": recommended_action, "notes": notes,
        })

    def flag_account(self, account_id: str, reason: str) -> QueryResult:
        cypher = """
        MATCH (a:Account {id: $id})
        SET a.flagged = true, a.flag_reason = $reason, a.flagged_at = timestamp()
        RETURN a {.*} AS account
        """
        return self._run(cypher, {"id": account_id, "reason": reason})

    def mark_high_risk(self, account_id: str, risk_score: float) -> QueryResult:
        cypher = """
        MATCH (a:Account {id: $id})
        SET a.risk_level = 'HIGH', a.risk_score = $score, a.status = 'UNDER_REVIEW'
        RETURN a {.*} AS account
        """
        return self._run(cypher, {"id": account_id, "score": risk_score})

    def escalate_case(self, case_id: str, reason: str) -> QueryResult:
        cypher = """
        MATCH (c:Case {id: $id})
        SET c.status = 'ESCALATED', c.escalation_reason = $reason, c.escalated_at = timestamp()
        RETURN c {.*} AS case
        """
        return self._run(cypher, {"id": case_id, "reason": reason})

    def request_manual_review(self, account_id: str, reason: str) -> QueryResult:
        cypher = """
        MATCH (a:Account {id: $id})
        SET a.status = 'MANUAL_REVIEW_REQUESTED', a.review_reason = $reason
        RETURN a {.*} AS account
        """
        return self._run(cypher, {"id": account_id, "reason": reason})

    def add_to_watchlist(self, entry_id: str, entity_id: str, entity_type: str, reason: str) -> QueryResult:
        cypher = """
        MATCH (e {id: $entity_id})
        WHERE $entity_type IN labels(e)
        CREATE (w:WatchlistEntry {
            id: $entry_id, entity_id: $entity_id, entity_type: $entity_type,
            reason: $reason, added_at: timestamp()
        })-[:WATCHES]->(e)
        RETURN w {.*} AS watchlist_entry
        """
        return self._run(cypher, {
            "entry_id": entry_id, "entity_id": entity_id,
            "entity_type": entity_type, "reason": reason,
        })

    def list_cases(self, limit: int = 100) -> QueryResult:
        """List durable investigation cases stored in FalkorDB."""
        safe_limit = max(1, min(int(limit), 500))
        cypher = f"MATCH (c:Case) RETURN c {{.*}} AS case ORDER BY c.created_at DESC LIMIT {safe_limit}"
        return self._run(cypher)

    def get_case(self, case_id: str) -> QueryResult:
        cypher = "MATCH (c:Case {id: $id}) RETURN c {.*} AS case"
        return self._run(cypher, {"id": case_id})

    # ------------------------------------------------------------------
    # SECOND-ORDER EVIDENCE GRAPH (additive — does not remove/rename the
    # existing Case-[:INVESTIGATES]->Account write above). Implements:
    #   (Account)-[:HAS_CASE]->(Case)
    #   (Case)-[:SUPPORTED_BY]->(Evidence)
    #   (Case)-[:RESULTED_IN]->(Action)
    #   (Action)-[:TRIGGERED_BY]->(GraphFinding)
    # so a judge (or `docs/DEMO_SCRIPT.md`'s sample Cypher) can literally
    # query "what graph finding triggered this action?" and get a real,
    # queryable answer instead of just a free-text reason string.
    # ------------------------------------------------------------------
    def attach_case_evidence(self, case_id: str, account_id: str, findings: list) -> QueryResult:
        """`findings`: list of {id, tool, summary} dicts, one per reasoning line /
        tool-call used to build the verdict. Writes a human-readable Evidence
        node AND a machine-traceable GraphFinding node per item (kept
        separate so the 'why' panel can show prose while Actions still link
        to the precise finding that triggered them), plus the reciprocal
        Account-[:HAS_CASE]->Case edge."""
        cypher = """
        MATCH (c:Case {id: $case_id})
        MATCH (a:Account {id: $account_id})
        MERGE (a)-[:HAS_CASE]->(c)
        WITH c
        UNWIND $findings AS f
        CREATE (e:Evidence {id: f.id + '-EV', text: f.summary, source_tool: f.tool})
        CREATE (gf:GraphFinding {id: f.id, tool: f.tool, summary: f.summary})
        CREATE (c)-[:SUPPORTED_BY]->(e)
        RETURN count(e) AS evidence_count
        """
        return self._run(cypher, {"case_id": case_id, "account_id": account_id, "findings": findings})

    def record_action_outcome(self, case_id: str, action_id: str, action_type: str, reason: str) -> QueryResult:
        """Creates the Action node and the Case-[:RESULTED_IN]->Action edge.
        Call `link_action_to_findings` right after with the GraphFinding ids
        this action was triggered by (kept as two queries — see the
        FalkorDB write-ordering note on the transaction-loading batch in
        ingestion/load_to_falkordb.py for why writes that depend on a
        subsequent conditional MATCH are split into separate queries)."""
        cypher = """
        MATCH (c:Case {id: $case_id})
        CREATE (ac:Action {id: $action_id, action_type: $action_type, reason: $reason, created_at: timestamp()})
        CREATE (c)-[:RESULTED_IN]->(ac)
        RETURN ac {.*} AS action
        """
        return self._run(cypher, {"case_id": case_id, "action_id": action_id,
                                   "action_type": action_type, "reason": reason})

    def link_action_to_findings(self, action_id: str, finding_ids: list) -> QueryResult:
        cypher = """
        MATCH (ac:Action {id: $action_id})
        UNWIND $finding_ids AS fid
        MATCH (gf:GraphFinding {id: fid})
        CREATE (ac)-[:TRIGGERED_BY]->(gf)
        RETURN count(gf) AS finding_count
        """
        return self._run(cypher, {"action_id": action_id, "finding_ids": finding_ids})

    def graph_stats(self) -> QueryResult:
        cypher = """
        MATCH (n) WITH count(n) AS nodes
        MATCH ()-[r]->() RETURN nodes, count(r) AS edges
        """
        return self._run(cypher)
