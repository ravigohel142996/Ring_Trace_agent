# Event-day contribution — Track 01 proposal

**Status: implementation draft; graph/browser/Docker/demo verification not yet complete.**

This document is deliberately separate from the project's existing RingTrace account-investigation implementation. It describes a proposed event-day contribution built under `eventday/` and the new **Payment corridor** page. No claim of organizer approval, public publication, or completed event eligibility review is made.

## Provenance and eligibility

The repository contains a substantial pre-existing RingTrace implementation and history, including its original account graph, ring-detection queries, risk model, tools, API, and interface. Those files and commits must remain represented as pre-event work; they are not relabelled as hackathon work. The distinct event-day code for this proposal is under `eventday/`, `tests/test_eventday_*.py`, `tests/eventday/`, and `frontend/src/pages/CorridorPage.tsx` plus its API/client/styles integration.

The supplied rules excerpt asked whether existing projects may continue but omitted its answer. **Existing-project eligibility is therefore unresolved.** Ask the organizers for written clarification before treating this repository as an eligible submission. A separate event-day graph core reduces technical overlap but does not itself prove eligibility. Do not publish the private repository or submit on the team's behalf without the team's deliberate eligibility, full-history secret, licensing, and contribution review.

## Track declaration

**Proposed track: Track 01 — Agents That Act on Connected Data.** FalkorDB is intended to be the primary source of connected payment evidence for this workflow. The planner reads actual Cypher results, changes its follow-up query set based on the returned paths, and uses FalkorDB graph algorithms on the observed corridor. The only write is a separately authenticated, approved, explicitly confirmed **simulated manual-review proposal** attached to synthetic graph records; no payment is frozen, sent, or otherwise changed.

## Workflow

1. Select a synthetic `PaymentEvent` and choose the downstream time window and maximum hop count.
2. Read the event's source and recipient from FalkorDB.
3. From the recipient, traverse `FUNDED_TO` edges that are synthetic, inside the specified window, and strictly increasing in event time. Return the actual wallet path, transfer IDs/amounts/timestamps, sink and any payout destination.
4. Only after that result, query shared devices and beneficial owners for wallet IDs returned by the graph. If paths exist, run FalkorDB PageRank/WCC on the isolated event-day graph and return algorithm rows for the observed corridor wallets. These are data-dependent follow-up calls, not prerecorded answers.
5. Show exact Cypher, bound parameters, row counts, errors, and returned rows. A failed query is unknown, never an empty-result fraud/safety conclusion.
6. Present a bounded, transparent review-signal heuristic (not a calibrated fraud probability). A corroborated path may allow a human to propose review; the agent does not make a fraud finding.
7. To write, the same configured analyst must authenticate, approve the time-limited proposal, and confirm a second time. One query writes only synthetic `CorridorInvestigation`, `ReviewProposal`, and `GraphEvidence` nodes/edges. No external side effect occurs.

## Event-day graph model

Every node and relationship written by the fixture carries `dataset_id` and `synthetic=true` (except where data is returned read-only). The fixture is fixed, public-in-repository demo data; do not import customer, personal, restricted, or login-protected records.

| Label | Key properties | Purpose |
|---|---|---|
| `Wallet` | `id`, `dataset_id`, `synthetic` | Payment endpoints and corridor stops |
| `PaymentEvent` | `id`, `dataset_id`, `synthetic`, `occurred_at` (UTC epoch seconds), `amount`, `currency`, `channel` | Immutable event anchor and payment identity |
| `Device` | `id`, `dataset_id`, `synthetic` | Synthetic authentication-link evidence |
| `BeneficialOwner` | `id`, `dataset_id`, `synthetic` | Synthetic ownership-link evidence |
| `PayoutDestination` | `id`, `dataset_id`, `synthetic`, `kind` | Synthetic cash-out sink |
| `CorridorInvestigation` | `id`, `payment_event_id`, `dataset_id`, `synthetic`, `created_at`, `decision`, heuristic score | Graph-backed investigation memory; created on a confirmed proposal write |
| `ReviewProposal` | `id`, `payment_event_id`, `dataset_id`, `synthetic`, `status`, analyst and approval metadata | Simulated human-review proposal only |
| `GraphEvidence` | `id`, `dataset_id`, `synthetic`, `query_name`, `cypher`, `params_json`, `row_count`, `summary` | Successful query provenance supporting a proposal |

