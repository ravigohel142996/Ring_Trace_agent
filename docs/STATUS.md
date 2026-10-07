# RingTrace — Project Status (as of this build)

This is a snapshot answer to three questions: **what exists**, **what's
strong about it (judging criteria)**, and **what's still rough / unfinished**.

---

## 1. Full file inventory

### Root
| File | What it is |
|---|---|
| `README.md` | Full hackathon write-up: problem, why graphs/FalkorDB, architecture, schema, agent workflow, tools, ML approach, demo script, setup, env vars, limitations, roadmap. |
| `requirements.txt` | All Python deps (FalkorDB client, openai, pandas/sklearn, streamlit/plotly/pyvis, pydantic, pytest, etc.). |
| `.env.example` | Template for all env vars (FalkorDB connection, LLM provider/key, synthetic data generator knobs). Never commit a real `.env`. |
| `.gitignore` | Excludes `.venv/`, `bin/` (local FalkorDB binaries), generated `data/`, generated `reports/`, caches. |
| `docker-compose.yml` | Two services: `falkordb` (official image) + `ringtrace` (the app), wired together with health checks and env passthrough. |

### `graph/` — the FalkorDB layer
| File | What it is |
|---|---|
| `connection.py` | Singleton FalkorDB connection/graph handle + `health_check()` used everywhere to detect "DB unreachable" gracefully. |
| `schema.py` | Node label / relationship-type constants + the index list applied on load. |
| `queries.py` | All Cypher: read queries (account context, WCC-based ring detection, PageRank leader ranking, money-path tracing, identity-link lookups) **and** the simulated action writes (create case, flag, escalate, watchlist, etc.), all parameterized. |

### `ingestion/` — synthetic data
| File | What it is |
|---|---|
| `generate_synthetic_data.py` | Configurable fraud-ring generator: plants the fixed demo scenario (A1027 ring, Case A/B reference accounts) + a random population of legit accounts and 5 fraud-pattern rings (dense ring, shared-device ring, shared-IP cluster, layered movement, central mule). Writes ground truth to CSV only. |
| `load_to_falkordb.py` | Batched `UNWIND`/`CREATE` loader into FalkorDB, then materializes the derived `LINKED_TO` identity-resolution graph that WCC/PageRank run over. |

