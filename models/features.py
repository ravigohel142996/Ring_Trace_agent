"""
models/features.py
-------------------
Turns live FalkorDB graph structure into a numeric feature vector for the
risk model. EVERY feature here is derived directly from a Cypher query —
there is no feature that comes from a static label. This is what makes the
risk score "graph-derived" rather than a lookup table.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, asdict
from typing import Optional

from graph.queries import GraphStore

FEATURE_NAMES = [
    "degree_linked",
    "out_txn_count",
    "in_txn_count",
    "total_out_amount",
    "total_in_amount",
    "net_flow",
    "pagerank_money",
    "pagerank_identity",
    "component_size",
    "num_shared_devices",
    "num_accounts_sharing_devices",
    "num_shared_ips",
    "num_accounts_sharing_ips",
    "broker_count",
    "hops_to_known_alert",
    "suspicious_neighbor_ratio",
    "has_own_alert",
]


@dataclass
class GraphFeatureCache:
    """Expensive, graph-wide computations (WCC, PageRank) done ONCE and
    reused across many accounts, instead of once per account."""

    component_of: dict
    component_size: dict
    pagerank_money: dict
    pagerank_identity: dict

    @classmethod
    def build(cls, gs: GraphStore) -> "GraphFeatureCache":
        wcc_rows = gs.weakly_connected_components().data
        component_of: dict = {}
        sizes: dict = defaultdict(int)
        for account_id, component_id in wcc_rows:
            component_of[account_id] = component_id
            sizes[component_id] += 1

        pr_money = dict(gs.pagerank("TRANSFERRED_TO").data)
        pr_identity = dict(gs.pagerank("LINKED_TO").data)

        return cls(component_of=component_of, component_size=dict(sizes),
                   pagerank_money=pr_money, pagerank_identity=pr_identity)


def compute_features(gs: GraphStore, account_id: str, cache: Optional[GraphFeatureCache] = None) -> dict:
    """Compute the full graph-derived feature vector for one account.

    Returns a plain dict {feature_name: float}; safe defaults (0.0) are used
    when a quantity cannot be computed (e.g. no alerts anywhere yet).
    """
    cache = cache or GraphFeatureCache.build(gs)

    degree = gs.degree_stats(account_id).data
    out_txn_count = in_txn_count = total_out = total_in = linked_degree = 0
    if degree:
        out_txn_count, total_out, in_txn_count, total_in, linked_degree = degree[0]
        out_txn_count = out_txn_count or 0
        in_txn_count = in_txn_count or 0
        total_out = total_out or 0.0
        total_in = total_in or 0.0
        linked_degree = linked_degree or 0

    broker_rows = gs.broker_count(account_id).data
    broker_count = broker_rows[0][0] if broker_rows else 0

    shared_devices = gs.shared_devices(account_id).data
    num_shared_devices = len(shared_devices)
    num_accounts_sharing_devices = len({a for row in shared_devices for a in row[2]})

    shared_ips = gs.shared_ips(account_id).data
    num_shared_ips = len(shared_ips)
    num_accounts_sharing_ips = len({a for row in shared_ips for a in row[2]})

    hops_rows = gs.hops_to_nearest_alert(account_id).data
    hops_to_alert = hops_rows[0][0] if hops_rows and hops_rows[0][0] is not None else 99

    ratio_rows = gs.suspicious_neighbor_ratio(account_id).data
    suspicious_ratio = 0.0
    if ratio_rows and ratio_rows[0][0]:
        total_neighbors, alerted_neighbors = ratio_rows[0]
        suspicious_ratio = (alerted_neighbors or 0) / total_neighbors if total_neighbors else 0.0

    component_id = cache.component_of.get(account_id)
    component_size = cache.component_size.get(component_id, 1)

    own_alert_rows = gs.own_alert_count(account_id).data
    has_own_alert = 1.0 if (own_alert_rows and own_alert_rows[0][0]) else 0.0

    features = {
        "degree_linked": float(linked_degree),
        "out_txn_count": float(out_txn_count),
        "in_txn_count": float(in_txn_count),
        "total_out_amount": float(total_out),
        "total_in_amount": float(total_in),
        "net_flow": float(total_in) - float(total_out),
        "pagerank_money": float(cache.pagerank_money.get(account_id, 0.0)),
        "pagerank_identity": float(cache.pagerank_identity.get(account_id, 0.0)),
        "component_size": float(component_size),
        "num_shared_devices": float(num_shared_devices),
        "num_accounts_sharing_devices": float(num_accounts_sharing_devices),
        "num_shared_ips": float(num_shared_ips),
        "num_accounts_sharing_ips": float(num_accounts_sharing_ips),
        "broker_count": float(broker_count),
        "hops_to_known_alert": float(min(hops_to_alert, 99)),
        "suspicious_neighbor_ratio": float(suspicious_ratio),
        "has_own_alert": has_own_alert,
    }
    return features