| Relationship | Direction | Properties / meaning |
|---|---|---|
| `FROM` | `PaymentEvent → Wallet` | Event source |
| `TO` | `PaymentEvent → Wallet` | Event recipient |
| `FUNDED_TO` | `Wallet → Wallet` | One payment-flow projection; `event_id`, `occurred_at`, `amount`, `currency` |
| `CASHED_OUT_TO` | `Wallet → PayoutDestination` | Synthetic payout endpoint |
| `AUTHENTICATED_ON` | `Wallet → Device` | Shared-device evidence |
| `CONTROLS` | `BeneficialOwner → Wallet` | Shared-owner evidence |
| `COORDINATED_WITH` | `Wallet → Wallet` | Materialized identity-link projection for WCC |
| `ANALYZED_PAYMENT` | `CorridorInvestigation → PaymentEvent` | Investigation provenance |
| `ABOUT_PAYMENT` | `ReviewProposal → PaymentEvent` | Proposal subject |
| `BASED_ON` | `ReviewProposal → CorridorInvestigation` | Proposal's graph-run provenance |
| `SUPPORTED_BY` | `CorridorInvestigation → GraphEvidence` | Exact successful Cypher provenance |

## Cypher and graph-native analysis

The parameterized query in `eventday/graph.py::trace_corridor` uses a validated integer hop bound (`1..6`) as the only interpolated query fragment; event IDs, dataset ID, and time bounds are bound parameters. Its key predicate is:

```cypher
MATCH path = (start:Wallet {id: $wallet_id, dataset_id: $dataset_id, synthetic: true})
              -[:FUNDED_TO*1..4]->
              (sink:Wallet {dataset_id: $dataset_id, synthetic: true})
WITH path, relationships(path) AS legs, sink
WHERE all(r IN legs WHERE r.dataset_id = $dataset_id
          AND r.synthetic = true
          AND r.occurred_at > $after_ts
          AND r.occurred_at <= $until_ts)
  AND CASE WHEN size(legs) < 2 THEN true
           ELSE all(i IN range(0, size(legs) - 2)
                    WHERE legs[i].occurred_at < legs[i + 1].occurred_at)
      END
OPTIONAL MATCH (sink)-[:CASHED_OUT_TO {dataset_id: $dataset_id, synthetic: true}]->
               (payout:PayoutDestination {dataset_id: $dataset_id, synthetic: true})
RETURN [n IN nodes(path) | n.id] AS wallets,
       [r IN legs | {event_id: r.event_id, amount: r.amount,
                     currency: r.currency, occurred_at: r.occurred_at}] AS transfers,
       sink.id AS sink_wallet, payout.id AS payout_id, size(legs) AS hop_count
LIMIT 20;
```

The source code builds the hop bound from a validated `max_hops`; all other values are supplied in a parameter map. This is a time-respecting walk: every transfer is later than the anchor and every next transfer is later than its predecessor. It is not a generic shortest-path query.

Conditional graph algorithms in the implementation:

```cypher
CALL algo.pageRank('Wallet', 'FUNDED_TO') YIELD node, score
WITH node, score
WHERE node.dataset_id = $dataset_id AND node.synthetic = true
  AND node.id IN $wallet_ids
RETURN node.id AS wallet_id, score AS page_rank
ORDER BY page_rank DESC;

CALL algo.WCC({nodeLabels: ['Wallet'], relationshipTypes: ['COORDINATED_WITH']})
YIELD node, componentId
WITH node, componentId
WHERE node.dataset_id = $dataset_id AND node.synthetic = true
  AND node.id IN $wallet_ids
RETURN node.id AS wallet_id, componentId;
```

PageRank is a graph-centrality signal, not proof of culpability. WCC exposes the graph's identity-link component, not a fraud label. Shared-device/owner evidence can be benign; corroboration, limitations, and all failed calls are disclosed to the analyst.

## Local setup (isolated graph only)

Prerequisites: Python 3.11+, Node.js/npm, Docker, and a free loopback port **6380**. Do not point this guide at the preview's legacy graph, a shared/team graph, or port 6379. Check that no unrelated process/container owns 6380 before starting the disposable database. This setup is not run/verified in the current workspace session.

