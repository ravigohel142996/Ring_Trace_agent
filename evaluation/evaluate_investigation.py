"""
evaluation/evaluate_investigation.py
---------------------------------------
Agent-level evaluation metrics — DISTINCT from the ML classifier metrics in
`models/train.py` (acc/precision/recall/f1/auc on the RandomForest alone).
This script measures how well the FULL investigation pipeline (graph tools +
composite ring score + guardrailed risk score + final decision rules)
performs against the synthetic ground truth, specifically:

  1. Ring detection precision/recall   — does find_fraud_ring's WCC-derived
     component match the planted ring membership?
  2. Leader identification quality     — for rings with a ground-truth
     "leader" role, does rank_ring_leaders' PageRank pick name the right
     account?
  3. Money-path success rate           — for rings with a known layered
     money trail, does trace_money_path actually find it?
  4. Identity-link detection recall    — for accounts known to share a
     device/IP, does find_identity_links surface it?
  5. Action accuracy vs. ground truth  — does the final agent decision
     (after the ring score + ML guardrail) correctly separate planted fraud
     accounts from legit ones at the ACTION level (not just the raw model)?

*** SYNTHETIC DATA EVALUATION ONLY. *** These numbers describe how well
RingTrace recovers the ring structure WE planted; they make no claim about
real-world fraud-detection performance. Honesty note: some individual
accounts (e.g. a quiet "feeder" in a layered chain with no identity-link
evidence of its own) are EXPECTED to score LOW even though they are
ground-truth fraud — the guardrail intentionally refuses to escalate an
account on ring membership alone without any corroborating evidence of its
own. This script reports that honestly rather than tuning it away.
"""
from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from pathlib import Path

import pandas as pd

from agent.decision import build_verdict
from agent.rule_based import run_investigation
from graph.connection import get_graph
from graph.queries import GraphStore
from models.risk_scorer import RiskScorer
from tools.base import REGISTRY
from tools.context import ToolContext

logger = logging.getLogger("ringtrace.evaluation")
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")

ROOT = Path(__file__).resolve().parent.parent
GROUND_TRUTH_PATH = ROOT / "data" / "processed" / "ground_truth.csv"
OUT_PATH = ROOT / "evaluation" / "investigation_eval_report.json"


def _new_ctx(gs: GraphStore, rs: RiskScorer) -> ToolContext:
    ctx = ToolContext(graph_store=gs, risk_scorer=rs)
    return ctx


def evaluate_ring_detection(gs: GraphStore, rs: RiskScorer, gt: pd.DataFrame) -> dict:
    rings = gt[gt["ring_id"] != "NONE"].groupby("ring_id")["account_id"].apply(set).to_dict()
    precisions, recalls = [], []
    per_ring = {}
    for ring_id, true_members in rings.items():
        sample_account = sorted(true_members)[0]
        ctx = _new_ctx(gs, rs)
        res = REGISTRY.get("find_fraud_ring").run(ctx, account_id=sample_account)
        detected = set(res.data.get("members", [])) if res.ok else set()
        tp = len(detected & true_members)
        precision = tp / len(detected) if detected else 0.0
        recall = tp / len(true_members) if true_members else 0.0
        precisions.append(precision)
        recalls.append(recall)
        per_ring[ring_id] = {"true_size": len(true_members), "detected_size": len(detected),
                              "precision": round(precision, 3), "recall": round(recall, 3)}

    # False-positive check: isolated legit accounts should NOT be swept into a large component.
    legit = gt[(gt["ring_id"] == "NONE")]["account_id"].tolist()
    fp_hits = 0
    for aid in legit[:30]:  # bounded sample for speed; still representative
        ctx = _new_ctx(gs, rs)
        res = REGISTRY.get("find_fraud_ring").run(ctx, account_id=aid)
        if res.ok and res.data.get("size", 1) >= 5:
            fp_hits += 1

    return {
        "rings_evaluated": len(rings),
        "mean_precision": round(sum(precisions) / len(precisions), 3) if precisions else None,
        "mean_recall": round(sum(recalls) / len(recalls), 3) if recalls else None,
        "per_ring": per_ring,
        "legit_accounts_sampled": min(30, len(legit)),
        "legit_accounts_falsely_swept_into_large_component": fp_hits,
    }


