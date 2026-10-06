# EvidenceDesk: submission writeup

Snowflake CoCo CLI Hackathon (GCC Edition), track Risk, Fraud and Regulatory Intelligence Copilot. Team of one. **All data is synthetic. This is a prototype, not a production financial-crime system.**
Every claim below carries the label from [`CLAIM_AUDIT.md`](CLAIM_AUDIT.md): PROVEN, STUBBED or ASSUMED. Claims that are not PROVEN say so where they appear.

## One line

A detector firing is not a decision. EvidenceDesk is the workspace where a Principal Officer decides what happens to an AML alert and can later show why: the facts first, the rule behind them,
an optional labelled AI proposal, checks that run on the record and not on the model, and a decision record that can be reconstructed.

## The problem

When an alert fires, someone has to decide whether to report it to FIU-IND within seven working days, and later show an inspector why they did or did not. The reasoning usually lives in email, spreadsheets and
free-text case notes. *(ASSUMED: our description of current practice; a pilot would confirm it.)* A model that drafts a narrative adds a second risk: it can state an amount, a date or a place the record does not hold.

## Who it is for

The Principal Officer, and the financial-crime operations team that prepares each decision, in an Indian bank or in a global capability centre (GCC) that works its alerts. *(ASSUMED: fit not reviewed by a practitioner.)*
India only: PMLA, PML Rules, FIU-IND, RBI. A question about another regime is screened and usually declined, not guessed.

## What it does

1. **Queue.** Alerts ranked by nine published factors, with the seven-working-day clock where the feed supplies a suspicion time. The app never infers one.
2. **Investigation desk.** The source facts open first, the regulatory basis second, an optional AI assessment third, the human decision last. The demo pair: ALERT-01 and ALERT-16 carry the same detector signal and the
   same ₹3.45 lakh, but 98.8% of the credits go onward to a flagged counterparty in one and 87.0% go to a named hospital in the other.
3. **Evidence gate.** Every amount, date, transaction id, channel, place, entity and profile fact in a filing text is checked against the case record. An unsupported fact blocks the filing, is named, and has no
   override. Facts that are real but bound to the wrong party are flagged for the officer to acknowledge. *(PROVEN, P3 to P6.)*
4. **Decision gate.** 33 conditions, re-run at write time by the recorder, not trusted from the screen. A second decision on an alert needs a written reason.
5. **Ledger.** Append-only for the application role (INSERT and SELECT only, proven live), each row carrying provenance and a SHA-256 hash. *(PROVEN, P7, P14.)* It is **not immutable**: the owner role can delete rows.
6. **Reconstruction and inspection pack.** A decision can be rebuilt from the ledger and downloaded as a file that an offline verifier checks without Snowflake or the app. *(Verifier PROVEN on a test harness; STUBBED against a pack downloaded from the hosted app, S2.)*
7. **Regulatory lookup.** Cortex Search over 36 indexed rules (PROVEN and ASSUMED only), with a scope guard that declines out-of-perimeter and weakly related questions. *(PROVEN, P9.)*

## How it is built

- **Snowflake:** Streamlit in Snowflake for the workspace; Cortex Search for governed retrieval; `SNOWFLAKE.CORTEX.COMPLETE` (temperature 0, token caps, JSON-schema structured outputs) for the optional 11-factor assessment
  and draft; Cortex Analyst over a semantic model for the dashboard questions; roles and grants for least privilege; SQL-side hashing for the ledger. Cortex Agents are not used.
- **Deterministic layer:** pure Python modules for grounding, attribution, the decision gate, scoring, evidence quality and the record-backed nexus rule. No model, no database, no clock inside them.
- **Fail closed:** unparseable model output, a timed-out quality check or a missing fact blocks instead of passing.
- **Honest evidence:** every figure is a count with an interval where one applies, from a command in the repository. Sets used to build a fix are labelled regression records; the first measurement of anything is kept.
- **Cortex Code CLI:** five skill files in `.cortex/skills/` describe how to verify a pack, reconcile the ledger, dry-run a feed, deploy into an isolated environment and measure. They follow the documented format and a test keeps
  them consistent with the scripts. *(STUBBED, S4: no CLI session has been recorded, so none is claimed.)* The code was written with an AI coding assistant (Claude Code).

The hard part was not the model call. It was deciding what the application may say when the model is wrong, slow or unavailable, and proving that with tests that fail when the rule is removed.

## What we measured (synthetic data, author-written cases and labels, counts not field accuracy)

| | Result |
|---|---|
| Offline suite, fresh clone | 603 passed, 20 skipped (P1) |
| Faithful narratives wrongly blocked | 0 of 70 and 0 of 69 (P3) |
| Unseen fabrication phrasings caught | 30 of 38, 78.9% (P4). The in-distribution figure is not quoted |
| Real model over 19 alerts | 19 of 19 assessments valid; 19 of 19 drafts passed the gate; 0 unsupported facts; median 78 s per assessment (P10) |
| Three models | Only `llama3.3-70b` separated the author's FILE and NOT_FILE groups (P11) |
| A model as the only checker | Wrongly flagged 15 of 40 and 39 of 40 faithful narratives; the validator 0 of 40 (P12) |
| Regulatory scope guard | 22 of 22 off-scope refused on the calibration set; 11 of 12 on a holdout measured once (P9) |

## Challenges we ran into

- **"Grounded" is not "supported".** The first real replay showed the model triggering a beneficiary factor on the legitimate twin while citing real transaction ids. We added a record test that can only discount a factor, and
  it works on ALERT-16. It also moved a FILE-labelled alert (ALERT-04) to REVIEW. We kept both results.
- **We wrote three new alerts after freezing that rule, and it failed on them.** The model recommended FILE for two legitimate Gulf-remittance alerts. The cause is a missing jurisdiction list and a too-permissive cross-border clause.
  We recorded our prediction before the run, did not change the rule afterwards, and made a test fail if anyone does without saying so (P13).
- **A model as a checker looked better and was worse.** It caught more fabrications and wrongly objected to most true narratives. The gate stays deterministic.
- **Cortex statement timeouts.** A full replay lost three alerts and two drafts to 120-second timeouts. The application failed closed, as designed, and a retry completed the record. Both runs are kept.
- **Concurrency.** Two decisions on one alert at the same moment cannot be prevented on this account (no locking, no enforced uniqueness, hybrid tables unavailable). They are detected and reported. *(STUBBED, S1: no live race was run.)*

## What we learned

A check that runs on the record is worth more than a better prompt. Measuring the thing you built to fix a problem, on cases you wrote after you built it, is the only way to find out it does not generalise.

## What is next

A maintained jurisdiction-risk reference with an owner, and new held-out alerts to test a rule that uses it. A practitioner review of the corpus rules (0 of 49 independently verified). A pilot on a real alert feed
(`docs/DATA_CONTRACT.md`, `docs/PILOT_PROTOCOL.md`). Recorded Cortex Code CLI sessions. Prevention of concurrent decisions where the account supports it. Row-level access, which needs an entitlement source.

## Not claimed

Time saved, volumes, accuracy on real cases, production readiness, regulatory approval, immutability of the ledger, or any use of the Cortex Code CLI beyond the skill files.

## Built with

Snowflake · Streamlit in Snowflake · Cortex Search · Cortex Complete · Cortex Analyst · Snowflake roles and grants · Python · pytest · SQL

## Links

Repository: *(add the public URL)* · Demo video: *(add the link)* · Hosted app: *(add the Snowsight link or state that judges use the screenshots, the clean-room app being private to the account)*
