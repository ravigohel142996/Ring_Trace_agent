# RingTrace — 3–5 Minute Judge Walkthrough

**Tagline:** *Follow the graph. Trace the money. Expose the ring.*

This is the exact script used to demo RingTrace to Track 01 judges
("Agents That Act on Connected Data"). It follows ONE alert end-to-end and
narrates each screen so the causal chain

```
GRAPH CONTEXT → GRAPH TOOL → AGENT DECISION → INVESTIGATION ACTION → EVIDENCE
```

is impossible to miss. Total runtime: ~4 minutes if read at a natural pace.

---

## 0. Setup (before judges arrive)

```bash
docker compose up --build        # or: see README "Setup" section for the
                                  # local-Python fallback path
```

Open the dashboard, leave it on the **Investigation Input** screen with
nothing run yet.

## 1. The hook (20s)

> "Fraud rings don't look suspicious one row at a time. A single account, a
> single transaction — nothing's wrong. What gives a ring away is
> *structure*. RingTrace is an agent that investigates by walking a graph,
> not by guessing from a prompt. Watch what happens when I give it one
> alert."

Type `A1027` into **Account / Alert ID** (or pick the "Case C" preset) and
click **Run Investigation**.

## 2. Graph context (30s)

While it runs:

> "The agent's first move is never a guess — it's a real Cypher query
> against FalkorDB: `get_account_context`. It pulls the account's owner,
> devices, IPs, brokers, alerts, and direct transfers. That's the only
> 'free' information it gets. Everything else, it has to go find."

Open the **B. Agent Trace** tab, expand the first step, point at the raw
JSON: this is a real tool call, real data, not canned text.

## 3. Ring detection — FalkorDB's own algorithm (40s)

> "Next it asks: is this account part of something bigger? That's
> `find_fraud_ring`, and under the hood it's calling FalkorDB's built-in
> `algo.WCC` — Weakly Connected Components — over the identity-resolution
> graph. Not a Python loop joining tables. A graph-native algorithm."

Point at the result: a 9-account component. Then:

> "But component size alone is a weak signal — a loosely-connected group of
> 9 strangers isn't a ring. So RingTrace computes a **composite ring
> score**: shared-device density, shared-IP density, reciprocal transfers,
> broker concentration, PageRank concentration, transaction velocity — nine
> independent graph signals, each one its own auditable Cypher query. For
> this account: ring score 0.43, confidence 0.89 — nearly every signal type
> fired."

## 4. Ring leader — PageRank, not a heuristic (30s)

> "Now: who's running it? `rank_ring_leaders` calls FalkorDB's
> `algo.pageRank` over the directed money-flow graph. The account that
> *accumulates* money from the rest of the ring rises to the top — zero
> hand-tuned rules."

Point at the result: **A1001**, PageRank score shown.

## 5. The money trail (30s)

> "`trace_money_path` finds the exact route: a 5-hop chain,
> A1027 → A1023 → A1024 → A1025 → A1026 → A1001, with timestamps and
> amounts on every hop. Then A1001 cashes out through a crypto mixer broker
> — and spends part of it at a real merchant. That whole narrative —
> Account → Account → ... → Broker → Account (self) → Merchant — only
> exists because the graph has Merchant/TO_MERCHANT edges, not just
> abstract transfers."

Open **C. Graph View**: the red path is the traced money flow.

## 6. Identity links — why these accounts are connected (20s)

> "`find_identity_links` confirms this isn't coincidence: 7 of these
> accounts share one physical device, 3 share an IP. That's why WCC
> grouped them — not an arbitrary graph artifact."

## 7. Risk score + the guardrail (30s)

Open **D. Risk**:

> "The ML risk scorer reads these graph features and predicts 0.98 —
> CRITICAL. But notice the panel shows BOTH the raw model score and a
> graph-adjusted score. RingTrace never lets a model's number stand alone —
> a guardrail checks the graph evidence itself and will CAP the score if the
> graph doesn't actually corroborate it. Here it doesn't need to: the
> evidence is real."

## 8. The decision — and WHY (40s) ← the centerpiece

Open the **🔍 Why This Action?** tab (first tab):

> "This is the panel that matters most to a judge. Six boxes, one causal
> chain: GRAPH FACTS → TOOL CALLS → EVIDENCE → RISK → DECISION → ACTION.
> Every number in the GRAPH FACTS box is a live Cypher/algo result. Remove
> FalkorDB, and there is no ring score, no leader, no money path — there is
> no decision. That's the banner at the top: **'Without FalkorDB, this
> decision could not have been made.'** It's not a slogan — it's literally
> true of this architecture."

## 9. The action — graph write-back (30s)

Go to **F. Decision**, click **Execute recommended action**:

> "RingTrace doesn't just print a verdict — it acts. Watch: a `Case` node
> gets created, linked to the account via `HAS_CASE`. The account gets
> flagged, marked high-risk, sent to manual review, and the case escalated.
> And — this is the part most agent demos skip — every one of those actions
> is linked back to the exact graph finding that triggered it:
> `(Case)-[:RESULTED_IN]->(Action)-[:TRIGGERED_BY]->(GraphFinding)`. You can
> literally query 'why did this action happen' and get a graph answer, not
> a log line."

(Optional, if a judge wants to see it in the raw graph — see README
"Sample Cypher queries":)

```cypher
MATCH (c:Case)-[:RESULTED_IN]->(ac:Action)-[:TRIGGERED_BY]->(gf:GraphFinding)
WHERE c.account_id = 'A1027'
RETURN ac.action_type, gf.summary
```

## 10. Contrast — the same logic, different graph (30s)

> "One more thing, and this is the test we built the whole decision engine
> against: run the IDENTICAL rule logic against a different account with a
> different graph neighborhood, and the verdict changes."

Switch the preset to **Case A — A1100** (isolated) and **Case B — A1200**
(shared IP, no money) and re-run. Point at: LOW / `NO_ACTION_REQUIRED` for
A1100, HIGH / `FLAG_AND_REQUEST_MANUAL_REVIEW` for A1200.

> "Same code path. Three different graphs. Three genuinely different
> verdicts — asserted directly in `tests/test_decision.py`."

## 11. Close (10s)

> "FalkorDB is not a visualization layer in RingTrace. It is the live
> context layer the agent queries to investigate relationships, select
> investigative tools, form evidence-backed conclusions, and trigger
> actions. Follow the graph. Trace the money. Expose the ring."

---

## If you have extra time: the DEMO-02 / DEMO-05 "don't cry wolf" cases

Run `A1310` (two accounts sharing a device, zero money movement — a
household, not a ring) and `A1340` (two strangers who happen to shop at the
same online retailer). Both correctly land on **LOW** — proof the composite
ring score and the ML guardrail don't flag every coincidental signal as
fraud. A detector that flags everything is as useless as one that flags
nothing; this demonstrates calibration, not just sensitivity.
