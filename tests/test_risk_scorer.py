"""
tests/test_risk_scorer.py
----------------------------
Unit tests (no FalkorDB required) for the graph-evidence guardrail logic in
models/risk_scorer.py — this is the mechanism that keeps the ML score
honest: an isolated account can never be scored CRITICAL no matter what a
noisy model predicts, and identity-only linkage (no money trail, no alert)
is capped below CRITICAL.
"""
from __future__ import annotations

from models.risk_scorer import _graph_evidence_strength


def _features(**overrides):
    base = dict(
        degree=0, weighted_degree=0.0, pagerank=0.0, num_connected_accounts=0,
        num_accounts_sharing_devices=0, num_accounts_sharing_ips=0,
        transaction_count=0, total_transaction_amount=0.0, hops_to_known_alert=99,
        broker_count=0, component_size=1, suspicious_neighbor_ratio=0.0, has_own_alert=0,
    )
    base.update(overrides)
    return base


def test_isolated_account_has_zero_evidence():
    assert _graph_evidence_strength(_features()) == 0.0


def test_shared_devices_increase_evidence():
    low = _graph_evidence_strength(_features())
    high = _graph_evidence_strength(_features(num_accounts_sharing_devices=5, component_size=6))
    assert high > low


def test_alert_and_ring_evidence_is_strongest():
    strong = _graph_evidence_strength(_features(
        num_accounts_sharing_devices=7, has_own_alert=1, hops_to_known_alert=1,
        component_size=9, broker_count=1, suspicious_neighbor_ratio=0.8,
    ))
    assert strong >= 4.0
