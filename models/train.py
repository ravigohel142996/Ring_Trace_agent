"""
models/train.py
----------------
Trains a lightweight, explainable RandomForest risk classifier on
GRAPH-DERIVED features, using the SYNTHETIC ground-truth labels produced by
`ingestion/generate_synthetic_data.py`.

*** This is a synthetic-data evaluation. *** Metrics reported here describe
how well the model recovers the synthetic ring structure we planted — they
make NO claim about real-world fraud detection performance.
"""
from __future__ import annotations

import csv
import hashlib
import json
import logging
import time
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    precision_recall_fscore_support,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split

from graph.connection import get_graph
from models.features import FEATURE_NAMES, GraphFeatureCache, compute_features
from graph.queries import GraphStore

logger = logging.getLogger("ringtrace.models.train")
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")

ROOT = Path(__file__).resolve().parent.parent
GROUND_TRUTH_PATH = ROOT / "data" / "processed" / "ground_truth.csv"
MODEL_PATH = ROOT / "models" / "risk_model.joblib"
EVAL_REPORT_PATH = ROOT / "evaluation" / "synthetic_eval_report.json"


def load_ground_truth() -> pd.DataFrame:
    if not GROUND_TRUTH_PATH.exists():
        raise FileNotFoundError(
            f"{GROUND_TRUTH_PATH} not found. Run `python -m ingestion.load_to_falkordb` first."
        )
    return pd.read_csv(GROUND_TRUTH_PATH)


def build_training_frame(gs: GraphStore, account_ids: list[str]) -> pd.DataFrame:
    t0 = time.time()
    cache = GraphFeatureCache.build(gs)
    rows = []
    for aid in account_ids:
        feats = compute_features(gs, aid, cache=cache)
        feats["account_id"] = aid
        rows.append(feats)
    logger.info("Computed features for %d accounts in %.2fs", len(rows), time.time() - t0)
    return pd.DataFrame(rows)


def train(test_size: float = 0.25, random_state: int = 42) -> dict:
    gt = load_ground_truth()
    graph = get_graph()
    gs = GraphStore(graph)

    feat_df = build_training_frame(gs, gt["account_id"].tolist())
    df = feat_df.merge(gt, on="account_id", how="inner")

    X = df[FEATURE_NAMES]
    y = df["is_fraud"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=random_state, stratify=y if y.nunique() > 1 else None
    )

    clf = RandomForestClassifier(
        n_estimators=200, max_depth=8, min_samples_leaf=2,
        class_weight="balanced", random_state=random_state,
    )
    clf.fit(X_train, y_train)

    y_pred = clf.predict(X_test)
    y_proba = clf.predict_proba(X_test)[:, 1]

    precision, recall, f1, _ = precision_recall_fscore_support(y_test, y_pred, average="binary", zero_division=0)
    acc = accuracy_score(y_test, y_pred)
    try:
        auc = roc_auc_score(y_test, y_proba) if y_test.nunique() > 1 else float("nan")
    except ValueError:
        auc = float("nan")

    importances = dict(zip(FEATURE_NAMES, clf.feature_importances_.tolist()))

    report = {
        "disclaimer": "SYNTHETIC DATA EVALUATION ONLY. Not a claim of real-world fraud-detection accuracy.",
        "score_interpretation": (
            "Reported classifier metrics are synthetic holdout results. Per-account "
            "predict_proba outputs are raw model scores, not calibrated real-world fraud probabilities."
        ),
        "reproducibility": {
            "split_method": "stratified sklearn.model_selection.train_test_split",
            "test_size": float(test_size),
            "random_state": int(random_state),
            "ground_truth_sha256": hashlib.sha256(GROUND_TRUTH_PATH.read_bytes()).hexdigest(),
            "feature_names": list(FEATURE_NAMES),
            "classifier": {
                "type": "RandomForestClassifier",
                "n_estimators": 200,
                "max_depth": 8,
                "min_samples_leaf": 2,
                "class_weight": "balanced",
                "random_state": int(random_state),
            },
        },
        "n_ground_truth_rows": int(len(gt)),
        "n_accounts_total": int(len(df)),
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "fraud_ratio_in_data": float(y.mean()),
        "accuracy": float(acc),
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "roc_auc": None if pd.isna(auc) else float(auc),
        "feature_importances": importances,
        "classification_report": classification_report(y_test, y_pred, zero_division=0, output_dict=True),
        "feature_means": {f: float(X[f].mean()) for f in FEATURE_NAMES},
        "feature_stds": {f: float(X[f].std() or 1e-6) for f in FEATURE_NAMES},
    }

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({
        "model": clf,
        "feature_names": FEATURE_NAMES,
        "feature_means": report["feature_means"],
        "feature_stds": report["feature_stds"],
    }, MODEL_PATH)

    EVAL_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(EVAL_REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)

    logger.info("Model saved to %s", MODEL_PATH)
    logger.info("Synthetic evaluation: acc=%.3f precision=%.3f recall=%.3f f1=%.3f auc=%s",
                acc, precision, recall, f1, report["roc_auc"])
    return report


if __name__ == "__main__":
    train()