### `models/` — explainable ML risk scoring
| File | What it is |
|---|---|
| `features.py` | Computes graph-derived features per account (degree, PageRank, component size, shared-device/IP counts, txn stats, hop-distance to alerts, broker count, suspicious-neighbor ratio) with a cache so one investigation doesn't recompute the whole graph repeatedly. |
| `train.py` | Trains a RandomForest on those features against synthetic ground truth; writes `risk_model.joblib` + `evaluation/synthetic_eval_report.json`. |
| `risk_scorer.py` | Loads the trained model, scores one account, and applies the **graph-evidence guardrail** (caps the ML score when the graph itself doesn't corroborate a high verdict — the mechanism that keeps Case A/B/C separated correctly). |
| `risk_model.joblib` | The trained model artifact (checked in — small, and useful to ship so a fresh clone can score without retraining). |

### `tools/` — the MCP-style agent tool layer
| File | What it is |
|---|---|
| `base.py` | `ToolResult`, `ToolSpec` (+ OpenAI function-schema export), `ToolRegistry`. Contract: tools never raise, always return a structured result. |
| `context.py` | `ToolContext` — the shared state passed into every tool call (graph store, risk scorer, feature cache, evidence trail, ID counters for new Case/Watchlist records). |
| `investigation.py` | The 11 read-only investigation tools: `get_account_context`, `find_fraud_ring`, `rank_ring_leaders`, `trace_money_path`, `find_identity_links`, `calculate_risk_score`, `generate_verdict`, plus optional `timeline_analysis`, `broker_analysis`, `compare_accounts`, `investigate_entity`. |
| `actions.py` | The 7 simulated action tools: `create_investigation_case`, `flag_account`, `mark_high_risk`, `escalate_case`, `request_manual_review`, `add_to_watchlist`, `export_case_summary` (+ `generate_case_report`). |
| `__init__.py` | Imports both modules so importing `tools` registers everything. |

### `agent/` — the reasoning loop
| File | What it is |
|---|---|
| `llm.py` | OpenAI-compatible chat client wrapper (Groq/OpenAI/etc via env vars). Returns `None` if unconfigured — never crashes the app. |
| `rule_based.py` | Deterministic planner: runs the same investigative methodology as an LLM would, skipping steps the evidence doesn't justify. This is what actually runs in this sandbox (no LLM key set). |
| `investigator.py` | Orchestrator: picks LLM-loop or rule-based planner, builds the `ToolContext`, always derives the final verdict from `agent/decision.py` regardless of which planner ran. |
| `decision.py` | The transparent, rule-based decision engine — reads the evidence trail, writes numbered human-readable reasoning, maps risk class → verdict/action/confidence. Also `execute_recommended_action()` which performs the simulated action tool calls. |
| `report.py` | Builds the downloadable Markdown case report from a steps+verdict pair. |

### `app/` — the dashboard
| File | What it is |
|---|---|
| `dashboard.py` | Streamlit app: sections A (input) → B (live tool trace) → C (graph view) → D (risk) → E (evidence) → F (verdict + execute action) → G (case report download). |
| `graph_viz.py` | Builds the interactive Pyvis graph (ring members, shared device/IP nodes, highlighted money-path edges) straight from the agent's own tool outputs. |

### `tests/`
| File | What it is |
|---|---|
| `conftest.py` | Shared fixtures; skips the suite cleanly if FalkorDB isn't reachable. |
| `test_tools.py` | Contract tests for the 7 required tools (correct shapes, graceful failure on bad input/unknown account). |
| `test_decision.py` | **The key test**: proves identical decision logic yields LOW / HIGH / CRITICAL for Case A / B / C respectively — different graph evidence, different verdict. |
| `test_risk_scorer.py` | Unit tests for the graph-evidence guardrail math (no DB needed). |

### `docker/`, `scripts/`, `docs/`, `evaluation/`
| File | What it is |
|---|---|
| `docker/Dockerfile`, `docker/entrypoint.sh` | App image; entrypoint waits for FalkorDB, runs the data pipeline once if the graph is empty, then launches Streamlit. |
| `scripts/run_pipeline.sh` | One command: generate data → load graph → train model. |
| `scripts/setup_falkordb_local.sh` | Convenience launcher for a local FalkorDB (Docker-first, with fallback notes). |
| `docs/architecture_diagram.png` | AI-generated illustration of the GRAPH → REASONING → DECISION → ACTION pipeline, used in the README. |
| `evaluation/synthetic_eval_report.json` | The model's metrics on synthetic ground truth, explicitly disclaimed as synthetic-only. |

**~3,800 lines of application Python**, plus Cypher embedded in `graph/queries.py`.

---

## 2. What's genuinely strong (the "winning" parts)

- **The graph actually drives the decision, provably.** `tests/test_decision.py::test_verdicts_differ_across_cases` is an automated, passing test that the *same* decision code produces LOW/HIGH/CRITICAL purely because of different FalkorDB graph structure (component size, shared devices/IPs, a traced money path, PageRank leader). That's the exact judge test from the brief ("without the graph, this agent could not have made this decision") turned into a real assertion, not just a demo narrative.
- **Real FalkorDB graph algorithms, not reimplemented in Python.** Ring detection uses `algo.WCC`, leader ranking uses `algo.pageRank` over `TRANSFERRED_TO` — both called live via Cypher, both verified against the loaded graph.
- **Never crashes, degrades gracefully everywhere:**
  - No LLM key → rule-based planner runs the same methodology, dynamically skipping steps (e.g. no `rank_ring_leaders` call for an isolated account).
  - FalkorDB down → dashboard shows a clear banner instead of a stack trace (`health_check()` gate).
  - Bad tool input → Pydantic validation error becomes a structured `ToolResult(ok=False)`, never an unhandled exception.
- **The ML isn't just a black box — it's guarded.** The RandomForest alone over-trusts a noisy small-sample feature for near-dormant accounts (confirmed in testing: an isolated account could land MEDIUM on model score alone). The `_graph_evidence_strength` guardrail in `models/risk_scorer.py` catches exactly that and caps the score, with the cap reason surfaced to the dashboard (`raw_model_score` vs `risk_score`). This is explainability in practice, not just a slide.
- **Full action loop, not just a verdict.** Executing the recommended action actually writes `Case`/`WatchlistEntry` nodes and sets `Account.flagged/risk_level/status` in FalkorDB — verified live, and immediately visible on re-investigation. The case report pulls in that same tool-execution history.
- **Clean separation of concerns**: tool layer (`tools/`) is reusable by both an LLM and a deterministic planner; the decision engine (`agent/decision.py`) is independent of which planner gathered the evidence. This is a defensible architecture, not just "whatever worked."
- **Synthetic data and ground truth are honestly scoped**: ground truth never touches graph nodes (the agent can't cheat by reading a label), and the README explicitly disclaims the 1.0 accuracy as "recovered a planted structure," not a real-world claim.
- **17 passing automated tests**, runnable with one command (`pytest tests/`), no manual clicking required to verify core correctness.

---

## 3. Known gaps / remaining issues (honest list)

### Environment fragility (operational, not a code bug)
- **FalkorDB has to be rebuilt from source each fresh sandbox.** This sandbox's glibc (2.36) is incompatible with the official prebuilt `redis-server` (needs 2.38), so each new session requires: building Redis 7.4.0 from source + extracting `falkordb.so` from the `falkordblite` PyPI wheel. This has now been done successfully 3 times, but it's slow (~2 min) and would NOT be needed at all on a judge's machine with Docker (`docker compose up` sidesteps this entirely, since the official image has its own compatible environment). **This is the single biggest practical risk for a live demo** — if asked to demo on short notice without Docker available, expect a ~2-3 minute setup delay.
- `.venv`, `bin/`, `data/raw/*.csv`, loaded graph contents are all git-ignored by design (correctly, per the hackathon spec's "no large generated artifacts in git" guidance) — but it means every fresh checkout needs `scripts/run_pipeline.sh` run again before the dashboard has anything to show.

### Untested / unverified paths
- **LLM tool-calling mode has never been exercised against a real LLM.** `LLM_PROVIDER=none` in this environment (no API key configured), so every investigation in this session ran through the rule-based planner. The LLM loop (`agent/investigator.py::_run_llm_loop`) is implemented and syntax-correct, but its live behavior with a real Groq/OpenAI key — tool-call parsing, multi-turn correctness, stopping condition — has not been observed end-to-end.
- **`docker-compose.yml` / `docker/Dockerfile` have never actually been built or run** — no Docker available in this sandbox. They're written to the same patterns as the working local scripts, but haven't been smoke-tested.
- The Streamlit dashboard's interactive widgets (buttons, the "execute recommended action" flow, file download) have been verified through direct Python calls to the same underlying functions the UI calls, and the server responds `HTTP 200` / health-checks OK — but the actual browser-rendered UI has not been clicked through by a human or a headless browser in this session.

### Scope / design simplifications
- **`Merchant` / `TO_MERCHANT` exist in the schema and loader code but are never populated** — the synthetic generator doesn't create any Merchant nodes (0 in the live graph). This is a leftover from matching the full schema spec; it doesn't affect any of the demo cases but is an incomplete corner.
- **`find_fraud_ring`'s "ring" threshold (component size ≥ 3) is a simple heuristic**, not density- or risk-weighted. A chain of 3 completely benign accounts would technically be labeled `is_ring=True` the same as a dense fraud cluster — the risk score (not the ring label) is what actually determines severity, but the label itself is approximate.
- **The RandomForest's perfect 1.0 metrics are on a small, intentionally clean synthetic set** (205 accounts, 52 in the test split) — honestly disclaimed in the README and eval report, but worth remembering it's not a real generalization claim.
- **No auth, no multi-user session isolation, no persistence layer for the dashboard** — by design (hackathon MVP), but worth stating explicitly as a limitation, not an oversight.
- **No CI pipeline** (e.g. GitHub Actions running `pytest` on push) — tests exist and pass locally/manually but aren't automated on the repo yet.
- The architecture diagram in the README is AI-generated artwork illustrating the pipeline concept, **not an actual dashboard screenshot** — there are no real screenshots of the running UI in the README yet (would need a headless browser, not available in this sandbox).

### Minor / cosmetic
- `agent/investigator.py` imports `json` twice in the LLM loop (`import json` then `import json as _json`) — harmless but untidy.
- No rate-limiting/backoff beyond `LLM_TIMEOUT_SECONDS` on the LLM call path.

---

**Bottom line:** the core thesis — FalkorDB graph structure provably drives the agent's decisions, with explainable ML, a full simulated action loop, and graceful degradation everywhere — is built, working, and test-covered. The main real risk for a live demo is the FalkorDB *setup* step in a non-Docker sandbox, not the application logic itself.
