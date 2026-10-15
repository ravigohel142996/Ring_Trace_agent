# Organizer Inquiry Draft — Existing-Project Eligibility

**Status: DRAFT — not sent. Requires team review and deliberate decision.**

---

Subject: Existing-project eligibility clarification — RingTrace (WeMakeDevs × FalkorDB Graph Hacks, Track 01)

Dear WeMakeDevs × FalkorDB Graph Hacks organizers,

Our team is preparing a submission for **Track 01: Agents That Act on Connected
Data**. We would like to clarify an eligibility question before submitting.

**Background:**

Our repository contains a pre-existing RingTrace fraud-ring investigation
project that predates the hackathon. The pre-event implementation includes an
account-investigation agent, ring-detection queries, a trained risk model,
action tools, a FastAPI/React interface, and a Docker deployment — all built
around FalkorDB as the live graph context layer.

For the event, we have built a **separate, materially distinct** contribution:
a Time-Respecting Payment-Corridor Investigator under `eventday/` with its own
graph model, its own disabled-by-default FalkorDB connection, its own
synthetic-only schema, a strictly time-ordered Cypher traversal, conditional
graph algorithms (PageRank/WCC), and a separate authenticated/confirmed
simulated write-back. This event-day code lives in its own package, has its
own tests, and its own UI page.

**Question:**

The supplied rules excerpt asks whether existing projects may continue but
omits its answer. May we submit this repository as a Track 01 entry, provided
we:

1. Clearly separate the pre-event baseline from the event-day contribution in
   our README, demo, and submission materials.
2. Represent only the event-day code as work produced during the hackathon.
3. Disclose AI coding assistance and team review/contribution as required.
4. Preserve the original repository history without relabelling pre-event
   commits as event-day work.

If existing projects are not eligible, or if additional disclosure or
publication requirements apply, we would appreciate written guidance before
submitting.

**Additional questions:**

- Must the repository be public at submission time, or is a private review
  link acceptable?
- Is a demo video required, and if so, what are the format and length limits?
- Are there specific FalkorDB feature or version requirements beyond "uses
  FalkorDB as the primary connected-data source"?
- Must the team demonstrate a live deployment, or is a recorded walkthrough
  sufficient?

Thank you for your time.

Sincerely,
[Team name and participants]

---

**Do not send this inquiry without the team's deliberate review and approval.**