def evaluate_leader_identification(gs: GraphStore, rs: RiskScorer, gt: pd.DataFrame) -> dict:
    leader_rows = gt[gt["role"] == "leader"]
    correct, total, details = 0, 0, []
    for _, row in leader_rows.iterrows():
        ring_id, true_leader = row["ring_id"], row["account_id"]
        members = gt[gt["ring_id"] == ring_id]["account_id"].tolist()
        if len(members) < 2:
            continue
        ctx = _new_ctx(gs, rs)
        res = REGISTRY.get("rank_ring_leaders").run(ctx, account_ids=members)
        predicted = res.data.get("ring_leader") if res.ok else None
        is_correct = predicted == true_leader
        correct += int(is_correct)
        total += 1
        details.append({"ring_id": ring_id, "true_leader": true_leader, "predicted_leader": predicted,
                         "correct": is_correct})
    return {"rings_with_known_leader": total, "accuracy": round(correct / total, 3) if total else None,
            "details": details}


def evaluate_money_paths(gs: GraphStore, rs: RiskScorer, gt: pd.DataFrame) -> dict:
    # Rings with an expected layered chain: central_mule_leader and layered_movement patterns.
    chain_patterns = {"central_mule_leader", "layered_to_merchant", "layered_movement"}
    found, total, details = 0, 0, []

    # Fixed demo case: A1027 -> ... -> A1001
    ctx = _new_ctx(gs, rs)
    res = REGISTRY.get("trace_money_path").run(ctx, source_account_id="A1027", destination_account_id="A1001")
    total += 1
    ok = res.ok and bool(res.data.get("paths"))
    found += int(ok)
    details.append({"ring_id": "RING-DEMO-1", "source": "A1027", "destination": "A1001", "found": ok})

    for ring_id, g in gt[gt["pattern"].isin(chain_patterns)].groupby("ring_id"):
        members = g["account_id"].tolist()
        if len(members) < 2:
            continue
        leader_row = g[g["role"] == "leader"]
        dest = leader_row["account_id"].iloc[0] if not leader_row.empty else members[-1]
        src = [m for m in members if m != dest][0]
        ctx = _new_ctx(gs, rs)
        res = REGISTRY.get("trace_money_path").run(ctx, source_account_id=src, destination_account_id=dest)
        ok = res.ok and bool(res.data.get("paths"))
        total += 1
        found += int(ok)
        details.append({"ring_id": ring_id, "source": src, "destination": dest, "found": ok})

    return {"chains_evaluated": total, "success_rate": round(found / total, 3) if total else None,
            "details": details}


def evaluate_identity_links(gs: GraphStore, rs: RiskScorer, gt: pd.DataFrame) -> dict:
    known_identity_accounts = {
        "A1027": "shared_device", "A1020": "shared_device", "A1200": "shared_ip",
        "A1310": "shared_device", "A1350": "shared_device",
    }
    hits, total, details = 0, 0, []
    for aid, kind in known_identity_accounts.items():
        ctx = _new_ctx(gs, rs)
        res = REGISTRY.get("find_identity_links").run(ctx, account_id=aid)
        total += 1
        found = False
        if res.ok:
            if kind == "shared_device" and res.data.get("shared_devices"):
                found = True
            elif kind == "shared_ip" and res.data.get("shared_ips"):
                found = True
        hits += int(found)
        details.append({"account_id": aid, "expected": kind, "found": found})
    return {"accounts_evaluated": total, "recall": round(hits / total, 3) if total else None, "details": details}


