"""
models/risk_scorer.py
----------------------
Loads the trained RandomForest model and scores a single account using its
live, freshly-computed graph features. Produces a risk score, a risk class,
and a simple, honest feature-attribution explanation
(importance x standardized deviation from the training-set baseline) —
NOT a claim of exact SHAP values, just a transparent, reproducible heuristic.

If no trained model is available (e.g. a brand-new checkout before
`scripts/run_pipeline.sh` has been run), falls back to a deterministic,
rule-based heuristic score so the agent never crashes.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import joblib
import pandas as pd

from graph.queries import GraphStore
from models.features import FEATURE_NAMES, GraphFeatureCache, compute_features

logger = logging.getLogger("ringtrace.models.risk_scorer")

MODEL_PATH = Path(__file__).resolve().parent / "risk_model.joblib"

RISK_BANDS = [
    (0.80, "CRITICAL"),
    (0.55, "HIGH"),
    (0.30, "MEDIUM"),
    (0.0, "LOW"),
]


def _risk_class(score: float) -> str:
    for threshold, label in RISK_BANDS:
        if score >= threshold:
            return label
    return "LOW"


def _heuristic_score(features: dict) -> float:
    """Deterministic fallback used only if no trained model exists yet."""
    score = 0.0
    score += min(features.get("component_size", 1) / 12.0, 1.0) * 0.30
    score += min(features.get("num_accounts_sharing_devices", 0) / 6.0, 1.0) * 0.20
    score += min(features.get("num_accounts_sharing_ips", 0) / 6.0, 1.0) * 0.15
    score += (1.0 if features.get("hops_to_known_alert", 99) <= 3 else 0.0) * 0.20
    score += min(features.get("suspicious_neighbor_ratio", 0.0), 1.0) * 0.15
    return max(0.0, min(1.0, score))


def _graph_evidence_strength(features: dict) -> float:
    """A small, transparent, RULE-BASED corroboration signal computed
    directly from graph features. This exists so the final risk score can
    never be driven to HIGH/CRITICAL purely by ML noise on an account that
    the graph shows has no suspicious connections whatsoever — graph
    evidence is the ultimate arbiter of RingTrace's decisions, not a
    black-box classifier trained on a necessarily small synthetic sample.
    Returns a 0..~6 "evidence points" score; 0 means no corroborating signal."""
    points = 0.0
    points += min(features.get("num_accounts_sharing_devices", 0), 3)
    points += min(features.get("num_accounts_sharing_ips", 0), 3)
    points += 2.0 if features.get("has_own_alert", 0) >= 1 else 0.0
    points += 1.5 if features.get("hops_to_known_alert", 99) <= 4 else 0.0
    points += 1.0 if features.get("component_size", 1) >= 4 else 0.0
    points += 1.0 if features.get("broker_count", 0) >= 1 else 0.0
    points += 1.0 if features.get("suspicious_neighbor_ratio", 0.0) >= 0.2 else 0.0
    return points


class RiskScorer:
    def __init__(self, model_path: Path = MODEL_PATH):
        self.model_path = model_path
        self._bundle = None
        if model_path.exists():
            try:
                self._bundle = joblib.load(model_path)
                logger.info("Loaded trained risk model from %s", model_path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not load risk model (%s); using heuristic fallback.", exc)
        else:
            logger.warning("No trained model at %s; using heuristic fallback until `python -m models.train` runs.",
                            model_path)

    @property
    def is_trained(self) -> bool:
        return self._bundle is not None

    def score_account(self, gs: GraphStore, account_id: str, cache: Optional[GraphFeatureCache] = None) -> dict:
        cache = cache or GraphFeatureCache.build(gs)
        features = compute_features(gs, account_id, cache=cache)

        if self._bundle is not None:
            model = self._bundle["model"]
            feature_names = self._bundle["feature_names"]
            means = self._bundle["feature_means"]
            stds = self._bundle["feature_stds"]
            x = pd.DataFrame([[features[f] for f in feature_names]], columns=feature_names)
            proba = float(model.predict_proba(x)[0][1])
            importances = dict(zip(feature_names, model.feature_importances_.tolist()))

            contributions = []
            for f in feature_names:
                dev = (features[f] - means.get(f, 0.0)) / (stds.get(f, 1e-6) or 1e-6)
                contributions.append((f, importances.get(f, 0.0) * dev, features[f]))
            contributions.sort(key=lambda t: abs(t[1]), reverse=True)
            top_features = [
                {"feature": f, "value": v, "attribution": round(attr, 4)}
                for f, attr, v in contributions[:5]
            ]
            method = "random_forest (synthetic-data trained)"
        else:
            proba = _heuristic_score(features)
            top_features = sorted(
                ({"feature": k, "value": v, "attribution": None} for k, v in features.items()),
                key=lambda d: d["value"], reverse=True,
            )[:5]
            method = "rule_based_heuristic (no trained model found)"

        evidence_points = _graph_evidence_strength(features)
        money_flow_volume = features.get("total_in_amount", 0.0) + features.get("total_out_amount", 0.0)
        has_money_trail = money_flow_volume >= 500 or features.get("broker_count", 0) >= 1
        near_known_alert = features.get("hops_to_known_alert", 99) <= 4 or features.get("has_own_alert", 0) >= 1

        raw_score = proba
        adjusted_score = proba
        guardrail_applied = False
        if evidence_points <= 0.0:
            # Zero corroborating graph evidence -> the graph does not support
            # a high-risk verdict no matter what the classifier output says.
            adjusted_score = min(proba, 0.20)
            guardrail_applied = adjusted_score < raw_score
        elif evidence_points < 1.5:
            adjusted_score = min(proba, 0.55)
            guardrail_applied = adjusted_score < raw_score
        elif not has_money_trail and not near_known_alert:
            # Identity-linked (shared device/IP) but NO evidence of an actual
            # money-laundering flow and no nearby alert yet: cap at HIGH, not
            # CRITICAL. This is exactly RingTrace's Case A/B/C distinction —
            # identity links alone raise risk, but a corroborated money trail
            # is what pushes a verdict to CRITICAL/ESCALATE.
            adjusted_score = min(proba, 0.72)
            guardrail_applied = adjusted_score < raw_score

        return {
            "account_id": account_id,
            "risk_score": round(adjusted_score, 4),
            "risk_class": _risk_class(adjusted_score),
            "raw_model_score": round(raw_score, 4),
            "graph_evidence_points": evidence_points,
            "graph_guardrail_applied": guardrail_applied,
            "method": method,
            "top_contributing_features": top_features,
            "all_features": features,
        }
