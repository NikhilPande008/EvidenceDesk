# Deck copy, corrected against the claim audit

The deck in the hackathon template (6 slides, dated 4 October) predates most of the work and has four statements that the audit does not support. This file gives replacement text for each slide, to paste into the deck.
Slides 2 and 6 need no change. The deck is a Keynote file that this repository does not hold; nothing here edits it.

## What must change, and why

| Slide | Current text | Problem | Replace with |
|---|---|---|---|
| 3 | "4 documented counterparties", "No documented counterparties", "Outcome: FILE" and "Outcome: CLOSE" | "Documented" states a conclusion that the data no longer carries, and "Outcome" reads as something the system found. They are the author's labels | Slide 3 text below |
| 4 | "CoCo CLI capabilities: regulatory lookup, AI suspicion assessment, evidence grounding and decision gate" | Those are Cortex Search, Cortex Complete and deterministic Python, not Cortex Code CLI capabilities. In a CoCo CLI hackathon this reads as CLI use that was not recorded | Slide 4 text below |
| 5 | "459 offline tests" | The suite is 603 passed, 20 skipped | Slide 5 text below |
| 5 | "14 fabrication classes blocked by the hard gate" | The benchmark has 9 claim classes, and no source for 14 | Slide 5 text below |

## Slide 3: Same signal, different evidence

**ALERT-01 and ALERT-16 both trigger the same mule-pass-through signal for ₹3.45 lakh.**

| Shared | ALERT-01 | ALERT-16 |
|---|---|---|
| MULE_PASSTHROUGH · I4C signal source · ₹3.45 lakh | 98.8% of credits sent onward · one flagged counterparty · unknown senders · author's label: FILE | 87.0% sent onward to a named hospital · no flagged counterparty · three KYC-linked family senders · author's label: NOT_FILE |

The detector finds a suspicious shape. The record decides whether a decision can be defended. The labels are the author's expectation on synthetic data; the officer decides.

## Slide 4: Architecture

Flow: Synthetic alerts and transactions → Governed regulatory corpus → Cortex Search and Cortex Complete → Grounding and decision gate → Principal Officer workspace → Append-only ledger and reconstruction.

**Snowflake capabilities used:** Streamlit in Snowflake, Cortex Search, Cortex Complete, Cortex Analyst, roles and grants.
**Cortex Code CLI:** five skill files in the repository describe how to verify, reconcile, load, deploy and measure. No CLI session is recorded.
Structured inputs: alerts, transactions, corpus. Text inputs: the officer's rationale and the case narrative. Cortex Agents are not used.

## Slide 5: What is measured

*The prototype does not claim time savings or production accuracy. Everything below is on synthetic data the author wrote.*

- 603 offline tests pass on a fresh clone; the live suites ran against the isolated environment on 6 October
- Evidence gate: 0 of 139 faithful narratives wrongly blocked; 30 of 38 unseen fabricated phrasings caught
- The application role can insert into and read the ledger and nothing more (proven live)
- Real model over 19 alerts: every draft passed the hard gate with no unsupported fact, **and on two legitimate Gulf-remittance alerts the model still recommended FILE** (a held-out result we report, not hide)

Scalable path: a governed corpus, Snowflake-native controls and a stored rationale support later reconstruction without giving the model authority to file.

## Speaker notes to carry with slide 5

If asked for accuracy: "We do not claim it. We measured the pieces we could on data we wrote, and we published where it is wrong." If asked about the Cortex Code CLI: "The repository has CLI skill files; we have not recorded a CLI session, so we do not claim one."