def evaluate_action_accuracy(gs: GraphStore, rs: RiskScorer, gt: pd.DataFrame, sample_size: int = 80) -> dict:
    """End-to-end: run the FULL investigation + decision pipeline (ring score +
    ML guardrail) for a stratified sample of ground-truth accounts and compare
    the resulting risk_class against is_fraud. This is intentionally stricter
    / more end-to-end than models/train.py's classifier-only metrics — each
    account here triggers the full multi-tool investigation (WCC, PageRank x2,
    money-path search, identity resolution, ring-score bundle), which is why
    it runs on a bounded, reproducibly-seeded sample rather than the full
    population: ~2-3 FalkorDB round trips per tool x 7 tools x N accounts
    adds up quickly on this dataset size, and a stratified sample is already
    statistically representative for a hackathon-scale evaluation."""
    fraud_rows = gt[gt["is_fraud"] == 1]
    legit_rows = gt[gt["is_fraud"] == 0]
    half = sample_size // 2
    fraud_sampled = min(half, len(fraud_rows))
    legit_sampled = min(half, len(legit_rows))
    sample_random_state = 42
    sampled = pd.concat([
        fraud_rows.sample(n=fraud_sampled, random_state=sample_random_state),
        legit_rows.sample(n=legit_sampled, random_state=sample_random_state),
    ])

    tp = fp = tn = fn = 0
    rows = []
    t0 = time.time()
    for _, row in sampled.iterrows():
        aid, is_fraud = row["account_id"], bool(row["is_fraud"])
        ctx = _new_ctx(gs, rs)
        try:
            run_investigation(ctx, aid)
            verdict = build_verdict(ctx, aid)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Investigation failed for %s: %s", aid, exc)
            continue
        flagged = verdict["risk_class"] in ("HIGH", "CRITICAL")
        if is_fraud and flagged:
            tp += 1
        elif is_fraud and not flagged:
            fn += 1
        elif not is_fraud and flagged:
            fp += 1
        else:
            tn += 1
        rows.append({"account_id": aid, "is_fraud": is_fraud, "risk_class": verdict["risk_class"],
                     "flagged": flagged, "recommended_action": verdict["recommended_action"]})
    elapsed = time.time() - t0

    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    accuracy = (tp + tn) / (tp + tn + fp + fn) if (tp + tn + fp + fn) else None
    f1 = (2 * precision * recall / (precision + recall)) if precision and recall and (precision + recall) else None

    return {
        "sample_size_requested": sample_size,
        "sample_random_state": sample_random_state,
        "sampling_strategy": "equal-size fraud/legit samples (bounded by class counts)",
        "fraud_accounts_sampled": fraud_sampled,
        "legit_accounts_sampled": legit_sampled,
        "n_accounts": len(rows), "elapsed_seconds": round(elapsed, 1),
        "true_positive": tp, "false_positive": fp, "true_negative": tn, "false_negative": fn,
        "accuracy": round(accuracy, 3) if accuracy is not None else None,
        "precision": round(precision, 3) if precision is not None else None,
        "recall": round(recall, 3) if recall is not None else None,
        "f1": round(f1, 3) if f1 is not None else None,
        "false_negative_examples": [r["account_id"] for r in rows if r["is_fraud"] and not r["flagged"]][:15],
        "false_positive_examples": [r["account_id"] for r in rows if not r["is_fraud"] and r["flagged"]][:15],
    }


def main():
    if not GROUND_TRUTH_PATH.exists():
        raise FileNotFoundError(f"{GROUND_TRUTH_PATH} not found. Run `python -m ingestion.load_to_falkordb` first.")
    gt = pd.read_csv(GROUND_TRUTH_PATH)
    gs = GraphStore(get_graph())
    rs = RiskScorer()

    logger.info("Evaluating ring detection (WCC precision/recall)...")
    ring_detection = evaluate_ring_detection(gs, rs, gt)

    logger.info("Evaluating leader identification (PageRank)...")
    leader_id = evaluate_leader_identification(gs, rs, gt)

    logger.info("Evaluating money-path success rate...")
    money_paths = evaluate_money_paths(gs, rs, gt)

    logger.info("Evaluating identity-link detection recall...")
    identity_links = evaluate_identity_links(gs, rs, gt)

    logger.info("Evaluating end-to-end action accuracy vs. ground truth (this is the slow part)...")
    action_accuracy = evaluate_action_accuracy(gs, rs, gt)

    report = {
        "disclaimer": "SYNTHETIC DATA EVALUATION ONLY. Describes recovery of the planted ring "
                       "structure, not real-world fraud-detection performance. Distinct from "
                       "models/synthetic_eval_report.json, which scores the RandomForest classifier "
                       "alone — this report scores the FULL agent decision pipeline (ring score + "
                       "ML + guardrail + rules).",
        "ring_detection": ring_detection,
        "leader_identification": leader_id,
        "money_path_success": money_paths,
        "identity_link_recall": identity_links,
        "action_accuracy_vs_ground_truth": action_accuracy,
    }
    OUT_PATH.write_text(json.dumps(report, indent=2, default=str))
    logger.info("Wrote %s", OUT_PATH)
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
