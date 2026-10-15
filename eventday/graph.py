"""FalkorDB access for the event-day payment-corridor workflow.

The graph model is event-centred: PaymentEvent nodes preserve each payment's
identity and timestamp, while FUNDED_TO relationships form a queryable flow
projection for time-respecting traversal and PageRank. No static/mock query
results are substituted when FalkorDB is unavailable.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Any

from falkordb import FalkorDB

DEFAULT_GRAPH_NAME = "ringtrace_eventday"
DEFAULT_DATASET_ID = "ringtrace_eventday_synthetic_v1"


class GraphQueryError(RuntimeError):
    def __init__(self, name: str, cypher: str, params: dict[str, Any], cause: Exception):
        self.name = name
        self.cypher = cypher
        self.params = dict(params)
        self.cause = cause
        super().__init__(f"FalkorDB query '{name}' failed: {cause}")


@dataclass(frozen=True)
class QueryObservation:
    name: str
    cypher: str
    params: dict[str, Any]
    rows: list[Any]

    def evidence(self) -> dict[str, Any]:
        return {
            "query_name": self.name,
            "cypher": self.cypher,
            "params": dict(self.params),
            "row_count": len(self.rows),
        }


_graph_lock = threading.RLock()
_graph_cache: dict[tuple[str, int, str, str | None, str | None], Any] = {}


def graph_settings() -> tuple[str, int, str, str | None, str | None]:
    # This feature has its own connection settings; it must not silently reuse
    # the pre-existing RingTrace graph endpoint or the preview's graph config.
    host = os.getenv("RINGTRACE_EVENTDAY_FALKORDB_HOST", "127.0.0.1")
    port = int(os.getenv("RINGTRACE_EVENTDAY_FALKORDB_PORT", "6380"))
    graph_name = os.getenv("RINGTRACE_EVENTDAY_GRAPH", DEFAULT_GRAPH_NAME)
    username = os.getenv("RINGTRACE_EVENTDAY_FALKORDB_USERNAME") or None
    password = os.getenv("RINGTRACE_EVENTDAY_FALKORDB_PASSWORD") or None
    return host, port, graph_name, username, password


def get_event_graph():
    """Return a cached handle, refusing legacy/live endpoint conventions."""
    settings = graph_settings()
    host, port, graph_name, _, _ = settings
    if port == 6379:
        raise RuntimeError("Event-day graph access refuses port 6379; use a dedicated non-6379 endpoint.")
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("Event-day graph access is restricted to loopback; remote/shared targets are refused.")
    if graph_name != DEFAULT_GRAPH_NAME and not graph_name.startswith(f"{DEFAULT_GRAPH_NAME}_"):
        raise RuntimeError(f"Event-day graph name must be '{DEFAULT_GRAPH_NAME}' or use its underscore prefix.")
    with _graph_lock:
        if settings not in _graph_cache:
            host, port, graph_name, username, password = settings
            options: dict[str, Any] = {
                "host": host,
                "port": port,
                "socket_connect_timeout": 2,
                "socket_timeout": 8,
            }
            if username:
                options["username"] = username
            if password:
                options["password"] = password
            _graph_cache[settings] = FalkorDB(**options).select_graph(graph_name)
        return _graph_cache[settings]


class CorridorGraph:
    """Typed Cypher surface for payment-event investigation.

    Query text and bound parameters are returned with each observation so the
    UI can show the exact graph evidence behind the agent's choices.
    """

    def __init__(self, graph, dataset_id: str = DEFAULT_DATASET_ID):
        self.graph = graph
        self.dataset_id = dataset_id

    def _run(self, name: str, cypher: str, params: dict[str, Any]) -> QueryObservation:
        try:
            result = self.graph.query(cypher, params)
        except Exception as exc:  # keep the failing query visible to the agent
            raise GraphQueryError(name, cypher, params, exc) from exc
        return QueryObservation(name, cypher, dict(params), list(result.result_set or []))

    def inspect_payment(self, payment_event_id: str) -> QueryObservation:
        cypher = """
        MATCH (p:PaymentEvent {id: $payment_event_id, dataset_id: $dataset_id, synthetic: true})
        MATCH (p)-[:FROM {dataset_id: $dataset_id, synthetic: true}]->(source:Wallet {dataset_id: $dataset_id, synthetic: true})
        MATCH (p)-[:TO {dataset_id: $dataset_id, synthetic: true}]->(recipient:Wallet {dataset_id: $dataset_id, synthetic: true})
        RETURN p {.*} AS payment, source.id AS source_wallet, recipient.id AS recipient_wallet
        """
        return self._run("inspect_payment_event", cypher, {
            "payment_event_id": payment_event_id,
            "dataset_id": self.dataset_id,
        })

    def trace_corridor(
        self,
        wallet_id: str,
        *,
        after_ts: int,
        until_ts: int,
        max_hops: int,
    ) -> QueryObservation:
        if not 1 <= max_hops <= 6:
            raise ValueError("max_hops must be between 1 and 6")
        # max_hops is a validated integer literal; all user/data values remain
        # bound parameters to prevent Cypher injection.
        cypher = f"""
        MATCH path = (start:Wallet {{id: $wallet_id, dataset_id: $dataset_id, synthetic: true}})
                    -[:FUNDED_TO*1..{max_hops}]->
                    (sink:Wallet {{dataset_id: $dataset_id, synthetic: true}})
        WITH path, relationships(path) AS legs, sink
        WHERE all(r IN legs WHERE r.dataset_id = $dataset_id
                  AND r.synthetic = true
                  AND r.occurred_at > $after_ts
                  AND r.occurred_at <= $until_ts)
          AND CASE WHEN size(legs) < 2 THEN true
                   ELSE all(i IN range(0, size(legs) - 2)
                            WHERE legs[i].occurred_at < legs[i + 1].occurred_at)
              END
        OPTIONAL MATCH (sink)-[:CASHED_OUT_TO {{dataset_id: $dataset_id, synthetic: true}}]->
                       (payout:PayoutDestination {{dataset_id: $dataset_id, synthetic: true}})
        RETURN [n IN nodes(path) | n.id] AS wallets,
               [r IN legs | {{event_id: r.event_id, amount: r.amount,
                               currency: r.currency, occurred_at: r.occurred_at}}] AS transfers,
               sink.id AS sink_wallet,
               payout.id AS payout_id,
               size(legs) AS hop_count
        ORDER BY hop_count DESC, sink_wallet
        LIMIT 20
        """
        return self._run("trace_time_respecting_corridor", cypher, {
            "wallet_id": wallet_id,
            "dataset_id": self.dataset_id,
            "after_ts": int(after_ts),
            "until_ts": int(until_ts),
        })

    def shared_devices(self, wallet_ids: list[str]) -> QueryObservation:
        cypher = """
        MATCH (wallet:Wallet {dataset_id: $dataset_id, synthetic: true})
              -[:AUTHENTICATED_ON {dataset_id: $dataset_id, synthetic: true}]->(device:Device {dataset_id: $dataset_id, synthetic: true})
              <-[:AUTHENTICATED_ON {dataset_id: $dataset_id, synthetic: true}]-(other:Wallet {dataset_id: $dataset_id, synthetic: true})
        WHERE wallet.id IN $wallet_ids AND wallet.id < other.id
        RETURN DISTINCT wallet.id AS wallet_id, other.id AS related_wallet,
               device.id AS shared_device
        ORDER BY wallet_id, related_wallet, shared_device
        """
        return self._run("find_shared_devices", cypher, {
            "wallet_ids": sorted(set(wallet_ids)),
            "dataset_id": self.dataset_id,
        })

    def shared_owners(self, wallet_ids: list[str]) -> QueryObservation:
        cypher = """
        MATCH (owner:BeneficialOwner {dataset_id: $dataset_id, synthetic: true})
              -[:CONTROLS {dataset_id: $dataset_id, synthetic: true}]->(wallet:Wallet {dataset_id: $dataset_id, synthetic: true})
        MATCH (owner)-[:CONTROLS {dataset_id: $dataset_id, synthetic: true}]->(other:Wallet {dataset_id: $dataset_id, synthetic: true})
        WHERE wallet.id IN $wallet_ids AND wallet.id < other.id
        RETURN DISTINCT wallet.id AS wallet_id, other.id AS related_wallet,
               owner.id AS shared_owner
        ORDER BY wallet_id, related_wallet, shared_owner
        """
        return self._run("find_shared_owners", cypher, {
            "wallet_ids": sorted(set(wallet_ids)),
            "dataset_id": self.dataset_id,
        })

    def rank_wallets(self, wallet_ids: list[str]) -> QueryObservation:
        cypher = """
        CALL algo.pageRank('Wallet', 'FUNDED_TO') YIELD node, score
        WITH node, score
        WHERE node.dataset_id = $dataset_id AND node.synthetic = true
          AND node.id IN $wallet_ids
        RETURN node.id AS wallet_id, score AS page_rank
        ORDER BY page_rank DESC, wallet_id
        """
        return self._run("rank_corridor_wallets", cypher, {
            "wallet_ids": sorted(set(wallet_ids)),
            "dataset_id": self.dataset_id,
        })

    def components(self, wallet_ids: list[str]) -> QueryObservation:
        cypher = """
        CALL algo.WCC({nodeLabels: ['Wallet'], relationshipTypes: ['COORDINATED_WITH']})
        YIELD node, componentId
        WITH node, componentId
        WHERE node.dataset_id = $dataset_id AND node.synthetic = true
          AND node.id IN $wallet_ids
        RETURN node.id AS wallet_id, componentId AS component_id
        ORDER BY wallet_id
        """
        return self._run("group_coordinated_wallets", cypher, {
            "wallet_ids": sorted(set(wallet_ids)),
            "dataset_id": self.dataset_id,
        })

    def record_review_proposal(
        self,
        *,
        payment_event_id: str,
        run_id: str,
        proposal_id: str,
        created_by: str,
        approved_at: str,
        approval_expires_at: str,
        decision: str,
        review_signal_score: float,
        evidence_rows: list[dict[str, Any]],
    ) -> QueryObservation:
        cypher = """
        MATCH (payment:PaymentEvent {id: $payment_event_id, dataset_id: $dataset_id, synthetic: true})
        CREATE (run:CorridorInvestigation {
            id: $run_id, payment_event_id: $payment_event_id, dataset_id: $dataset_id,
            synthetic: true, created_at: $approved_at, decision: $decision,
            review_signal_score: $review_signal_score
        })
        CREATE (run)-[:ANALYZED_PAYMENT {dataset_id: $dataset_id, synthetic: true}]->(payment)
        CREATE (proposal:ReviewProposal {
            id: $proposal_id, payment_event_id: $payment_event_id, dataset_id: $dataset_id,
            synthetic: true, status: 'proposed_manual_review', created_by: $created_by,
            approved_at: $approved_at, approval_expires_at: $approval_expires_at,
            decision: $decision, review_signal_score: $review_signal_score
        })
        CREATE (proposal)-[:ABOUT_PAYMENT {dataset_id: $dataset_id, synthetic: true}]->(payment)
        CREATE (proposal)-[:BASED_ON {dataset_id: $dataset_id, synthetic: true}]->(run)
        WITH run, proposal
        UNWIND $evidence_rows AS item
        CREATE (evidence:GraphEvidence {
            id: item.id, dataset_id: $dataset_id, synthetic: true,
            query_name: item.query_name, cypher: item.cypher,
            params_json: item.params_json, row_count: item.row_count, summary: item.summary
        })
        CREATE (run)-[:SUPPORTED_BY {dataset_id: $dataset_id, synthetic: true}]->(evidence)
        WITH run, proposal, count(evidence) AS evidence_count
        RETURN run.id AS run_id, proposal.id AS proposal_id, evidence_count
        """
        return self._run("create_synthetic_review_proposal", cypher, {
            "payment_event_id": payment_event_id,
            "dataset_id": self.dataset_id,
            "run_id": run_id,
            "proposal_id": proposal_id,
            "created_by": created_by,
            "approved_at": approved_at,
            "approval_expires_at": approval_expires_at,
            "decision": decision,
            "review_signal_score": float(review_signal_score),
            "evidence_rows": evidence_rows,
        })

    def prior_investigations(self, payment_event_id: str, limit: int = 5) -> QueryObservation:
        safe_limit = max(1, min(int(limit), 10))
        cypher = f"""
        MATCH (run:CorridorInvestigation {{payment_event_id: $payment_event_id,
                                             dataset_id: $dataset_id, synthetic: true}})
        RETURN run {{id: run.id, created_at: run.created_at, decision: run.decision,
                     priority: run.priority, summary: run.summary}} AS prior_run
        ORDER BY run.created_at DESC
        LIMIT {safe_limit}
        """
        return self._run("recall_prior_investigations", cypher, {
            "payment_event_id": payment_event_id,
            "dataset_id": self.dataset_id,
        })