```bash
# Repository root: /home/user/Ring_Trace_agent
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt

cd frontend
npm ci
npm run build
cd ..

# Only after verifying port 6380 is free, start a separate disposable database.
docker run --rm -d --name ringtrace-eventday-falkordb \
  -p 127.0.0.1:6380:6379 falkordb/falkordb:latest

# Enable only this dedicated event-day graph connection.
export RINGTRACE_EVENTDAY_ENABLED=1
export RINGTRACE_EVENTDAY_DISPOSABLE=1
export RINGTRACE_EVENTDAY_FALKORDB_HOST=127.0.0.1
export RINGTRACE_EVENTDAY_FALKORDB_PORT=6380
export RINGTRACE_EVENTDAY_GRAPH=ringtrace_eventday_test

# Keep the pre-existing graph routes from attempting a default localhost:6379 probe.
export FALKORDB_HOST=127.0.0.1
export FALKORDB_PORT=1

# For the simulated write gate, load RINGTRACE_AUTH_SECRET,
# RINGTRACE_DEMO_USERNAME, and RINGTRACE_DEMO_PASSWORD via an approved
# local secret manager/runtime environment. Never echo or commit their values.

# First perform the gated read-only endpoint/empty-graph preflight; the
# integration module seeds the fixture only after both graph counts are zero.
export RINGTRACE_TEST_DISPOSABLE=1
pytest -q tests/eventday/test_graph_integration.py
unset RINGTRACE_TEST_DISPOSABLE

# Terminal 1, repository root:
uvicorn api.main:app --host 0.0.0.0 --port 8000

# Terminal 2, after the backend is listening:
cd frontend && npm run dev -- --host 0.0.0.0
```

Open the Vite URL and select **Payment corridor**. The Vite `/api` proxy uses the backend on the same sandbox host. For a single-origin local build, `npm run build` makes FastAPI serve `frontend/dist`; visit `http://localhost:8000/corridor`.

The default event-day feature is **disabled**. Its graph client uses only `RINGTRACE_EVENTDAY_FALKORDB_*` settings and never inherits the pre-existing graph endpoint. It refuses port 6379 and graph names outside `ringtrace_eventday` (or its underscore-suffixed namespace). Every connection requires an explicitly configured host and port, so no missing endpoint can fall back to localhost. Remote hosts additionally require TLS, username/password, and the exact `ringtrace_eventday_test` graph. Seeding requires `RINGTRACE_EVENTDAY_DISPOSABLE=1`; remote seeding is limited to the same TLS-authenticated test graph. Never set the disposable flag against data you need to preserve.

### Dedicated Cloud test endpoint

**Free-tier TLS limitation (checked 2026-10-15):** FalkorDB Cloud's [Free-tier matrix](https://github.com/FalkorDB/falkordb-cloud-docs/blob/0d1e2a2e7dc3dc11058de59fc9fab0757813c893/tiers/free.mdx) marks TLS unavailable on Free and first available on Startup. The [connection guide](https://github.com/FalkorDB/falkordb-cloud-docs/blob/0d1e2a2e7dc3dc11058de59fc9fab0757813c893/console/connect.mdx) says Free instances use the non-TLS client mode. This application deliberately refuses remote plaintext. Therefore, do not use a Free-tier instance for direct remote integration; do not set TLS off or relax certificate/hostname verification. The minimum provider capability is an endpoint with provider-supported TLS; the current plan matrix places that at Startup. No plan change or billable resource is made by this project.

Store the Cloud host, assigned non-6379 port, username, and password only in the approved runtime secret/environment configuration; do not paste credentials in chat, save them in `.env.example`, or use a credential URL. Configure these existing connection variables in that runtime: `RINGTRACE_EVENTDAY_FALKORDB_HOST`, `RINGTRACE_EVENTDAY_FALKORDB_PORT`, `RINGTRACE_EVENTDAY_FALKORDB_USERNAME`, and `RINGTRACE_EVENTDAY_FALKORDB_PASSWORD`. Set `RINGTRACE_EVENTDAY_FALKORDB_TLS=1`, `RINGTRACE_EVENTDAY_GRAPH=ringtrace_eventday_test`, `RINGTRACE_EVENTDAY_ENABLED=1`, and `RINGTRACE_EVENTDAY_DISPOSABLE=1`; set `RINGTRACE_TEST_DISPOSABLE=1` only when explicitly running the integration test. Set legacy `FALKORDB_PORT=1` during test runs so the pre-existing graph test harness cannot target its default preview port. Missing host/port is a configuration error in every mode, not a localhost fallback. The client keeps TLS certificate and hostname verification enabled for Cloud connections.

The integration test performs a read-only `RETURN 1` check and checks total graph node/edge counts before seeding. It refuses to seed if the target is not empty and never resets or wipes the graph. Run the integration module once against the newly created empty graph; after it seeds, inspect graph state rather than rerunning it blindly. The loader is additive/idempotent, but the test intentionally requires a fresh empty target for its first-run proof.

