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
  exports, evidence, trace, risk, decisions, and simulated actions.
- Native interactive SVG graph with pan/zoom, selection/details, fit/reset,
  and relationship filters.
- Investigation workspace with live graph payload, actual tool trace,
  evidence/Cypher ledger, risk/decision provenance, cases/risk/graph pages,
  and an approval plus explicit-confirmation action center.
- FastAPI static serving for the built SPA, assets, and client-side routes;
  unknown `/api/*` routes remain JSON 404s.
- Multi-stage Docker build: Vite production build plus Python/FastAPI
  runtime. Compose publishes only app port `8000`; FalkorDB is internal.
- Preserved Streamlit baseline and existing agent/graph/action engine.

## Verification in this workspace

- Frontend production build: `npm --prefix frontend run build` — passed.
- Full application suite with FalkorDB running and seeded:
  `PYTHONPATH=. .venv/bin/pytest tests/ -q` — **65 passed**. The suite has
  24 graph-dependent cases that skip cleanly if FalkorDB is unavailable.
- Fresh default synthetic graph seed: **1,805 nodes / 5,062 edges** before the
  additional QA action-write records.
- Live A1027 FastAPI investigation: seven successful rule-based tool steps;
  **CRITICAL**, risk score `0.9852`, confidence `0.95`, PageRank leader
  `A1001`, and the five-hop path `A1027 → A1023 → A1024 → A1025 → A1026 →
  A1001`.
- Production HTTP smoke test: `/`, `/cases`, `/risk`, `/graph`, built JS/CSS,
  `/api/health`, `/api/graph/health`, investigation graph/evidence/trace
  endpoints all succeeded.
- Simulated action smoke test: approval and explicit confirmation completed;
  graph case, supporting evidence, action, and findings were verified in
  FalkorDB (`HAS_CASE`, `SUPPORTED_BY`, `RESULTED_IN`, `TRIGGERED_BY`).
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
