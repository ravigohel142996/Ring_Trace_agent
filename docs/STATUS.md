# RingTrace — Project Status

**Updated:** 2026-10-08

This status note reflects the React/FastAPI rebuild while preserving the
original Streamlit application and fraud-investigation engine.

## Product shape

- **Primary judge-facing app:** React 19 + TypeScript + Vite, served in
  production by FastAPI on port `8000`. `/api/*`, built assets, and SPA
  routes share one origin.
- **Graph layer:** FalkorDB is the live context source for graph tools,
  agent decisions, evidence provenance, and simulated action writes. The
  default Compose setup does not publish a separate database URL.
- **Legacy UI:** `app/dashboard.py` and `app/graph_viz.py` remain in the
  repository; they were not deleted or replaced in place.
- **Existing engine:** `agent/`, `tools/`, `graph/`, `models/`, and
  `ingestion/` continue to provide investigations and graph-derived risk.
- **Data:** A1027 and every other included scenario are synthetic. The UI
  and demo script must not frame them as real customer records or fraud
  findings.

## Implemented

- FastAPI API contracts for health, scenarios, investigations, cases, graph
  exports, evidence, trace, risk, decisions, and simulated actions. Durable
  FalkorDB action cases are normalized into read-only summaries; missing
  historical traces/features are not fabricated.
- Native interactive SVG graph with pan/zoom, selection/details, fit/reset,
  and relationship filters.
- Investigation workspace with live graph payload, actual tool trace,
  evidence/Cypher ledger, risk/decision provenance, cases/risk/graph pages,
  and an approval plus explicit-confirmation action center. The execution API
  independently requires the confirmation flag before it can begin a write.
- FastAPI static serving for the built SPA, assets, and client-side routes;
  unknown `/api/*` routes remain JSON 404s.
- Multi-stage Docker build: Vite production build plus Python/FastAPI
  runtime. Compose publishes only app port `8000`; FalkorDB is internal.
- Preserved Streamlit baseline and existing agent/graph/action engine.

## Verification in this workspace

- Frontend production build: `npm --prefix frontend run build` — passed.
  Vite also accepted the sandbox `*.e2b.app` host and successfully proxied
  relative `/api/health` requests to FastAPI.
- Python dependency consistency and byte-compilation checks passed; production
  frontend audit: `npm audit --omit=dev` — **0 vulnerabilities**.
- Graceful no-graph run: **45 passed, 23 skipped** with the graph port
  deliberately unavailable; all graph-specific tests report a clear skip.
- Full application suite with FalkorDB running and seeded:
  `FALKORDB_HOST=127.0.0.1 FALKORDB_PORT=6379 PYTHONPATH=. .venv/bin/pytest tests/ -q`
  — **68 passed**. The suite has 23 graph-dependent cases that skip cleanly
  if FalkorDB is unavailable.
- Focused failure-path coverage verifies that an empty graph-case write
  cannot be reported as success or trigger follow-on action tools, and that
  graph case/watchlist IDs remain unique across independent contexts.
- Durable graph-case listing/detail HTTP contracts were smoke-tested with
  persisted FalkorDB records and expose the known summary as read-only rather
  than inventing an absent original tool trace or feature vector.
- Fresh default synthetic graph seed: **1,805 nodes / 5,062 edges** before the
  additional QA action-write records.
- Live A1027 FastAPI investigation: seven successful rule-based tool steps;
  **CRITICAL**, risk score `0.9852`, confidence `0.95`, PageRank leader
  `A1001`, and the five-hop path `A1027 → A1023 → A1024 → A1025 → A1026 →
  A1001`.
- Production HTTP smoke test: `/`, `/cases`, `/risk`, `/graph`, built JS,
  `/api/health`, `/api/graph/health`, investigation graph/evidence/trace
  endpoints, and durable read-only case detail all succeeded. A live A1027
  investigation returned seven successful rule-based tool calls.