Stop the disposable graph with `docker stop ringtrace-eventday-falkordb` (the `--rm` container is removed when stopped). Do not run the integration tests against the existing preview, a shared database, or a production graph.

## Tests and verification state

Fast unit tests cover planner semantics, Cypher parameterization/hop bounds, seed opt-in/port isolation, and one-time authenticated-review state transitions. They do not prove FalkorDB syntax/algorithm compatibility.

The separately gated integration tests are in `tests/eventday/test_graph_integration.py`. Run only after a disposable FalkorDB instance is confirmed on loopback port 6380:

```bash
RINGTRACE_EVENTDAY_ENABLED=1 \
RINGTRACE_EVENTDAY_DISPOSABLE=1 \
RINGTRACE_TEST_DISPOSABLE=1 \
RINGTRACE_EVENTDAY_FALKORDB_HOST=127.0.0.1 \
RINGTRACE_EVENTDAY_FALKORDB_PORT=6380 \
RINGTRACE_EVENTDAY_GRAPH=ringtrace_eventday_test \
pytest -q tests/eventday/test_graph_integration.py
```

Current verification (2026-10-15): `falkordb-bin` 1.4.1 ran Redis 8.2.3 with FalkorDB 4.16.3 in a temporary Python 3.11 environment, bound to loopback port 6380; the temporary database and environment were removed after testing. The basic PING/Cypher smoke check passed (2 nodes, 1 edge). Actual local embedded event-day integration: **6 passed, 0 skipped**; seed-time fixture counts were **19 nodes / 31 edges**. After the authenticated simulated write, a read-only inspection observed **28 nodes / 41 edges** (5 payment events, 8 wallets, 1 investigation run, 1 proposal, 7 evidence nodes). Full Python suite: **99 passed, 36 skipped**; the six event-day integration cases were run separately against the local engine, not counted as full-suite passes. Frontend production build passed. The local graph API smoke, query-failure distinction, timestamp mutation/restore, approval, confirmation, replay rejection, and evidence write-back were exercised by that integration run. Remote Cloud TLS and production deployment remain unverified; browser QA and Docker build remain unrun. Port 6379 was not accessed.

## Three-minute demo outline

1. **Scope** — State that the prior RingTrace repository predates the event; show the separate event-day package/page and synthetic-only graph label. Do not imply the existing project was created during the event.
2. **Temporal trace** — Select `PAY-ALERT-1001`. Explain the anchor time, strict time ordering, bounded hop count, and actual Cypher parameters; show the returned `W-MULE-01 → W-MULE-02 → W-MULE-03` route and synthetic payout (only after integration verifies it).
3. **Graph-native corroboration** — Expand the shared-device/owner, PageRank, and WCC queries; distinguish actual result rows from heuristic interpretations.
4. **Benign look-alike** — Select `PAY-BENIGN-2001` or `PAY-AMBIG-3001`; show that shared household/device context can exist without a downstream payment path and is not labelled fraud.
5. **Uncertainty and action gate** — Demonstrate the explicit query-error/unknown state if feasible. Authenticate, approve, inspect the confirmation language, then show the simulated graph proposal and provenance only if a disposable graph has passed integration QA. State that there is no external financial side effect.

Do not record or publish a demo as verified until it has actually been captured, reviewed, and checked for credentials/secret leakage.

## AI-use disclosure and team review

AI coding assistance in the Arena Agent Mode session was used to draft/implement the event-day graph layer, deterministic planner/API/UI, tests, and documentation. This AI-assisted code is not represented as independently human-authored. The team must inspect and understand the Cypher, validate it against an isolated FalkorDB instance, make meaningful participant contributions, and update this disclosure with the actual human review/changes and any additional AI tools used before submission. Do not claim participant verification, organizer approval, or tests that have not actually been performed.

## Submission checklist (not yet complete)

- [ ] Obtain organizer clarification on reuse/eligibility and confirm Track 01.
- [ ] Team reviews, understands, materially contributes to, and verifies the event-day code; finalize AI disclosure.
- [ ] Run Python unit suite and disposable FalkorDB integration above; document exact results.
- [ ] Run browser flows and Docker build; check responsive behavior, action gate, and graph-offline behavior.
- [ ] Record/review the demo video; remove credentials and unrelated personal data.
- [ ] Audit all Git history for secrets; review license and data rights; keep repository private until the team deliberately approves publication.
- [ ] Publish the repository and submit only after the team confirms eligibility and every required artifact.
