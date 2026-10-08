# RingTrace — 3–5 Minute Judge Walkthrough

**Tagline:** *Follow the graph. Trace the money. Expose the ring.*

This walkthrough uses the React/Vite investigation workspace served by
FastAPI. It follows a deterministic **synthetic** A1027 demo account from
live FalkorDB graph queries to a human-approved, explicitly confirmed
simulated action. No real person, account, payment, or financial system is
involved.

```text
FALKORDB GRAPH → AGENT TOOL TRACE → EVIDENCE → RISK DECISION → APPROVED SIMULATED ACTION
```

## 0. Setup (before judges arrive)

```bash
docker compose up --build
```

Open **http://localhost:8000**. The app and `/api/*` endpoints share this one
URL; FalkorDB remains private inside the Compose network. On an empty graph,
the entrypoint loads the synthetic dataset and trains the risk model.

For a local setup without Docker, follow the local-development instructions
in the README. Confirm the graph health indicator is connected, select
`CASE-C · Ring with money flow`, and leave the account as `A1027`.

## 1. The hook (20s)

> “Fraud rings don't look suspicious one row at a time. What gives one away
> is structure: shared devices, connected accounts, and a trail of money.
> RingTrace asks FalkorDB for that connected context, then shows every tool
> result behind its decision. All data in this demo is synthetic.”

Use the preselected `CASE-C` scenario and click **Run investigation**.

## 2. Live graph context and tool trace (40s)

> “The first step is `get_account_context`: the agent queries the live graph
> for this account's owner, devices, alerts, transfers, and neighboring
> entities. The later steps are not prewritten results. They are tool calls
> made against the graph that was just loaded for this demo.”

Point to the **Agent Trace** and **Evidence Ledger**. With the default seed,
the rule-based investigator returns seven successful tool steps:

- `get_account_context`
- `find_fraud_ring`
- `rank_ring_leaders`
- `trace_money_path`
- `find_identity_links`
- `calculate_risk_score`
- `generate_verdict`

The agent uses the deterministic rule-based planner by default; an LLM key
is optional. The page displays the actual tool outputs and captured Cypher
provenance, not fabricated result cards.

## 3. FalkorDB algorithms and relationships (45s)

> “`find_fraud_ring` runs FalkorDB's WCC graph algorithm over materialized
> `LINKED_TO` edges. `rank_ring_leaders` uses PageRank on money-flow
> relationships. RingTrace doesn't approximate these graph operations in
> the browser.”

Point to the graph panel, which is rendered as native SVG from the API's
investigation graph payload. With the default synthetic dataset, A1027 is
in a nine-account component, shares a device with seven other accounts,
and the PageRank leader is `A1001`.

> “Then `trace_money_path` returns the five-hop path
> A1027 → A1023 → A1024 → A1025 → A1026 → A1001. The graph view, path, and
> account counts are all derived from FalkorDB results.”

Use graph pan/zoom, filters, node selection, fit, or reset to inspect the
returned neighborhood.

## 4. Risk and the evidence-backed decision (40s)

> “The risk model consumes graph-derived features, and the guardrail limits
> scores that lack corroborating graph evidence. On this seeded A1027 graph,
> the live investigation returned a CRITICAL score of 0.9852, a 0.95
> confidence verdict, and `ESCALATE_FOR_MANUAL_INVESTIGATION`.”

Show the **Why This Action?** provenance panel. It links graph facts, the
successful tool calls, evidence, risk, verdict, and recommendation. The
five-hop flow, nine-account component, existing alert, and leader ranking
are visible in the agent result. Remind judges that the trained model and
its evaluation data are synthetic and are not evidence of real-world fraud
accuracy.

## 5. Human approval and confirmed simulated write-back (40s)

In **Action Center**, point out the **SIMULATED ACTION** label and the
explanation that no financial system is modified.

> “The recommendation cannot execute silently. First an investigator
> approves it. The execution button then opens a final review dialog showing
> the action and graph write. I must explicitly confirm that dialog.”

Click **Approve recommendation**, then **Execute simulated action**, review
the dialog, and click **Confirm simulated execution**. The existing
RingTrace action tools write a case and supporting evidence to the demo
FalkorDB graph. The UI shows the returned graph case ID and write status.

> “This is a real graph write to the local synthetic investigation graph,
> but it does not flag a real account or contact a payment system. The
> `HAS_CASE`, `SUPPORTED_BY`, `RESULTED_IN`, and `TRIGGERED_BY` links let us
> query why the simulated action was recorded.”

## 6. Contrast cases and close (30s)

Optionally investigate `A1100` (isolated) and `A1200` (identity-linked
without the A1027 money trail) to show that the same engine can produce
lower-severity outcomes for different graph neighborhoods.

Close with:

> “FalkorDB is not merely used to visualize RingTrace relationships. It is
the live graph context layer used by the agent to investigate connected
evidence, make decisions, and trigger actions. Follow the graph. Trace the
money. Expose the ring.”

---

## Before presenting

- Ensure `/api/graph/health` reports `connected: true` and the graph has the
  synthetic seed data. `python -m ingestion.load_to_falkordb` reloads the
  deterministic demo plus generated synthetic population.
- The first simulated execution writes graph records. Re-seed the demo graph
  before a fresh run if a clean action ledger is desired.
- Do not describe synthetic A1027 records as real customer data or a real
  fraud finding.
