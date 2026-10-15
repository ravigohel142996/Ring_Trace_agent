"""Evidence-driven temporal payment-corridor investigator.

The planner is deterministic and graph-driven: each follow-up query is chosen
from actual FalkorDB results. Missing/failed queries remain unknown and can
never be translated into "no corridor" evidence.
"""
from __future__ import annotations

from typing import Any, Callable

from eventday.graph import CorridorGraph, GraphQueryError, QueryObservation


SCORE_NOTE = (
    "Review-signal score is a transparent heuristic over observed evidence, "
    "not a calibrated fraud probability."
)


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "item") and callable(value.item):
        try:
            return value.item()
        except (TypeError, ValueError):
            return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class CorridorInvestigator:
    def __init__(self, graph: CorridorGraph):
        self.graph = graph

    def investigate(
        self,
        payment_event_id: str,
        *,
        window_minutes: int = 60,
        max_hops: int = 4,
    ) -> dict[str, Any]:
        if not 1 <= window_minutes <= 1440:
            raise ValueError("window_minutes must be between 1 and 1440")
        if not 1 <= max_hops <= 6:
            raise ValueError("max_hops must be between 1 and 6")

        steps: list[dict[str, Any]] = []
        failed_queries: list[str] = []

        def call(name: str, fn: Callable[[], QueryObservation], summary: str) -> QueryObservation | None:
            try:
                observation = fn()
            except GraphQueryError as exc:
                failed_queries.append(name)
                steps.append({
                    "ok": False,
                    "tool": name,
                    "summary": f"{summary} — query did not complete.",
                    "error": str(exc),
                    "evidence": [{
                        "query_name": exc.name,
                        "cypher": exc.cypher,
                        "params": _jsonable(exc.params),
                        "row_count": None,
                    }],
                })
                return None
            except Exception as exc:  # keep connection/setup failures explicit too
                failed_queries.append(name)
                steps.append({
                    "ok": False,
                    "tool": name,
                    "summary": f"{summary} — graph evidence is unavailable.",
                    "error": str(exc),
                    "evidence": [],
                })
                return None

            steps.append({
                "ok": True,
                "tool": observation.name,
                "summary": f"{summary} ({len(observation.rows)} row(s)).",
                "data": {"rows": _jsonable(observation.rows), "row_count": len(observation.rows)},
                "evidence": [_jsonable(observation.evidence())],
            })
            return observation

        memory = call(
            "recall_prior_investigations",
            lambda: self.graph.prior_investigations(payment_event_id),
            "Read prior investigation memory for this payment event",
        )
        inspect = call(
            "inspect_payment_event",
            lambda: self.graph.inspect_payment(payment_event_id),
            "Inspect the synthetic payment event and its endpoints",
        )
        if inspect is None:
            return self._incomplete(payment_event_id, window_minutes, max_hops, steps, failed_queries)
        if not inspect.rows:
            return {
                "payment_event_id": payment_event_id,
                "dataset_id": self.graph.dataset_id,
                "status": "not_found",
                "decision": "PAYMENT EVENT NOT FOUND IN THE SELECTED SYNTHETIC DATASET",
                "recommended_action": "NO_ACTION",
                "review_signal_score": None,
                "score_note": SCORE_NOTE,
                "window_minutes": window_minutes,
                "max_hops": max_hops,
                "prior_investigations": [],
                "paths": [],
                "signals": [],
                "steps": steps,
                "failed_queries": failed_queries,
            }

        row = inspect.rows[0]
        payment = _jsonable(row[0]) if len(row) > 0 else None
        source_wallet = str(row[1]) if len(row) > 1 and row[1] is not None else ""
        recipient_wallet = str(row[2]) if len(row) > 2 and row[2] is not None else ""
        if not isinstance(payment, dict) or not source_wallet or not recipient_wallet:
            steps.append({
                "ok": False,
                "tool": "validate_payment_event_shape",
                "summary": "FalkorDB returned an incomplete payment record; the investigation cannot safely continue.",
                "error": "invalid_payment_event_result",
                "evidence": [],
            })
            return self._incomplete(payment_event_id, window_minutes, max_hops, steps, failed_queries)

        try:
            anchor_ts = int(payment["occurred_at"])
        except (KeyError, TypeError, ValueError):
            steps.append({
                "ok": False,
                "tool": "validate_payment_timestamp",
                "summary": "The payment timestamp is missing or invalid; no time-bounded conclusion is available.",
                "error": "invalid_payment_timestamp",
                "evidence": [],
            })
            return self._incomplete(payment_event_id, window_minutes, max_hops, steps, failed_queries)

        until_ts = anchor_ts + window_minutes * 60
        corridor = call(
            "trace_time_respecting_corridor",
            lambda: self.graph.trace_corridor(
                recipient_wallet,
                after_ts=anchor_ts,
                until_ts=until_ts,
                max_hops=max_hops,
            ),
            f"Trace strictly time-ordered downstream payments within {window_minutes} minutes",
        )
        if corridor is None:
            return self._incomplete(payment_event_id, window_minutes, max_hops, steps, failed_queries,
                                    payment=payment, source_wallet=source_wallet,
                                    recipient_wallet=recipient_wallet)

        paths: list[dict[str, Any]] = []
        wallet_ids = {source_wallet, recipient_wallet}
        for path_row in corridor.rows:
            if not isinstance(path_row, (list, tuple)) or len(path_row) < 5:
                continue
            wallets = [str(item) for item in (path_row[0] or [])]
            transfers = _jsonable(path_row[1] or [])
            wallet_ids.update(wallets)
            paths.append({
                "wallets": wallets,
                "transfers": transfers,
                "sink_wallet": path_row[2],
                "payout_id": path_row[3],
                "hop_count": int(path_row[4] or 0),
            })

        # The next tools operate on IDs actually returned by the graph, not a
        # hard-coded ring list. With no route, inspect only the observed event's
        # two endpoints rather than pretending a larger component was queried.
        id_list = sorted(wallet_ids)
        devices = call(
            "find_shared_devices",
            lambda: self.graph.shared_devices(id_list),
            "Check whether observed wallets reuse an authentication device",
        )
        owners = call(
            "find_shared_owners",
            lambda: self.graph.shared_owners(id_list),
            "Check whether observed wallets share a beneficial owner",
        )

        ranks = None
        components = None
        if paths:
            ranked_ids = sorted({wallet for path in paths for wallet in path["wallets"]})
            ranks = call(
                "rank_corridor_wallets",
                lambda: self.graph.rank_wallets(ranked_ids),
                "Rank wallets in the observed payment corridor with FalkorDB PageRank",
            )
            components = call(
                "group_coordinated_wallets",
                lambda: self.graph.components(ranked_ids),
                "Check the observed wallets' FalkorDB weak-component membership",
            )

        prior_rows = [] if memory is None else [
            _jsonable(item[0]) for item in memory.rows if isinstance(item, (list, tuple)) and item
        ]
        device_rows = [] if devices is None else _jsonable(devices.rows)
        owner_rows = [] if owners is None else _jsonable(owners.rows)
        rank_rows = [] if ranks is None else _jsonable(ranks.rows)
        component_rows = [] if components is None else _jsonable(components.rows)

        signals: list[dict[str, Any]] = []
        if paths:
            signals.append({
                "kind": "time_respecting_flow",
                "summary": f"{len(paths)} downstream path(s) observed after the anchor payment.",
                "path_count": len(paths),
            })
        payout_paths = [path for path in paths if path.get("payout_id")]
        if payout_paths:
            signals.append({
                "kind": "payout_destination",
                "summary": f"{len(payout_paths)} observed path(s) reach a synthetic payout destination.",
                "payout_ids": sorted({str(path["payout_id"]) for path in payout_paths}),
            })
        if device_rows:
            signals.append({
                "kind": "shared_device",
                "summary": f"{len(device_rows)} shared-device relationship(s) were returned by FalkorDB.",
                "relationships": device_rows,
            })
        if owner_rows:
            signals.append({
                "kind": "shared_beneficial_owner",
                "summary": f"{len(owner_rows)} shared-owner relationship(s) were returned by FalkorDB.",
                "relationships": owner_rows,
            })
        if rank_rows:
            signals.append({
                "kind": "pagerank",
                "summary": "FalkorDB PageRank ranked wallets in the observed corridor.",
                "top_wallet": rank_rows[0][0] if isinstance(rank_rows[0], (list, tuple)) and rank_rows[0] else None,
                "rows": rank_rows,
            })
        if component_rows:
            signals.append({
                "kind": "weak_component",
                "summary": "FalkorDB WCC returned component assignments for corridor wallets.",
                "rows": component_rows,
            })

        all_query_names = {"recall_prior_investigations", "inspect_payment_event",
                           "trace_time_respecting_corridor", "find_shared_devices", "find_shared_owners"}
        if paths:
            all_query_names |= {"rank_corridor_wallets", "group_coordinated_wallets"}
        failed = bool(failed_queries)
        positive_evidence = bool(paths or device_rows or owner_rows)
        identity_corroboration_types = int(bool(device_rows)) + int(bool(owner_rows))
        strong = bool(paths and identity_corroboration_types > 0)
        observed_score = min(1.0, (0.30 if paths else 0.0)
                             + (0.25 if payout_paths else 0.0)
                             + (0.20 if device_rows else 0.0)
                             + (0.25 if owner_rows else 0.0))
        score = None if failed else round(observed_score, 2)

        if failed and not positive_evidence:
            status = "incomplete"
            decision = "INCOMPLETE — GRAPH EVIDENCE UNAVAILABLE; DO NOT INFER ABSENCE"
            action = "NO_ACTION_UNVERIFIED"
        elif strong:
            status = "partial" if failed else "complete"
            decision = "REVIEW RECOMMENDED — TEMPORAL CORRIDOR HAS CORROBORATING GRAPH EVIDENCE"
            action = "CREATE_SIMULATED_REVIEW_PROPOSAL"
        elif positive_evidence:
            status = "partial" if failed else "complete"
            decision = "MONITOR — CONNECTED SIGNAL OBSERVED, CORROBORATION LIMITED"
            action = "NO_ACTION_REQUIRED"
        elif failed:
            status = "incomplete"
            decision = "INCOMPLETE — GRAPH EVIDENCE UNAVAILABLE; DO NOT INFER ABSENCE"
            action = "NO_ACTION_UNVERIFIED"
        else:
            status = "complete"
            decision = f"NO DOWNSTREAM CORRIDOR OBSERVED WITHIN THE {window_minutes}-MINUTE WINDOW"
            action = "NO_ACTION_REQUIRED"

        return {
            "payment_event_id": payment_event_id,
            "dataset_id": self.graph.dataset_id,
            "status": status,
            "payment": payment,
            "source_wallet": source_wallet,
            "recipient_wallet": recipient_wallet,
            "window_minutes": window_minutes,
            "max_hops": max_hops,
            "window_start_ts": anchor_ts,
            "window_end_ts": until_ts,
            "paths": paths,
            "signals": signals,
            "prior_investigations": prior_rows,
            "failed_queries": failed_queries,
            "queries_expected": sorted(all_query_names),
            "review_signal_score": score,
            "score_note": SCORE_NOTE,
            "corroborating_identity_types": identity_corroboration_types,
            "decision": decision,
            "recommended_action": action,
            "can_propose_review": action == "CREATE_SIMULATED_REVIEW_PROPOSAL" and status == "complete",
            "steps": steps,
        }

    @staticmethod
    def _incomplete(
        payment_event_id: str,
        window_minutes: int,
        max_hops: int,
        steps: list[dict[str, Any]],
        failed_queries: list[str],
        *,
        payment: dict[str, Any] | None = None,
        source_wallet: str | None = None,
        recipient_wallet: str | None = None,
    ) -> dict[str, Any]:
        return {
            "payment_event_id": payment_event_id,
            "dataset_id": None,
            "status": "incomplete",
            "payment": payment,
            "source_wallet": source_wallet,
            "recipient_wallet": recipient_wallet,
            "window_minutes": window_minutes,
            "max_hops": max_hops,
            "paths": [],
            "signals": [],
            "prior_investigations": [],
            "failed_queries": failed_queries,
            "review_signal_score": None,
            "score_note": SCORE_NOTE,
            "corroborating_identity_types": 0,
            "decision": "INCOMPLETE — GRAPH EVIDENCE UNAVAILABLE; DO NOT INFER ABSENCE",
            "recommended_action": "NO_ACTION_UNVERIFIED",
            "can_propose_review": False,
            "steps": steps,
        }
