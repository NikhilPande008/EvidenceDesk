# Pitch defense: the questions a judge will ask

Each answer is short enough to say in one breath and traces to evidence (`CLAIM_AUDIT.md` labels in brackets). A question marked **OPEN** has no honest short answer yet and is a work item, not something to hope the judge does not ask.

## "Why not the simpler thing?"

| Question | Answer |
|---|---|
| Why not just RAG, or a good system prompt? | We do use retrieval (Cortex Search). The point is what runs after the model: checks on the case record decide what may be filed, so a better prompt cannot make a fabricated amount fileable. [P3 to P6] |
| Why not ask a second model to check the narrative? | We measured it. A strong model caught more fabrications (80 of 80 against our 65) and also wrongly flagged 15 of 40 true narratives; the validator flagged none. A gate that cries wolf gets switched off. [P12] |
| Why this model? | We compared three on the same 16 alerts. Only `llama3.3-70b` gave different recommendations for the author's FILE and NOT_FILE groups; `claude-sonnet-4-5` said FILE on all 16. One run each, so indicative. [P11] |
| Why Snowflake? | The data, the role-based access, the retrieval, the model call and the row hash all sit in one governed place, and the application role provably cannot update or delete a decision. [P7] |

## "What is your weakest number?"

| Question | Answer |
|---|---|
| What is the weakest number in the deck? | 30 of 38, 78.9% (interval 63.6 to 88.9), for unseen fabrication phrasings. We lead with it, not with the 154 of 154 the author's own validator gets on the author's own narratives. [P4] |
| And the one you hide? | We do not hide it: on two legitimate Gulf-remittance alerts the model still recommended FILE. We predicted the weakness before running them and did not change our rule afterwards. [P13] |
| How accurate is it? | We do not claim accuracy. Everything is synthetic, written by us, and counted over those cases. The README says so first. |
| Your faithful-narrative result is 0 of 139. | Written by the same author as the validator. It shows the validator does not object to what it was built to accept, not that it generalises. We say that in the benchmark summary. [P3] |
| The record check moved a FILE-labelled alert to REVIEW. | Yes, ALERT-04. A rule that can only discount will sometimes discount a case the author would file. It does not remove the alert, the factors or the record from the officer. [P10] |

## "What breaks at 10x?"

| Question | Answer |
|---|---|
| What breaks first? | Model latency and timeouts. The median assessment is 78 s and a full replay lost three alerts to 120-second statement timeouts, so the application fails closed and offers a saved reply. We have not load-tested anything. [P10] |
| Then the queue? | It reads all transactions on each load; the readiness page says so and describes precomputing aggregates at ingest. Not built, not measured. |
| Two officers decide the same alert at once. | Both rows are kept and the reconciliation reports `CONCURRENT_DECISIONS`. We cannot prevent it on this account, and no live race was run. [S1] |

## "What did you not build?"

A Cortex Agent, microservices and a case-ingestion UI: the decision is the product, and an agent would add autonomy the officer should not delegate. Row-level access: it needs an entitlement source we do not have, and inventing one would be decoration.
A jurisdiction-risk list: we cannot verify the current FATF lists from here, so a hard-coded one would be an unverified claim. Each is a choice with a reason, written down.

## Trust and regulation

| Question | Answer |
|---|---|
| Is the regulatory corpus right? | Not independently verified: 0 of 49. PROVEN means a source is cited by the corpus author. We found and corrected a real error ourselves (a section cited as the tipping-off provision is "Access to information"). [A2] |
| Is the ledger tamper-proof? | No. It is append-only for the application role and each row carries a SHA-256 hash that exposes edits. The owner role can delete rows, and deletion is only detectable with an audit export that is not provisioned live. [P7, S6] |
| What does the model see? | The customer profile and counterparties, verbatim, inside Snowflake. Opt-in masking protects the columns from other roles; it does not change prompts. Pseudonymised prompts are a production prerequisite, not built. |
| Did you use AI to build this? | Yes, an AI coding assistant (Claude Code). The README says so. |

## Fit and adoption

| Question | Answer |
|---|---|
| Who pays, and what does it replace? | A compliance head at an Indian bank or a GCC that works its alerts; it replaces reasoning kept in email and spreadsheets. That is our assumption and no practitioner has confirmed it. [A1] **OPEN** |
| Why not a feature of the case-management system? | An incumbent could add narrative grounding. What is harder to copy quickly is re-deriving the gate and the regulatory basis at write time and storing what the officer saw and acknowledged. We have not tested this against an incumbent. [A1] |
| What would a pilot measure? | `docs/PILOT_PROTOCOL.md`: time on the desk against a recorded baseline, decision-record completeness, and what an inspector asks for. No baseline exists today. |

## Open items (work, not hope)

1. **Cortex Code CLI.** *"Where did you use it?"* The honest answer today is "we wrote five skill files and have not recorded a session". Run the sessions in `evidence/coco/README.md`. **OPEN**
2. **Build window.** The first commit is 2026-10-04 00:12 IST. If the rules limit pre-existing work or set a build window, check them and be ready to say what existed before. **OPEN**
3. **A buyer or a practitioner.** One named practitioner reading the corpus rules and the workflow would turn two ASSUMED claims into evidence. **OPEN**
4. **Scale.** No load number exists; do not offer one.
