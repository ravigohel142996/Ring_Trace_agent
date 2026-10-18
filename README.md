<div align="center">

# 🕵️ RingTrace Fraud-Ring Detective Agent

### **Follow the graph. Trace the money. Respect the clock.**

[![Track 01](https://img.shields.io/badge/Track-01%20Agents%20That%20Act-blue?style=for-the-badge)](https://graphhacks.dev/)
[![FalkorDB](https://img.shields.io/badge/Powered%20by-FalkorDB-red?style=for-the-badge)](https://www.falkordb.com/)
[![Python 3.11](https://img.shields.io/badge/Python-3.11-blue?style=for-the-badge&logo=python)](https://python.org/)
[![React](https://img.shields.io/badge/React-19-61dafb?style=for-the-badge&logo=react)](https://react.dev/)
[![Tests](https://img.shields.io/badge/Tests-100%20passed-brightgreen?style=for-the-badge)](tests/)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)

---

## 🎯 **WeMakeDevs × FalkorDB Graph Hacks 2026**

**Track 01: Agents That Act on Connected Data**

A graph-native fraud investigation system where FalkorDB powers every decision — from ring detection to risk scoring to simulated action execution.

[🚀 Quick Start](#-quick-start) • [📖 Documentation](#-documentation) • [🎬 Demo](#-demo) • [🏗️ Architecture](#️-architecture)

---

</div>

## 🌟 Overview

RingTrace is a **graph-first fraud investigation agent** that uses FalkorDB as its live reasoning engine. Unlike traditional systems that treat graphs as visualization afterthoughts, RingTrace executes real Cypher queries and graph algorithms (WCC, PageRank) to detect fraud rings, trace money flows, and make evidence-based decisions.

**Two Investigation Workflows:**

1. **Core Ring Investigator** — Detects account-based fraud rings with shared devices, IPs, and money movement
2. **Event-Day Payment Corridor** ⭐ — Time-respecting payment traversal for Track 01 (event-day contribution)

> ⚠️ **All demo data is synthetic.** No real people, accounts, or financial systems are involved. Every action is simulated and confined to demo graphs.

![RingTrace architecture: FalkorDB Graph → Agent Reasoning → Risk Decision → Action](docs/architecture_diagram.png)

---

## 🚀 Quick Start

Get RingTrace running in under 5 minutes:

### Option 1: Docker (Recommended)

```bash
# Clone the repository
git clone https://github.com/ravigohel142996/Ring_Trace_agent.git
cd Ring_Trace_agent

# Start everything with Docker Compose
docker-compose up -d

# Access the application
open http://localhost:8000
```

### Option 2: Local Development

```bash
# Clone and setup
git clone https://github.com/ravigohel142996/Ring_Trace_agent.git
cd Ring_Trace_agent

# Install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Start FalkorDB (requires Docker)
docker run -d --name ringtrace-falkordb -p 127.0.0.1:6379:6379 falkordb/falkordb:latest

# Seed the database
python -m ingestion.load_to_falkordb

# Start the API server
uvicorn api.main:app --host 0.0.0.0 --port 8000

# In another terminal, start the frontend
cd frontend
npm install
npm run dev
```

### Demo Credentials

- **Username:** `analyst`
- **Password:** `demo2026`

---

## 🎬 Demo

### Try These Scenarios

**Core Ring Investigation:**
1. Navigate to **Investigate** page
2. Select **CASE-C** (Account A1027 - "Ring with money flow")
3. Click **Run Investigation**
4. Watch the agent detect a 9-account fraud ring with CRITICAL risk

**Event-Day Payment Corridor:**
1. Navigate to **Payment Corridor** page
2. Select **PAY-ALERT-1001** (Fast multi-hop corridor)
3. Set window: 60 minutes, max hops: 4
4. Click **Investigate**
5. See time-respecting traversal across 4 wallets

**Authentication & Actions:**
1. Click **Sign In** → Enter `analyst` / `demo2026`
2. Run any investigation
3. Scroll to **Action Center**
4. Click **Approve Action** → Confirm
5. See the graph write-back in real-time

---

## 📖 Documentation

<details>
<summary><strong>📋 Table of Contents</strong> (click to expand)</summary>

### Core Concepts
1. [Problem Statement](#1-problem)
2. [Why a Graph?](#2-why-a-graph)
3. [Why FalkorDB?](#3-why-falkordb)
4. [Track 01 Alignment](#4-track-alignment)

### Technical Deep Dive
5. [Architecture](#5-architecture)
6. [Graph Schema](#6-graph-schema)
7. [Agent Workflow](#7-agent-workflow)
8. [Tool Layer](#8-tool-layer)
9. [Graph Algorithms](#9-graph-algorithms)
10. [ML Risk Scoring](#10-ml-risk-scoring)

### Features & Security
11. [Action System](#11-action-system)
12. [Evidence Model](#12-evidence-model)
13. [Demo Scenarios](#13-demo-scenarios)
14. [Security Hardening](#-security-hardening)

### Getting Started
15. [Setup Guide](#15-setup)
16. [Docker Deployment](#16-docker)
17. [Environment Variables](#17-environment-variables)
18. [Testing](#18-testing)

### Project Info
19. [Evaluation Results](#19-evaluation)
20. [Limitations](#20-limitations)
21. [Future Roadmap](#21-future-roadmap)
22. [Event-Day Contribution](#22-event-day-payment-corridor-contribution)
23. [Deployment Options](#-deployment-options)
24. [Team & Credits](#-team--credits)

</details>

---

## 1. Problem

Fraud rings don't look suspicious one row at a time. A single account, a
single transaction, a single login — in isolation, none of it looks wrong.
What gives a ring away is **structure**: five accounts sharing one device,
money hopping through four intermediaries before landing on one collector
account, a cluster of "unrelated" wallets all logging in from the same IP,
then cashing out through a mixer and spending the proceeds at a real
merchant.

That structure lives naturally in a **graph**. Flattening it into rows for a
classifier (or a prompt for an LLM) throws away exactly the signal that
matters.

## 2. Why a graph

Fraud rings *are* graphs: `Account —TRANSFERRED_TO→ Account`,
`Account —USES_DEVICE→ Device ←USES_DEVICE— Account`,
`Account —TO_MERCHANT→ Merchant`. Two graph primitives do most of the real
work here:

- **Weakly Connected Components (WCC)** instantly isolates "who is in this
  ring with me" — the alternative (self-joins / recursive SQL CTEs) gets
  ugly and slow fast.
- **PageRank** over the money-flow graph identifies the *ring leader* — the
  account that disproportionately collects funds — with zero hand-tuned
  heuristics.

Component *membership* alone is a weak signal, though (see [Section 9](#9-graph-algorithms)
for why RingTrace replaced a naive "size ≥ 3 = ring" check with a transparent
composite score) — which is itself only possible because the graph exposes
the finer-grained signals (shared-identity density, reciprocal flow, broker
concentration) that a flattened table would have thrown away.

## 3. Why FalkorDB

FalkorDB was chosen because it's a **property graph with those algorithms
built in** (`CALL algo.WCC(...)`, `CALL algo.pageRank(...)`) and speaks
**Cypher** over a **Redis-compatible wire protocol**, so the whole stack
(graph + "cache" + pub/sub if needed later) is one lightweight service — a
good fit for a hackathon MVP that still "looks production-capable."

**FalkorDB is not merely used to visualize RingTrace relationships. It is the
live graph context layer used by the agent to investigate connected evidence,
make decisions, and trigger actions.**

Every tool the agent calls (`find_fraud_ring`, `rank_ring_leaders`,
`trace_money_path`, `find_identity_links`, `calculate_risk_score`) issues
real Cypher/`algo.*` calls against FalkorDB, and the **structured results of
those calls are what the decision engine reads** to pick a verdict (see
`agent/decision.py`). Change the graph — remove a shared device, delete a
money edge — and the verdict changes. That's demonstrated explicitly in
[Section 13](#13-demo-scenarios) and asserted directly in
`tests/test_decision.py::test_verdicts_differ_across_cases`.

**On GraphRAG-SDK:** evaluated and deliberately NOT used. RingTrace's tool
layer already issues precise, parameterized Cypher per investigative
question (ring detection, leader rank, money path, identity links) — that's
a more auditable and judge-legible "show your work" story than routing
those same questions through a RAG abstraction on top of the graph. Adding
it here would dilute the graph-first architecture without solving a problem
RingTrace actually has. If a future version needs open-ended natural-language
graph Q&A beyond the fixed tool set, GraphRAG-SDK would be the right place
to revisit this decision.

## 4. Track alignment — pre-existing project baseline

**Provenance:** This section describes the repository's pre-event RingTrace
implementation. It is not claimed as code written during the event. The
separate event-day contribution and its exact graph model are documented in
[Section 22](#22-event-day-payment-corridor-contribution).

Track 01 asks for **"Agents That Act on Connected Data."** The pre-existing
RingTrace implementation was designed around that connected-data workflow:

- **Connected data**: the graph (Person/Account/Device/IP/Broker/Merchant/
  Transaction/Alert + derived `LINKED_TO` identity-resolution edges) is the
  *only* source of investigative truth — no flat feature table is computed
  outside the graph.
- **Agent**: a real tool-calling loop (LLM-driven when configured, or a
  deterministic rule-based planner) dynamically decides which graph query to
  run next based on what the *previous* query actually returned.
- **Acts**: the agent doesn't just report a verdict — it writes real,
  auditable nodes back into the graph (`Case`, `Evidence`, `GraphFinding`,
  `Action`, `WatchlistEntry`) via simulated-but-real graph mutations.

## 5. Architecture

```
┌──────────────┐   Cypher / algo.*   ┌───────────────────────────────┐
│   FalkorDB   │◄───────────────────►│   tools/  (MCP-style layer)   │
│ (graph store │                     │  19 tools (7 required + 5     │
│  + WCC/PageRank)                   │  optional + 7 action), typed  │
└──────────────┘                     └───────────────┬───────────────┘
                                                       │ ToolResult
                                      ┌────────────────▼───────────────┐
                                      │   agent/   (reasoning loop)    │
                                      │ LLM tool-calling  OR           │
                                      │ deterministic rule-based       │
                                      │ planner (agent/rule_based.py)  │
                                      └────────────────┬───────────────┘
                                                        │ evidence_trail
                                      ┌─────────────────▼──────────────┐
                                      │ agent/decision.py                │
                                      │ transparent rules -> verdict,    │
                                      │ confidence, recommended_action   │
                                      └─────────────────┬──────────────┘
                                                         │
                 ┌───────────────────────────────────────▼─────────────┐
                 │ FastAPI `api/main.py` — REST API + SPA on :8000     │
                 │ React/Vite `frontend/` + native SVG graph renderer  │
                 │ `/api/*` and client routes share one public origin │
                 │ legacy Streamlit baseline remains in `app/`         │
                 └───────────────────────────────────────────────────────┘
```

Models (`models/`) compute graph-derived features (degree, PageRank,
component size, shared-identifier counts, hop-distance to known alerts…)
and feed a RandomForest classifier; `models/risk_scorer.py` additionally
applies a **graph-evidence guardrail** (Section 10) on top of the raw model
score so the final number always stays grounded in what the graph actually
shows.

## 6. Graph schema

**Node labels:** `Person`, `Account`, `Device`, `IP`, `Transaction`,
`Broker`, `Merchant`, `Alert`, plus agent-written `Case`, `Evidence`,
`GraphFinding`, `Action`, and `WatchlistEntry` nodes.

**Relationships:**

| Relationship | Direction | Meaning |
|---|---|---|
| `OWNS` | Person → Account | Account ownership |
| `USES_DEVICE` | Account → Device | Device used to access an account |
| `LOGGED_FROM` | Account → IP | Login/session IP |
| `TRANSFERRED_TO` | Account → Account | Denormalized money-flow edge (drives PageRank) |
| `ROUTED_THROUGH` | Account/Transaction → Broker | Funds routed through a broker/mixer |
| `FROM` / `TO` | Transaction → Account | Transaction endpoints |
| `TO_MERCHANT` | Transaction → Merchant | One-sided merchant purchase (no destination Account) — completes realistic end-of-chain narratives like Account → Broker → Account(self) → Merchant |
| `FLAGS` | Alert → Account | Existing rules-engine alert |
| `LINKED_TO` | Account → Account | **Materialized identity-resolution edge** — derived at load time from shared device / IP / owning person / broker / direct transfer. This is what makes `algo.WCC` directly usable for ring detection. |
| `INVESTIGATES` | Case → Account | Agent-created case record (original, unchanged) |
| `HAS_CASE` | Account → Case | Reciprocal of `INVESTIGATES`, added for the evidence-provenance graph (Section 12) |
| `SUPPORTED_BY` | Case → Evidence | Human-readable reasoning line behind a case |
| `RESULTED_IN` | Case → Action | What the agent actually did |
| `TRIGGERED_BY` | Action → GraphFinding | The specific graph finding that justified the action |
| `WATCHES` | WatchlistEntry → entity | Agent-created watchlist entry |

Indexes are created on every `.id` property plus a few hot filter fields
(see `graph/schema.py`) so lookups stay O(log n) as the graph grows.

### Sample Cypher — inspect the graph yourself

Run these directly with `redis-cli` (`GRAPH.QUERY ringtrace "..."`), an
optionally exposed FalkorDB Browser UI, or
`python -c "from graph.connection import get_graph; print(get_graph().query('...').result_set)"`.
The default Compose setup keeps FalkorDB private; the judge-facing app is
available at one URL on port 8000.

```cypher
// Ring members of the Case C demo ring
MATCH (a:Account {id: 'A1027'})
CALL algo.WCC({nodeLabels: ['Account'], relationshipTypes: ['LINKED_TO']})
YIELD node, componentId
WITH componentId AS target_cid WHERE node.id = 'A1027'
WITH target_cid
CALL algo.WCC({nodeLabels: ['Account'], relationshipTypes: ['LINKED_TO']})
YIELD node, componentId
WHERE componentId = target_cid
RETURN collect(node.id) AS ring_members;

// Highest PageRank accounts (likely ring leaders) by money flow
CALL algo.pageRank('Account', 'TRANSFERRED_TO')
YIELD node, score
RETURN node.id AS account_id, score
ORDER BY score DESC LIMIT 10;

// The money path from an alerted account to its ring leader
MATCH p = (a:Account {id: 'A1027'})-[:TRANSFERRED_TO*1..6]->(b:Account {id: 'A1001'})
RETURN [n IN nodes(p) | n.id] AS path, length(p) AS hops;

// Accounts sharing a device with a given account
MATCH (a:Account {id: 'A1027'})-[:USES_DEVICE]->(d:Device)<-[:USES_DEVICE]-(other:Account)
RETURN d.id, collect(DISTINCT other.id) AS other_accounts;

// Full action history + what graph finding triggered each action
MATCH (c:Case)-[:RESULTED_IN]->(ac:Action)-[:TRIGGERED_BY]->(gf:GraphFinding)
RETURN c.account_id, ac.action_type, ac.created_at, gf.summary
ORDER BY ac.created_at DESC LIMIT 20;
```

## 7. Agent workflow

```
understand target → get_account_context
        │
        ▼
   is it in a ring?  ──no──► skip ring tools, still check identity links
        │ yes (is_ring OR ring_score ≥ 0.2)
        ▼
  rank_ring_leaders  → identify leader (PageRank)
        │
        ▼
  trace_money_path(account → leader)  → confirm the flow
        │
        ▼
  find_identity_links  → confirm WHY these accounts are connected
        │
        ▼
  calculate_risk_score → explainable ML score (+ graph guardrail)
        │
        ▼
  generate_verdict → numbered reasoning, ring score/leader/path, confidence, action
```

Two interchangeable planners implement this:

- **LLM mode** (`agent/llm.py` + `Investigator._run_llm_loop`): if
  `LLM_PROVIDER` + `LLM_API_KEY` are set (works with Groq, OpenAI, or any
  OpenAI-compatible endpoint), an LLM with function/tool-calling picks the
  next tool after reading each previous tool's *actual* JSON output — real
  dynamic tool selection, not a canned script. **No live LLM key is
  available in the environment this was engineered in**, so this path is
  verified with a scripted-but-honest mocked-client contract test instead
  (`tests/test_llm_loop_mocked.py` — see [Section 18](#18-testing)); it
  exercises the exact `tool_calls[i].function.{name,arguments}` /
  `.model_dump()` shape the real OpenAI SDK returns, including the
  max-iteration guard and rejection of non-investigation tools. Anyone with
  a Groq/OpenAI key can flip `LLM_PROVIDER` in `.env` and exercise the real
  path end-to-end — the code path is identical either way.
- **Rule-based mode** (`agent/rule_based.py`, the default — **no API key
  required**): a deterministic planner follows the same methodology but
  skips steps the evidence doesn't justify. The demo is never broken by a
  missing/rate-limited LLM key, and this remains the **permanent fallback**,
  not a mode slated for removal.

In **both modes**, the actual verdict is produced by
`agent/decision.py::build_verdict`, reading the structured `evidence_trail`
— never by free-form LLM text. This keeps every decision auditable and
exactly reproducible from the graph evidence collected, independent of which
planner ran.

## 8. Tool layer

Every tool is a `ToolSpec`: a name, an LLM-facing description (**explaining
WHEN to call it**, not just what it does), a Pydantic input model (typed,
validated), and a handler that **always returns a `ToolResult`** —
tools never raise; failures become `{ok: False, error: "..."}` so the agent
loop degrades gracefully instead of crashing.

### Investigation tools (read-only, pure graph queries)

| Tool | Graph operation | When the agent should call it |
|---|---|---|
| `get_account_context` | 1-hop neighborhood fetch (now includes merchant purchases) | Always first — establishes what we know about the target. |
| `find_fraud_ring` | `algo.WCC` over `LINKED_TO` + composite ring score | To check whether the account belongs to a larger connected structure, and how strongly that structure actually looks like a ring. |
| `rank_ring_leaders` | `algo.pageRank` over `TRANSFERRED_TO` | Once a ring is found, to identify the likely leader/mule. |
| `trace_money_path` | Variable-length path over `TRANSFERRED_TO` | To see exactly how money moves between the account and a suspicious endpoint. |
| `find_identity_links` | Shared-device/IP/person/broker lookups | To explain *why* accounts are connected (confirms the ring isn't coincidental). |
| `calculate_risk_score` | Graph feature extraction + RandomForest + guardrail | To get an explainable, numeric severity for a verdict. |
| `generate_verdict` | Synthesizes the evidence trail | Final step — call once sufficient evidence has been gathered. |
| `timeline_analysis` *(optional)* | Chronological transaction ordering | To spot bursty/velocity patterns. |
| `broker_analysis` *(optional)* | Broker/mixer fan-in analysis | When a broker shows up in a money path. |
| `compare_accounts` *(optional)* | Side-by-side feature diff | To contrast a suspicious account against a clean one. |
| `investigate_entity` *(optional)* | Generalized entity lookup (device/IP/person) | When the query starts from a non-account entity. |
| `generate_case_report` *(optional)* | Builds the full Markdown report | For display/export without necessarily ending the investigation. |

### Action tools (simulated, graph-mutating)

| Tool | What it writes |
|---|---|
| `create_investigation_case` | A `Case` node linked to the account via `INVESTIGATES` |
| `flag_account` | `Account.flagged = true` + reason |
| `mark_high_risk` | `Account.risk_level = 'HIGH'`, `status = 'UNDER_REVIEW'` |
| `request_manual_review` | `Account.status = 'MANUAL_REVIEW_REQUESTED'` |
| `escalate_case` | `Case.status = 'ESCALATED'` |
| `add_to_watchlist` | A `WatchlistEntry` node `WATCHES` any entity (account/device/IP/person/broker) |
| `export_case_summary` | Writes a downloadable Markdown case summary report to `reports/` |

`agent/decision.py::execute_recommended_action` additionally writes the
second-order evidence graph (`HAS_CASE`/`SUPPORTED_BY`/`RESULTED_IN`/
`TRIGGERED_BY`, see [Section 12](#12-evidence-model)) around every action —
this is internal bookkeeping, not a new LLM-selectable tool, so the tool
surface the agent reasons over stays small and auditable.

## 9. Graph algorithms

RingTrace prefers **real FalkorDB graph algorithms over Python/NetworkX
reimplementations** everywhere one exists:

| Need | FalkorDB primitive used | NOT done |
|---|---|---|
| Ring membership | `CALL algo.WCC({nodeLabels:['Account'], relationshipTypes:['LINKED_TO']})` | No Python Union-Find over fetched edges |
| Ring leader | `CALL algo.pageRank('Account', 'TRANSFERRED_TO')` | No manual in-degree/weight heuristic |
| Money trail | `MATCH p = (a)-[:TRANSFERRED_TO*1..6]->(b) RETURN p` (variable-length path match) | No BFS implemented client-side |
| Identity distance | `shortestPath((a)-[:LINKED_TO*..8]->(b))` | — |

### The ring-score composite (replaces the old "size ≥ 3" heuristic)

A naive "component size ≥ 3 ⇒ ring" check has a real, measured failure
mode in this dataset: the legitimate background population is only loosely
partitioned into small "circles," so cross-circle noise transactions
transitively merge much of it into one large connected component over time
(confirmed by `evaluation/investigation_eval_report.json`: a 153-account
component containing mostly unrelated legit accounts). Component size alone
would flag the majority of innocent accounts.

`find_fraud_ring` now also computes a **transparent composite ring score**
(`tools/investigation.py::_find_fraud_ring`), blending nine independently
auditable, parameterized-Cypher-backed signals:

| Signal | Query | Weight |
|---|---|---|
| Component size | `weakly_connected_components` | 0.15 |
| Shared-device pair density | `shared_identity_pair_counts` | 0.15 |
| Shared-IP pair density | `shared_identity_pair_counts` | 0.10 |
| Reciprocal transfer density | `reciprocal_transfer_pairs` | 0.15 |
| Internal transaction density | `component_txn_stats` | 0.10 |
| Broker/mixer concentration | `component_broker_count` | 0.10 |
| Alerted-member ratio | `component_alert_count` | 0.10 |
| PageRank concentration | `pagerank` filtered to members | 0.10 |
| Transaction velocity | derived from `component_txn_stats` timestamps | 0.05 |

The tool returns `ring_score` (0–1), `ring_confidence` (how many distinct
signal *types* corroborate it — one strong signal alone yields a low
confidence even with a moderate score), and `ring_reasons` (plain-English,
one line per fired signal). The legacy `is_ring` boolean is **kept for
backward compatibility**, but `agent/rule_based.py` and
`agent/decision.py` now read `ring_score`/`ring_confidence`, not just the
boolean — e.g. the planner digs deeper (`rank_ring_leaders`,
`trace_money_path`) whenever `ring_score ≥ 0.2`, even for 2-account
components the old size threshold would have ignored outright (see
`DEMO-06` in [Section 13](#13-demo-scenarios)).

## 10. ML risk scoring

`models/features.py` computes, per account, purely graph-derived features:
degree & weighted degree on `LINKED_TO`, PageRank on both the identity graph
and the money-flow graph, connected-component size, counts of accounts
sharing a device/IP, transaction count & total amount, net flow, hop-distance
to the nearest known `Alert`, broker count, and the fraction of
directly-linked neighbors that are themselves already flagged
(`suspicious_neighbor_ratio`).

`models/train.py` trains a `RandomForestClassifier` against
`data/processed/ground_truth.csv` — **synthetic ground truth only, used for
training/evaluation, never written onto graph nodes** (the agent cannot
"cheat" by reading a label; it has to infer risk from structure, like a real
investigator). The fresh post-fix run used **219 labeled accounts** with a
stratified 25% holdout (**164 train / 55 test**, `random_state=42`) and the
existing 17-feature schema. The 200-tree forest (`max_depth=8`,
`min_samples_leaf=2`, `class_weight="balanced"`) scored **accuracy 0.945,
precision 0.882, recall 0.938, F1 0.909, ROC-AUC 0.995** on that synthetic
holdout. These are synthetic-only metrics; per-account `predict_proba` values
are raw model scores, **not calibrated real-world fraud probabilities**. The
regenerated `evaluation/synthetic_eval_report.json` records the ground-truth
SHA-256, split parameters, feature order, and classifier settings for
reproducibility. Independent aggregation of outgoing, incoming, and linked
relationships keeps identity fan-out from inflating the monetary features.

> Honesty note: an earlier version of this dataset (without the deliberately
> ambiguous/benign look-alike scenarios) scored a suspicious 1.00 across
> every metric. Adding DEMO-02/DEMO-05 (benign shared-signal look-alikes) and
> DEMO-06 (genuinely ambiguous) made the problem slightly harder and the
> metrics correspondingly — and more credibly — less than perfect. This is
> reported as-is, not tuned back to 1.00.

### The graph-evidence guardrail

A small RandomForest trained on a few hundred synthetic accounts can be
over-confident at the margins. RingTrace adds a transparent, rule-based
**guardrail** (`_graph_evidence_strength` in `models/risk_scorer.py`) that
caps the raw ML score based on what the graph actually shows:

- **No shared identifiers, no alerts, no ring membership** → capped at 0.20
  (LOW), regardless of what the model predicts.
- **Weak evidence** → capped at 0.55.
- **Identity linkage confirmed (shared device/IP, ring membership) but no
  confirmed money trail and no nearby alert** → capped at 0.72 (HIGH, not
  CRITICAL).
- **Strong evidence** (ring + money trail + alert proximity) → the raw model
  score passes through untouched.

The dashboard's **D. Risk** panel shows both `raw_model_score` and the final
graph-adjusted `risk_score` whenever the guardrail fires.

**A genuinely interesting, honestly-reported side effect of the guardrail:**
in a layered-movement ring, the *leader* (who routes through a broker and
spends at a merchant) correctly scores HIGH, while a quiet *feeder* account
one hop earlier in the same ring — with no identity-link or broker evidence
of its own — scores LOW, even though it's ground-truth fraud. This is a
conscious design choice (no guilt-by-association without corroborating
evidence of the account's *own* behavior), confirmed and reported, not hidden,
in `evaluation/investigation_eval_report.json` (`false_negative_examples`).

## 11. Action system

The agent doesn't just output a verdict — it can **write simulated,
auditable graph mutations** (no real financial system is contacted). The
React/API flow is deliberately staged:

1. A demo analyst signs in with the environment-configured credentials.
2. `POST /api/actions/{case_id}/approve` records a short-lived approval tied
to the exact case, recommended action, and authenticated analyst.
3. `POST /api/actions/{case_id}/execute` requires that same analyst and the
separate JSON confirmation `{ "confirmed": true }`. The approval is one-time;
replay, expiry, identity mismatch, and missing confirmation are rejected.
4. The API reports execution only after the graph layer returns the expected
case ID and a verified final action-audit write.

The underlying action tools are unchanged in purpose:

```
verdict → authenticated API approval → explicit execution confirmation
   ├─ create_investigation_case   (always)
   ├─ ESCALATE_FOR_MANUAL_INVESTIGATION → flag_account + mark_high_risk +
   │                                      request_manual_review + escalate_case
   ├─ FLAG_AND_REQUEST_MANUAL_REVIEW     → flag_account + request_manual_review
   ├─ ADD_TO_WATCHLIST                   → add_to_watchlist
   └─ NO_ACTION_REQUIRED                 → (case record is the only artifact)
```

Graph Case/Action records retain the API case ID, action type, approver,
approval timestamp/expiry, execution actor, execution timestamp, outcome,
and graph-write status when the relevant writes succeed. The React Action
Center shows the server-returned actor metadata and only labels graph
write-back **verified** when the API confirms `written` for the expected
case ID. The legacy Streamlit direct-action button is disabled; it cannot
bypass this API flow.

### Demo authentication and write limitations

Set `RINGTRACE_AUTH_SECRET` (at least 32 bytes),
`RINGTRACE_DEMO_USERNAME`, and `RINGTRACE_DEMO_PASSWORD` in the environment
or local `.env`. They have no built-in defaults; incomplete/invalid auth
configuration fails closed for all action routes while read-only pages remain
available. Generate a signing secret with
`python -c "import secrets; print(secrets.token_urlsafe(32))"` and never commit
real credentials. Sessions use an HttpOnly, SameSite=Lax signed cookie with
Secure enabled by default, plus an API-provided CSRF token on every
state-changing action request. Only a local plain-HTTP demo may explicitly set
`RINGTRACE_AUTH_COOKIE_SECURE=false`; HTTPS requests remain Secure. The
default session lifetime is eight hours, and approvals expire after five
minutes; configure these periods with `RINGTRACE_SESSION_TTL_SECONDS` and
`RINGTRACE_APPROVAL_TTL_SECONDS`.

This is a **single-analyst hackathon demo**, not production identity
management: credentials are one environment-configured username/password
pair, session revocation and active API cases are process-local, and the app
should run as one API worker. The graph action path spans multiple FalkorDB
queries and has no cross-query transaction. If a step fails after earlier
writes, the API marks the outcome unknown/failed where possible, blocks
replay for that case, and instructs the analyst to inspect the graph before
any manual recovery. Earlier graph mutations may remain; the UI must not
claim write-back success in that situation.

Every actual action remains synthetic and is immediately visible on
re-investigation when its graph write succeeds; no real account or banking
system is contacted.

## 12. Evidence model

Two complementary representations of "why":

**1. The in-memory verdict dict** (`agent/decision.py::build_verdict`),
matching the shape `{claim, evidence[], tools_used[], risk_score,
confidence, action}`:

```python
{
  "verdict": "FRAUD RING CONFIRMED",            # claim
  "reasoning": [...],                           # evidence[]
  "tools_used": ["find_fraud_ring", ...],       # tools_used[]
  "risk_score": 0.99, "confidence": 0.95,       # risk_score, confidence
  "recommended_action": "ESCALATE_FOR_MANUAL_INVESTIGATION",  # action
  "ring_score": 0.43, "ring_confidence": 0.89, "ring_reasons": [...],
  ...
}
```

**2. The second-order evidence graph**, written into FalkorDB itself
(additive — the original `Case-[:INVESTIGATES]->Account` write is untouched):

```
(Account)-[:HAS_CASE]->(Case)-[:SUPPORTED_BY]->(Evidence)
                           │
                           └─[:RESULTED_IN]->(Action)-[:TRIGGERED_BY]->(GraphFinding)
```

This means "why did RingTrace take this action?" is not just a UI panel —
it's a literal, queryable graph fact (see the sample Cypher in
[Section 6](#6-graph-schema)). The React investigation workspace surfaces
the provenance panel and evidence ledger alongside the native SVG graph,
agent trace, and a confirmation-based simulated Action Center. GRAPH FACTS
→ TOOL CALLS → EVIDENCE → RISK → DECISION → ACTION are rendered from the
actual API result and tool evidence, not fabricated or re-derived.

## 13. Demo scenarios

### Fixed cases (the original 3, unchanged)

| ID | Case | Graph evidence | Risk class | Action |
|---|---|---|---|---|
| `A1100` | **A — isolated** | 1 linked account, no shared devices/IPs, no alerts | **LOW** | `NO_ACTION_REQUIRED` |
| `A1200` | **B — identity-linked only** | 5-account component, 4 share an IP, no money trail | **HIGH** | `FLAG_AND_REQUEST_MANUAL_REVIEW` |
| `A1027` | **C — ring + money flow** | 9-account component, shared device (7 accts), PageRank leader `A1001`, 5-hop money trail, pre-existing alert, leader spends mixer proceeds at a synthetic merchant | **CRITICAL** | `ESCALATE_FOR_MANUAL_INVESTIGATION` |

Identical decision logic run against three different graph neighborhoods
produces three genuinely different outcomes — asserted directly in
`tests/test_decision.py::test_verdicts_differ_across_cases`.

### Additive scenarios (DEMO-01 … DEMO-06)

Added to broaden coverage without touching the cases above — including two
deliberate **benign look-alikes** that a naive detector would wrongly flag:

| ID | Account(s) | What it tests |
|---|---|---|
| `DEMO-01` | `A1300` | Trivial clean/isolated account — sanity check for LOW. |
| `DEMO-02` | `A1310`/`A1311` | **Benign**: shared device, zero money movement (e.g. household). Must NOT escalate on identity-link alone. |
| `DEMO-03` | `A1320`-`A1323` | Reciprocal wash-trading ring — dense back-and-forth money flow, **no shared identity at all**. Tests the reciprocal-transfer signal specifically. |
| `DEMO-04` | `A1330`→`A1331`→`A1332` | Full layered-movement chain ending in a broker cash-out **and a synthetic merchant purchase**. |
| `DEMO-05` | `A1340`/`A1341` | **Benign**: two unrelated accounts who happen to shop at the same popular merchant. Must NOT be treated as a ring signal. |
| `DEMO-06` | `A1350`/`A1351` | Genuinely **ambiguous** — one shared device, one small transfer, nothing else. A well-calibrated agent should land on a measured verdict, not an overconfident one. |

See `docs/DEMO_SCRIPT.md` for the full narrated 3–5 minute walkthrough, and
`evaluation/investigation_eval_report.json` for how well the agent actually
performs on all of the above, measured against synthetic ground truth.

## 14. Screenshots

No screenshots are bundled; mockups are not presented as real captures.
The React interface is built with Vite and served by FastAPI on port `8000`.
For the current security changes, the frontend build and no-graph API tests
passed, but an authenticated graph-write browser smoke test was not possible
without a disposable FalkorDB service (see Section 18). The existing
screenshot helper targets the preserved Streamlit baseline and is not a React
browser-test harness.

## 15. Setup

### Option A — Docker (recommended)

```bash
cp .env.example .env     # configure the demo analyst values to enable actions
docker compose up --build
```

To enable simulated actions, set `RINGTRACE_AUTH_SECRET` (at least 32 bytes),
`RINGTRACE_DEMO_USERNAME`, and `RINGTRACE_DEMO_PASSWORD` in `.env` first.
If left blank, read-only pages remain usable and all action routes fail
closed. For plain local HTTP at `http://localhost:8000`, also set
`RINGTRACE_AUTH_COOKIE_SECURE=false`; keep the default Secure cookie for
HTTPS deployments. FastAPI serves both the React SPA and its `/api/*` routes
on this single URL; FalkorDB stays private inside the Compose network. On
first startup, the app loads the synthetic demo graph and trains the risk
model if the graph is empty.

### Option B — Local development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill the signing secret and demo username/password to enable actions.
# For plain local HTTP only, also set RINGTRACE_AUTH_COOKIE_SECURE=false.
npm --prefix frontend ci
npm --prefix frontend run build

./scripts/setup_falkordb_local.sh      # starts FalkorDB via Docker if available
./scripts/run_pipeline.sh              # generate data + load graph + train model
uvicorn api.main:app --env-file .env --host 0.0.0.0 --port 8000
```

Open **http://localhost:8000**. If Docker is unavailable, point
`FALKORDB_HOST`/`FALKORDB_PORT` in `.env` at a reachable FalkorDB service
instead of running the local-DB helper.

For development without a build, run these in separate terminals:

```bash
uvicorn api.main:app --env-file .env --host 0.0.0.0 --port 8000
npm --prefix frontend run dev
```

Vite proxies `/api` to FastAPI; open **http://localhost:5173** while using
the development server. The original Streamlit implementation remains
available separately with `streamlit run app/dashboard.py
--server.address 0.0.0.0 --server.port 8501`.

All scenarios are synthetic. `A1027` is a deterministic seeded demo account,
not a real customer or fraud allegation.

## 16. Docker

The Compose stack contains two services: `falkordb` (healthchecked and
private to the Compose network) and `ringtrace`. The multi-stage Dockerfile
builds the Vite frontend with Node, copies the production assets into the
Python image, and serves them together with FastAPI. On first startup, the
entrypoint seeds the synthetic graph and trains the model if the graph is
empty.

```bash
docker compose up --build
```

The only published application port is **8000** (`http://localhost:8000`).
Redis/FalkorDB and its optional browser UI are not published to the host by
default, so the judge-facing app has one URL.

**Honest disclosure:** Docker/Podman is not installed in this sandbox, so a
container build/run has not been performed here. The Compose file now passes
the explicit demo-auth environment variables into the API container; this
change has not been exercised in a container. The frontend build and no-graph
API tests are documented in Section 18. The prior disposable-graph baseline
predates the current auth/audit changes; no current graph write-back result is
claimed. Validate the image on a host with Docker before using the demo.

## 17. Environment variables

See `.env.example` for the full annotated list. Highlights:

| Variable | Purpose | Default |
|---|---|---|
| `FALKORDB_HOST` / `FALKORDB_PORT` | Where to reach FalkorDB | `localhost:6379` |
| `FALKORDB_GRAPH` | Graph name | `ringtrace` |
| `FALKORDB_USERNAME` / `FALKORDB_PASSWORD` | Optional graph authentication | _(empty)_ |
| `FALKORDB_TLS` | Required `1` for non-loopback hosts; loopback permits `0` | `0` |
| `RINGTRACE_AUTH_SECRET` | Session-signing secret (minimum 32 bytes); missing/invalid disables action routes | _(empty; fail closed)_ |
| `RINGTRACE_DEMO_USERNAME` / `RINGTRACE_DEMO_PASSWORD` | Environment-configured demo analyst credentials | _(empty; fail closed)_ |
| `RINGTRACE_SESSION_TTL_SECONDS` | Signed session lifetime, 1–86400 seconds | `28800` |
| `RINGTRACE_APPROVAL_TTL_SECONDS` | Approval validity, 1–3600 seconds | `300` |
| `RINGTRACE_AUTH_COOKIE_SECURE` | Secure by default; `false` only opts out on local HTTP | `true` |
| `LLM_PROVIDER` | `none` \| `groq` \| `openai` | `none` (rule-based fallback) |
| `LLM_API_KEY` | API key — **never hardcoded**, read from env only | _(empty)_ |
| `LLM_BASE_URL`, `LLM_MODEL` | OpenAI-compatible endpoint + model | Groq `llama-3.3-70b-versatile` |
| `LLM_TIMEOUT_SECONDS`, `LLM_MAX_TOOL_ITERATIONS` | Guardrails against a hung/looping agent | `20`, `8` |
| `RING_COUNT`, `ACCOUNTS_PER_RING`, `LEGIT_PERSON_COUNT`, `NORMAL_TRANSACTION_COUNT`, `NOISE_LEVEL`, `FRAUD_RATIO`, `RANDOM_SEED` | Synthetic data generator knobs | see `.env.example` |

## 18. Testing

Build the frontend and run the Python suite. Any test that performs graph
writes must use the explicit disposable-graph opt-in and a reachable port other
than `6379`; the harness skips graph-dependent tests without probing the
live/default graph when no safe target is configured.

```bash
npm --prefix frontend run build

# Read-only/unit/API tests without a graph (graph-dependent tests skip):
env -u RINGTRACE_TEST_DISPOSABLE -u FALKORDB_PORT -u FALKORDB_HOST \
  -u FALKORDB_GRAPH .venv/bin/pytest tests/ -q

# Only after verifying a disposable synthetic graph is listening on 6380:
RINGTRACE_TEST_DISPOSABLE=1 FALKORDB_HOST=127.0.0.1 FALKORDB_PORT=6380 \
FALKORDB_GRAPH=ringtrace PYTHONPATH=. pytest tests/ -q
```

For this action-security hardening, the latest no-graph run completed **70
passed, 30 skipped**. The 30 skipped cases are graph-dependent, including the
real authenticated action-write/audit integration. A read-only health check to
the configured safe test endpoint at `127.0.0.1:6380` returned connection
refused because no disposable FalkorDB service is available. Docker and
`redis-server` are not installed in this sandbox; port `6379` was never
selected for an action-write test and was not mutated. Consequently, no current
graph-write integration verification is claimed for these security changes.
The earlier 74-pass disposable-graph result predates this hardening and does
not validate the new auth/audit write path.

`test_auth.py` covers missing/weak auth configuration, signed session cookie
properties and expiry, CSRF, logout/revocation, case/action/analyst binding,
approval expiry, explicit confirmation, and safe session handling. `test_api.py`
checks the protected API responses and server-derived actor fields;
`test_actions.py` checks fail-closed graph-result handling;
`test_legacy_actions.py` prevents the direct Streamlit bypass from returning.
The integration tests in `test_integration_falkordb.py` remain guarded by the
disposable-graph fixture, including the corrected transfer-aggregation
fan-out regression and the authenticated graph-audit/write verification.

The frontend TypeScript check and production Vite build completed successfully
with `npm --prefix frontend run build`.

## 19. Evaluation

Two **distinct, separately-reported** evaluation layers:

1. **`evaluation/synthetic_eval_report.json`** — the RandomForest classifier
   alone (accuracy/precision/recall/F1/ROC-AUC on a held-out split). See
   [Section 10](#10-ml-risk-scoring).

2. **`evaluation/investigation_eval_report.json`** (new,
   `evaluation/evaluate_investigation.py`) — the FULL agent pipeline
   (graph tools + ring score + ML + guardrail + decision rules), measured
   against synthetic ground truth:

   - **Ring detection** (WCC vs. planted rings): mean precision 0.905, mean
     recall 0.988 across 10 planted rings — with one informative failure
     case reported, not hidden: a `central_mule_leader` ring's WCC component
     merged into a 153-account component shared with the background legit
     population (precision 0.052 for that ring specifically), because the
     legit population's own cross-circle noise transactions transitively
     connect much of it over time. This is exactly why
     [Section 9](#9-graph-algorithms)'s composite ring score — not raw
     component size — is what the decision engine actually reads.
   - **Leader identification** (PageRank vs. ground-truth leader role): 4/4
     correct (100%) across every ring with a labeled leader.
   - **Money-path success rate**: 3/4 (75%) — one generated
     `central_mule_leader` ring's fan-in pattern doesn't produce a direct
     path within 6 hops from an arbitrary feeder (expected: money flows IN
     to the leader from many feeders, not through them sequentially).
   - **Identity-link recall**: 5/5 (100%) on accounts with known shared
     device/IP signals.
   - **Action accuracy vs. ground truth** (fresh balanced 80-account sample:
     40 fraud / 40 legitimate, `random_state=42`; full pipeline): accuracy
     0.988, precision 1.0, recall 0.975, **0 false positives**, 1 false
     negative (`A1331`, which has no corroborating evidence of its own — see
     [Section 10](#10-ml-risk-scoring)). The separate ring check also reports
     that 23 of 30 sampled legitimate accounts fall into a large WCC component;
     that synthetic-graph limitation is not hidden by the aggregate metrics.

Run it yourself: `python -m evaluation.evaluate_investigation` (takes ~90s;
runs a full investigation per sampled account).

## 20. Limitations

- The RandomForest is trained on a small, synthetic dataset — its metrics
  describe recovering a planted structure, not real-world generalization.
- The rule-based decision thresholds (guardrail caps, risk-class cutoffs,
  ring-score weights) are hand-tuned for this demo's scenario design, not
  calibrated against real fraud data.
- The background legit population's own weak interconnectivity means raw
  WCC component size is a noisy signal on its own (see
  [Section 19](#19-evaluation)) — mitigated, not eliminated, by the
  composite ring score.
- A quiet "feeder" account deep in a layered chain with no identity-link
  evidence of its own may legitimately score LOW despite being ground-truth
  fraud — an intentional guardrail tradeoff against guilt-by-association,
  reported honestly in the evaluation output rather than tuned away.
- No browser screenshot or Docker image build is available from this sandbox.
  The current frontend build and no-graph API suite passed, but the new
  authenticated graph-write path lacks a current disposable-graph smoke test;
  see [Sections 14](#14-screenshots), [16](#16-docker), and [18](#18-testing).
- Demo analyst authentication is an environment-configured single username/
  password pair, not production identity management, multi-factor auth, or a
  multi-tenant case-management system. Session revocation and active API cases
  are process-local; use one API worker. Durable graph action writes are
  multi-query and not transactional: an interrupted sequence may leave partial
  graph changes, so inspect the graph before any manual recovery. The API
  blocks replay and reports write-back as unknown unless the final audit write
  is confirmed.

## 21. Future roadmap

- Materialize `component_id` / `pagerank_money` as node properties on a
  schedule, so large-graph investigations don't re-run `algo.*` per request.
- Expand the synthetic generator with adversarial patterns (rings that
  deliberately avoid shared devices/IPs, relying only on timing/velocity).
- Tighten the legit background population's circle isolation so raw
  component size is a cleaner signal on its own (currently compensated for,
  not eliminated, by the ring-score composite — see Section 19).
- A shared durable session/approval store and proper analyst identity
  management; the current environment-configured demo gate is intentionally
  single-user and process-local.
- A CI pipeline running the full test suite + static Docker validation on
  every push (also explicitly deprioritized for this submission in favor of
  P0/P1 feature work).
- Human-in-the-loop feedback loop: investigator overrides feed back into
  model retraining.

---

## 22. Event-day payment-corridor contribution

**Proposed Track 01 contribution:** a **Time-Respecting Payment-Corridor
Investigator** built around an event-centred synthetic graph. This is a new,
separately namespaced workflow in `eventday/`; it does not relabel or replace
the pre-event account/ring queries, agent, risk model, or history described
above. This distinction is both technical and provenance-relevant.

The rules excerpt supplied to the team asks whether an existing project may
continue but omits the answer. **Eligibility is unresolved** until organizers
confirm it in writing. A materially separate event-day implementation does
not itself establish eligibility. Do not publish this private repository or
submit it on the team's behalf until the team has reviewed eligibility, the
full Git history for secrets, licensing/data rights, and all required demo
artifacts.

### Track declaration and graph-native core

**Track: Track 01 — Agents That Act on Connected Data.** FalkorDB is intended
to be the primary source of connected payment evidence in this workflow. The
agent reads actual graph rows, adapts follow-up queries to returned wallet
paths, and runs FalkorDB PageRank/WCC on the isolated event-day graph while
returning algorithm rows only for observed corridor wallets. A separately
authenticated and explicitly confirmed write may create only a
simulated manual-review proposal plus its provenance in the synthetic graph.
It does not freeze, debit, flag a real customer, or contact an external
financial system.

The event-day model scopes every relevant node/edge to a `dataset_id` and
`synthetic=true`:

| Node | Properties / purpose |
|---|---|
| `Wallet` | `id`; payment endpoints and flow stops |
| `PaymentEvent` | `id`, `occurred_at` (UTC epoch seconds), `amount`, `currency`, `channel`; immutable investigation anchor |
| `Device`, `BeneficialOwner` | Synthetic shared-identity evidence |
| `PayoutDestination` | Synthetic cash-out endpoint |
| `CorridorInvestigation` | Graph-backed record created with a confirmed proposal |
| `ReviewProposal` | Simulated manual-review proposal and analyst approval metadata |
| `GraphEvidence` | Exact successful Cypher, bound parameters, row count, and summary |

Relationships: `PaymentEvent-[:FROM/TO]->Wallet`; `Wallet-[:FUNDED_TO {
event_id, occurred_at, amount, currency}]->Wallet`; `Wallet-[:CASHED_OUT_TO]->PayoutDestination`; `Wallet-[:AUTHENTICATED_ON]->Device`; `BeneficialOwner-[:CONTROLS]->Wallet`; materialized `Wallet-[:COORDINATED_WITH]->Wallet`; and review provenance `ANALYZED_PAYMENT`, `ABOUT_PAYMENT`, `BASED_ON`, `SUPPORTED_BY`. The additive loader in `eventday/seed.py` contains synthetic data only and never wipes a graph.

### Time-respecting Cypher

`eventday/graph.py::trace_corridor` binds the event ID, dataset, and epoch
bounds as parameters; only the validated integer hop bound is interpolated.
Its core query is:

```cypher
MATCH path = (start:Wallet {id: $wallet_id, dataset_id: $dataset_id, synthetic: true})
              -[:FUNDED_TO*1..4]->
              (sink:Wallet {dataset_id: $dataset_id, synthetic: true})
WITH path, relationships(path) AS legs, sink
WHERE all(r IN legs WHERE r.dataset_id = $dataset_id AND r.synthetic = true
          AND r.occurred_at > $after_ts AND r.occurred_at <= $until_ts)
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

The predicates ensure each transfer follows the anchor payment and is strictly
later than the previous transfer, within a bounded window and hop count. If
routes are returned, the deterministic planner queries shared devices and
owners for the observed wallet IDs, then calls:

```cypher
CALL algo.pageRank('Wallet', 'FUNDED_TO') YIELD node, score
WITH node, score
WHERE node.dataset_id = $dataset_id AND node.synthetic = true
  AND node.id IN $wallet_ids
RETURN node.id AS wallet_id, score AS page_rank ORDER BY page_rank DESC;

CALL algo.WCC({nodeLabels: ['Wallet'], relationshipTypes: ['COORDINATED_WITH']})
YIELD node, componentId
WITH node, componentId
WHERE node.dataset_id = $dataset_id AND node.synthetic = true
  AND node.id IN $wallet_ids
RETURN node.id AS wallet_id, componentId;
```

These are graph signals, not guilt labels. Shared devices can be benign;
PageRank/WCC do not establish fraud. The displayed review-signal score is an
explicit heuristic, **not a calibrated fraud probability**. A failed query is
reported as unavailable/unknown and is never treated as a zero-row finding.
The query text, parameters, errors, and returned rows are exposed in the UI.

### Local disposable setup and tests

The event-day API is disabled by default and uses a dedicated connection
with explicitly configured `RINGTRACE_EVENTDAY_FALKORDB_HOST/PORT` (the local
example uses loopback port 6380); it does not inherit the pre-existing graph
endpoint. After verifying that
port 6380 is free and suitable for a throwaway service, local setup is:

```bash
cd frontend && npm ci && npm run build && cd ..
docker run --rm -d --name ringtrace-eventday-falkordb \
  -p 127.0.0.1:6380:6379 falkordb/falkordb:latest
export RINGTRACE_EVENTDAY_ENABLED=1 RINGTRACE_EVENTDAY_DISPOSABLE=1
export RINGTRACE_EVENTDAY_FALKORDB_HOST=127.0.0.1 RINGTRACE_EVENTDAY_FALKORDB_PORT=6380
export RINGTRACE_EVENTDAY_GRAPH=ringtrace_eventday_test
export FALKORDB_HOST=127.0.0.1 FALKORDB_PORT=1  # isolate legacy preview graph checks
export RINGTRACE_TEST_DISPOSABLE=1
pytest -q tests/eventday/test_graph_integration.py  # read-only empty check, then synthetic seed/tests
unset RINGTRACE_TEST_DISPOSABLE
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

The event-day graph client refuses port 6379 and graph names outside the
`ringtrace_eventday` namespace before constructing a FalkorDB client. Remote
Cloud hosts are accepted only with explicit TLS, username/password, and the
exact `ringtrace_eventday_test` graph. Every connection requires explicit
host/port and never falls back to localhost. Seeding additionally requires the enabled and
disposable opt-ins. Full connection details are in
[`docs/EVENTDAY_TRACK_01.md`](docs/EVENTDAY_TRACK_01.md).

The pre-existing legacy graph connection in `graph/connection.py` has been
hardened to enforce a similar fail-closed transport policy: non-loopback
hosts now require `FALKORDB_TLS=1` plus configured `FALKORDB_USERNAME` and
`FALKORDB_PASSWORD`; loopback retains its existing local-development behavior.
The transport policy is checked before any connection attempt. The Docker
Compose app port is now published to `127.0.0.1:8000` by default so the demo
app is not exposed to the network.

Fast unit tests cover planner semantics, parameterized Cypher/hop validation,
seed safety, and the one-time analyst approval flow. Real graph assertions are
separately gated by `RINGTRACE_TEST_DISPOSABLE=1` in
`tests/eventday/test_graph_integration.py`; they must run only against a
verified throwaway instance, never the preview or any shared/live graph.

### AI disclosure and submission status

AI coding assistance in the Arena Agent Mode session drafted/implemented the
event-day graph layer, deterministic planner/API/UI, tests, and documentation.
This work is not represented as independently human-authored. Before
submission, the team must inspect and understand the Cypher and decisions,
meaningfully contribute and verify the code, and update this disclosure with
its actual review/changes and any additional AI tools used. The supplied rules
allow AI assistance but require disclosure and meaningful participant
contribution.

**Not yet submission-ready:** no disposable FalkorDB integration run, browser
or Docker QA, action-write verification, demo video, organizer eligibility
answer, full-history secret audit, license review, or deliberate public-release
approval is recorded here. Historical pre-event tests do not verify the new
workflow. See the checklist in `docs/EVENTDAY_TRACK_01.md` and do not claim
completion until each item is actually done.

---

## 🔒 Security Hardening

RingTrace implements defense-in-depth security measures:

### Transport Security
- **TLS Enforcement**: Non-loopback FalkorDB connections require `FALKORDB_TLS=1`
- **Credential Validation**: Remote connections require explicit username/password
- **Fail-Closed Design**: Invalid configurations raise errors before connection attempts
- **Loopback Exception**: Local development (127.0.0.1, localhost, ::1) permits plaintext for convenience

### Application Security
- **Signed Sessions**: itsdangerous-based session tokens with configurable TTL
- **CSRF Protection**: All state-changing API endpoints require CSRF tokens
- **Approval Workflow**: Actions require explicit analyst approval before execution
- **Audit Trail**: All actions are logged with timestamps and analyst identity

### Infrastructure Security
- **Network Isolation**: Docker Compose binds to 127.0.0.1:8000 (not 0.0.0.0)
- **Credential Management**: Secrets via environment variables, never hardcoded
- **Disposable Graphs**: Test databases are isolated and explicitly marked as disposable

---

## 🌐 Deployment Options

### Option 1: Railway (Recommended for Hackathon)

**Why Railway?**
- Free tier: $5/month credit (sufficient for demo)
- One-click Docker deployment
- Automatic HTTPS
- Custom domains supported
- Database add-ons available

**Steps:**
```bash
# 1. Install Railway CLI
npm i -g @railway/cli

# 2. Login to Railway
railway login

# 3. Create new project
railway init

# 4. Deploy
railway up

# 5. Add environment variables
railway variables set FALKORDB_HOST=your-falkordb-host
railway variables set FALKORDB_PORT=6379
railway variables set RINGTRACE_AUTH_SECRET=$(openssl rand -hex 32)
railway variables set RINGTRACE_DEMO_USERNAME=analyst
railway variables set RINGTRACE_DEMO_PASSWORD=your-secure-password
```

**Pros:** Easy setup, free tier, automatic deployments  
**Cons:** Requires external FalkorDB instance

---

### Option 2: Render

**Why Render?**
- Free tier for web services
- Native Docker support
- Automatic HTTPS
- Good for demos

**Steps:**
1. Connect your GitHub repository to Render
2. Create a new "Web Service"
3. Select "Docker" as runtime
4. Add environment variables in Render dashboard
5. Deploy

**Pros:** Simple GitHub integration, free tier  
**Cons:** Cold starts on free tier, requires external FalkorDB

---

### Option 3: Fly.io

**Why Fly.io?**
- Free tier with generous limits
- Global edge deployment
- Native Docker support
- Built-in Redis (can run FalkorDB)

**Steps:**
```bash
# 1. Install flyctl
curl -L https://fly.io/install.sh | sh

# 2. Login
fly auth login

# 3. Launch app
fly launch

# 4. Deploy
fly deploy

# 5. Set secrets
fly secrets set FALKORDB_HOST=your-host
fly secrets set RINGTRACE_AUTH_SECRET=$(openssl rand -hex 32)
```

**Pros:** Global deployment, can run FalkorDB on same platform  
**Cons:** More complex setup, requires fly.toml configuration

---

### Option 4: Self-Hosted VPS (DigitalOcean, Linode, etc.)

**Why VPS?**
- Full control over infrastructure
- Can run FalkorDB and app on same server
- Cost-effective for long-term use

**Steps:**
```bash
# 1. Provision VPS (2GB+ RAM recommended)
# 2. Install Docker and Docker Compose
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# 3. Clone repository
git clone https://github.com/ravigohel142996/Ring_Trace_agent.git
cd Ring_Trace_agent

# 4. Configure environment
cp .env.example .env
nano .env  # Edit with your settings

# 5. Deploy
docker-compose up -d

# 6. Setup reverse proxy (nginx/caddy) for HTTPS
```

**Pros:** Full control, cost-effective, can run everything on one server  
**Cons:** Requires server management, manual HTTPS setup

---

### Option 5: Local Demo with ngrok (Quick & Easy)

**Why ngrok?**
- No deployment required
- Instant public URL
- Perfect for live demos

**Steps:**
```bash
# 1. Start RingTrace locally (see Quick Start)
docker-compose up -d

# 2. Install ngrok
npm i -g ngrok

# 3. Create tunnel
ngrok http 8000

# 4. Share the ngrok URL (e.g., https://abc123.ngrok.io)
```

**Pros:** Instant setup, no deployment, perfect for live demos  
**Cons:** URL changes on restart, not suitable for long-term use

---

### Deployment Comparison

| Platform | Free Tier | HTTPS | FalkorDB | Setup Time | Best For |
|----------|-----------|-------|----------|------------|----------|
| **Railway** | $5/mo | ✅ | External | 5 min | Hackathon demos |
| **Render** | Yes | ✅ | External | 10 min | Simple deployments |
| **Fly.io** | Yes | ✅ | Built-in | 20 min | Global apps |
| **VPS** | No | Manual | Built-in | 30 min | Production |
| **ngrok** | Yes | ✅ | Built-in | 2 min | Live demos |

**Recommendation:** Use **Railway** for hackathon submission (easy + free) or **ngrok** for live demo during judging.

---

## 👥 Team & Credits

### Team

**Ravi Gohel**
- Role: Lead Developer & Architect
- Responsibilities: System architecture, FalkorDB integration, agent design, security hardening

**Nandini Saini** & **Himesh Rupchandani**
- Role: Design & documentation

### Technologies

- **Graph Database:** [FalkorDB](https://www.falkordb.com/) - Graph-native reasoning engine
- **Backend:** [FastAPI](https://fastapi.tiangolo.com/) - Modern Python web framework
- **Frontend:** [React 19](https://react.dev/) + [TypeScript](https://www.typescriptlang.org/) + [Vite](https://vitejs.dev/)
- **Authentication:** [itsdangerous](https://itsdangerous.palletsprojects.com/) - Secure session signing
- **ML:** [scikit-learn](https://scikit-learn.org/) - Risk scoring models
- **Testing:** [pytest](https://pytest.org/) - Comprehensive test suite

### Acknowledgments

- **WeMakeDevs** and **FalkorDB** for organizing Graph Hacks 2026
- The open-source community for the amazing tools and libraries
- Arena AI for providing Agent Mode development environment

---

## 📋 Hackathon Submission Checklist

Before submitting to WeMakeDevs × FalkorDB Graph Hacks 2026:

### ✅ Completed

- [x] **Track 01 Alignment**: Agents that act on connected data using FalkorDB
- [x] **Working Demo**: Both core and event-day workflows functional
- [x] **Authentication**: Analyst login and approval workflow
- [x] **Security Hardening**: Transport policy, CSRF, session management
- [x] **Test Suite**: 100 tests passing (6 transport policy tests + 94 core tests)
- [x] **Documentation**: Comprehensive README with setup instructions
- [x] **Deployment Ready**: Docker Compose + multiple deployment options documented
- [x] **Synthetic Data**: All demo data is synthetic and clearly labeled

### 🔄 In Progress / Needs Team Review

- [ ] **Demo Video**: Record 3-5 minute walkthrough of key features
- [ ] **Live Deployment**: Deploy to Railway/Render for judges to access
- [ ] **Organizer Eligibility**: Confirm existing-project eligibility with organizers
- [ ] **License Selection**: Choose and add open-source license (MIT recommended)
- [ ] **Secret Audit**: Review full Git history for any committed secrets
- [ ] **Team Contributions**: Document specific human contributions vs AI assistance

### 📝 Before Public Release

- [ ] Remove any temporary hackathon-specific code/comments
- [ ] Update all placeholder credentials
- [ ] Verify all links in README work
- [ ] Test deployment instructions on clean environment
- [ ] Get team approval for public release

---

## 📂 Project Structure

```
RingTrace/
│
├── 🎯 Core Investigation System
│   ├── api/                 # FastAPI routes & request models
│   ├── agent/               # Reasoning loop & decision engine
│   ├── tools/               # Investigation & action tools
│   ├── graph/               # FalkorDB connection & Cypher queries
│   ├── models/              # ML risk scoring
│   └── ingestion/           # Synthetic data generator
│
├── ⭐ Event-Day Payment Corridor (Track 01)
│   ├── eventday/            # Time-respecting corridor investigator
│   │   ├── graph.py         # Event-day graph queries
│   │   ├── engine.py        # Corridor traversal engine
│   │   ├── api.py           # Event-day API routes
│   │   └── seed.py          # Synthetic payment data
│   └── tests/eventday/      # Event-day test suite
│
├── 🎨 Frontend
│   └── frontend/            # React + TypeScript + Vite SPA
│       ├── src/
│       │   ├── pages/       # Investigate, Corridor, Cases, Risk, Graph
│       │   ├── components/  # Reusable UI components
│       │   └── api/         # API client
│       └── public/          # Static assets
│
├── 🧪 Testing & Evaluation
│   ├── tests/               # Python test suite (100 tests)
│   ├── evaluation/          # ML model evaluation
│   └── data/                # Synthetic datasets
│
├── 🐳 Deployment
│   ├── docker/              # Dockerfile & entrypoint
│   ├── docker-compose.yml   # Multi-container setup
│   └── .env.example         # Environment template
│
└── 📚 Documentation
    ├── docs/                # Detailed documentation
    │   ├── STATUS.md        # Project status
    │   ├── DEMO_SCRIPT.md   # Demo walkthrough
    │   └── EVENTDAY_TRACK_01.md  # Track 01 details
    └── README.md            # This file
```

---

## 📞 Support & Contact

**Questions about RingTrace?**

- 📧 **Email**: ravi.gohel142996@marwadiuniversity.ac.in
- 💬 **GitHub Issues**: [Open an issue](https://github.com/ravigohel142996/Ring_Trace_agent/issues)
- 📖 **Documentation**: See `docs/` directory for detailed guides

---

## 📄 License

This project is currently unlicensed. A license will be added before public release.

**Recommended:** MIT License (permissive, hackathon-friendly)

---

<div align="center">

### 🕵️ **Follow the graph. Trace the money. Respect the clock.**

**Built with ❤️ for WeMakeDevs × FalkorDB Graph Hacks 2026**

[⬆ Back to Top](#-ringtrace--fraud-ring-detective-agent)

</div>