- Graph-backed action integration test verified the case, supporting
  evidence, action, and findings in FalkorDB (`HAS_CASE`, `SUPPORTED_BY`,
  `RESULTED_IN`, `TRIGGERED_BY`). API tests verify both approval and a
  separate confirmation are required; an unconfirmed request does not
  consume the one allowed execution attempt.
- Local graph runtime for this workspace: Redis 8.0.0 with FalkorDB module
  4.18.3. Redis was built from source and the module/libs were extracted into
  ignored `bin/`; none of those generated binaries are part of the repo.
- Docker/Podman is not installed in this workspace, so the container image
  has not been built or run here. Do not describe the Docker path as
  end-to-end verified.
- No browser screenshot is bundled. The HTTP smoke test verifies serving,
  not pixel-level rendering or a human browser interaction.

## Known limitations

- The data generator, trained model, and evaluation metrics are synthetic;
  they do not establish real-world fraud-detection performance.
- The live LLM path was not exercised with an external API key. The verified
  A1027 walkthrough uses the existing deterministic rule-based planner.
- The active API investigation index is process-local. Graph-backed action
  and evidence records are durable in FalkorDB, but there is no authentication
  or multi-tenant case-management layer.
- The Docker build/run still needs verification on a host with Docker.
- Local FalkorDB source/binaries and loaded graph contents are ignored and
  are not shipped in Git. A fresh local checkout needs a FalkorDB service and
  a synthetic graph seed, or can use the Docker Compose setup.

## Relevant files

- `api/`: FastAPI routes, schemas, graph export, and investigation session
  store.
- `frontend/`: React/Vite app, API client, native SVG graph, provenance,
  evidence, cases, risk, and action components.
- `agent/`, `tools/`, `graph/`, `models/`, `ingestion/`: preserved engine and
  graph implementation.
- `app/`: preserved Streamlit dashboard and Pyvis graph implementation.
- `tests/`: API, tools, decisions, risk, LLM-loop, and FalkorDB integration
  tests.
- `docker/`, `docker-compose.yml`: one-port FastAPI deployment with an
  internal graph service.

## Event-day extension status — 2026-10-15

The pre-event status above remains a record of the earlier baseline; it does
not verify the new contribution. The separate proposed Track 01 workflow lives
under `eventday/` and in the Payment corridor UI. It uses its own disabled-by-
default FalkorDB connection (`RINGTRACE_EVENTDAY_FALKORDB_*`), a synthetic-only
schema, a strictly time-respecting Cypher traversal, identity follow-ups, and
conditional FalkorDB PageRank/WCC. A graph write can only create a simulated
review proposal/provenance after analyst authentication, short-lived approval,
and explicit confirmation.

Current verification (2026-10-15): `npm run build` passed (`tsc --noEmit`
plus Vite production build). The full Python suite passed **92, skipped 32,
failed 0** using `FALKORDB_PORT=1`, `RINGTRACE_TEST_DISPOSABLE=0`, and
`RINGTRACE_EVENTDAY_ENABLED=0`; the focused event-day suite passed **19,
skipped 2, failed 0**. Both gated event-day graph integration tests skipped,
and graph-dependent legacy tests were disabled; the graph integration status
is **UNVERIFIED (no disposable FalkorDB)**. A no-graph HTTP smoke test served
`/corridor`, synthetic scenario IDs, and a disabled event-day health response;
the investigation route correctly returned 503 before opening a graph
connection. Docker, Podman, `redis-server`, and `redis-cli` are not installed
in this workspace. No FalkorDB process was started or contacted, and port 6379
was not probed or accessed. Do not infer graph/browser/Docker integration or
action-write verification from the build, unit tests, or HTTP smoke test. The
demo video, organizer eligibility clarification, full-history secret/license
reviews, and public-release decision remain outstanding. See
`docs/EVENTDAY_TRACK_01.md`.
