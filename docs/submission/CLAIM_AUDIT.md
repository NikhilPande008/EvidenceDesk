# Claim audit: EvidenceDesk submission package

**CLAIM AUDIT, 2026-10-06, repository as of this date.** (The history was later squashed into one commit, so commit ids inside the evidence records no longer resolve.) Synthetic data throughout. Every label means what it says:
**PROVEN** = reproduced in the current environment from a clean state, evidence path named. **STUBBED** = implemented, not verified end to end or only in a non-representative state, and said so
wherever it is mentioned. **ASSUMED** = believed, not checked, and labelled where it appears.

```
PROVEN: 17 | STUBBED: 8 | ASSUMED: 4 | DELETED (never claimed): 7
Blocking (must fix before ship): none open. Three wording defects were found and fixed during this audit (listed at the end).
Non-blocking: the 8 STUBBED items must be framed as "what is next", not "what it does".
Verdict: SHIP, with the labels below carried into the writeup, the README and the demo.
```

## PROVEN

| # | Claim | Evidence (and how it was reproduced) |
|---|---|---|
| P1 | The offline suite passes: 603 passed, 20 skipped (the 20 are live tests needing credentials) | A clean copy of the repository's files as they stand, fresh virtualenv, `pip install -r requirements.txt`, `python -m pytest tests -q`, 2026-10-06, on Python 3.11 and on Python 3.14. A 3.12-only f-string slipped past a 3.14 run once; `tests/test_python_311_syntax.py` now guards it |
| P2 | Every test file under `tests/` that can run on its own (50) exits 0 without credentials, and all code compiles on Python 3.11 | The same clean copy, `python tests/<name>.py` for each file with a `__main__` block. Two of the 50 are the live suites and skip without credentials |
| P3 | The evidence gate wrongly blocked 0 of 70 faithful narratives for ALERT-01 and 0 of 69 for the other 14 alerts with real rows | `evidence/fabrication-benchmark/2026-10-06/` (offline, re-run today). The author wrote both validator and narratives |
| P4 | On a set written before round 2 and never tuned on, the gate caught 30 of 38 fabricated narratives (78.9%, 95% interval 63.6 to 88.9) | Same folder; 27 of 38 before the last fixes in `.../2026-10-05/baseline_before_round2.json`. The in-distribution 154 of 154 is not quoted |
| P5 | Mis-attribution check, first measurement on a fresh set: 14 of 20 (70.0%); 12 of 20 on today's code after two post-hoc changes | `.../2026-10-05/attribution_q_first_measurement.json` and today's run |
| P6 | A planted sentence with an amount, date, channel and place the record does not hold is named fact by fact and blocks the filing, with no override | Tests (`tests/test_grounding.py`, `tests/test_hostile_evidence.py`) and `docs/screenshots/04-evidence-gate-blocks-fabricated-facts.jpg` (5 Oct, running app) |
| P7 | The application role holds INSERT and SELECT only on the ledger; UPDATE and DELETE are denied; the answer key is unreadable to it | Live RBAC proof `deploy/04_verify_ledger_rbac.sql`, health report and live suites, 2026-10-06 (`evidence/cleanroom-2026-10-06/live_suites.log`) |
| P8 | The hosted app's code is byte-identical to the source (30 of 30 files) after the 6 October redeploy | Health report in the same log |
| P9 | Regulatory lookup on 98 queries: calibration 22 of 22 off-scope refused; a holdout written after the foreign-regime screen and measured once: 11 of 12 refused, 8 of 8 answerable answered (one miss: Cayman Islands) | `evidence/retrieval-gold/2026-10-06/` and `.../2026-10-05/holdout3_first_measurement/` |
| P10 | The real model over all 19 alerts (two runs combined): 19 of 19 assessments valid, 19 of 19 drafts passed the hard gate (18 first time), 0 unsupported facts, median assessment 78 s | `evidence/live-replay/2026-10-06/COMBINED.md` |
| P11 | Of three models, only `llama3.3-70b` separated the author's FILE and NOT_FILE groups; `claude-sonnet-4-5` recommended FILE on all 16 alerts | `evidence/live-replay/MODEL_COMPARISON_2026-10-06.md` (one run each) |
| P12 | A model as the only checker wrongly flagged 15 of 40 (`claude-sonnet-4-5`) and 39 of 40 (`llama3.3-70b`) faithful narratives; the validator flagged 0 of 40. The models caught more fabrications (80 and 76 of 80, against 65) | `evidence/llm-checker/2026-10-06/COMPARISON.md` |
| P13 | A negative result, reproduced: on the held-out Gulf-remittance alerts the model recommended FILE for both legitimate ones (ALERT-18, ALERT-19) | `evidence/heldout-gcc/2026-10-06/` and the retry run |
| P14 | A ledger row's SHA-256 recomputed in Python matches the hash the database stored, for 3 of 3 real rows | `evidence/cleanroom-2026-10-02/ledger-rows-for-offline-hash-check.json`, `tests/test_dossier.py` |
| P15 | Opt-in masking: the owner role read masked values and the application role clear text, then the policies were removed | `evidence/governance/2026-10-06/` (isolated environment only) |
| P16 | The feed loader validates and refuses offline (dry run), and its write path ran live inside a rolled-back transaction | `evidence/feed-load/2026-10-06/live_transaction_proof.txt`, `tests/test_feed_contract.py` |
| P17 | The shipped saved responses are real model replies, matched to a case by the exact prompt hash, labelled as saved on screen and in the ledger row | `tests/test_saved_responses.py` (11 tests), `skills/saved_responses_data.py` (56 replies, 2026-10-06) |

## STUBBED (say so wherever mentioned)

| # | Claim | State |
|---|---|---|
| S1 | Concurrent decisions on one alert are detected | The detector and the recorded `decision_sequence` are unit-tested. No live concurrent write was run. Prevention is not possible on this account and is not claimed |
| S2 | An inspection pack verifies offline | Packs are built and verified in the test harness. A pack downloaded from the hosted app has not been verified |
| S3 | An institution's alert feed loads | Only the synthetic canonical sample and a monitoring-export-shaped sample were used. No real feed |
| S4 | Cortex Code CLI skill files in `.cortex/skills/` | Present, in the documented format, kept consistent with the scripts by a test. No CLI session has loaded them; `evidence/coco/README.md` says so |
| S5 | Time on the desk is measured as a proxy | Implemented and tested. No officer session has produced a measurement and no baseline exists |
| S6 | The audit export is a deletion witness | Not provisioned in the live environment (health: UNVERIFIED); the local write-once sink is a simulation |
| S7 | What Snowsight renders | Never observed. Screenshots are from the app running locally against the same environment |
| S8 | The queue's live deadlines | Seeded as working-day offsets from the load moment, so they look live whenever the seed runs; they are not a real feed |

## ASSUMED (labelled as such where each appears)

| # | Claim | Why it is only assumed |
|---|---|---|
| A1 | The product fits a Principal Officer and operations team in an Indian bank or a GCC | The README says "our assumption; a pilot would confirm it". No practitioner has reviewed it |
| A2 | The corpus is legally accurate | 0 of 49 rules independently verified. PROVEN means a primary source is cited by the corpus author |
| A3 | Descriptions of the filing portal and the FIU-IND report structure | From the corpus, author-asserted, not checked against the live regulator documents |
| A4 | The three Gulf-remittance alerts and the prediction about them were written after the nexus rule was frozen and before the first model run on them | The author's statement, the header of `PREDICTION.md`, and a hash guard that shows the rule has not changed since. The commit order that once showed it was lost when the history was squashed, so the order can no longer be checked from git |

## Never claimed (deleted or refused)

Time saved or volumes at any institution. Accuracy on real cases. Production readiness. Use of the Cortex Code CLI. That the ledger is immutable (it is append-only for the application role; the owner role can
delete rows). That any model recommendation is correct (3 of 5 NOT_FILE-labelled alerts still get FILE). A Cortex Agent (none is used).

## Fabrication-vector walk

1. **Frozen or stale feeds.** Not applicable: no live feed. Seeds are fixed synthetic rows; only the deadline offsets move (S8).
2. **Cached or hardcoded outputs.** The saved responses are real captured replies, shipped on purpose, labelled on screen and in provenance, and replayed only on an exact prompt match (P17). Every benchmark figure is recomputed by a command in the repository; the live figures point at their raw files.
3. **Non-isolated states.** The masking probe isolates by role (P15). The held-out replays use the same code and data as the main run; the run-to-run variation of the model at temperature 0 is documented (`MODEL_COMPARISON_2026-10-06.md`).
4. **Invented third-party descriptions.** Every statement about a Snowflake product was scanned. Corrected: an earlier claim of a "Cortex Agent" (none is used). Behaviours described from live use: Cortex Search service, `COMPLETE` options and structured outputs, the Analyst REST endpoint, masking policies on this account's edition, hybrid tables unavailable on this account. Cortex Code CLI skill locations and file format are from Snowflake's own extensibility documentation.
5. **Hand-drawn or unsourced data.** All alerts, transactions and labels are author-written synthetic data (stated on the first screen and in the README). Corpus rules carry a cited source with `url_verified: false`; that is why the corpus is A2.
6. **Survivor framing.** The held-out miss, the cost of the record check (it moved a FILE-labelled alert, ALERT-04, to REVIEW), the 3-of-5 NOT_FILE result, the model-checker's higher recall, the unrun full live suites after one test correction, and the absence of any CLI session are all in the README or the evidence notes.

Design-intent check: the gate's refusal to record on an unsupported fact, the required reason for a repeat decision, and the discounting of unsupported nexus factors are deliberate (each has a test and a comment in the code that says why), not defects.

## Fixed during this audit

1. `SKILL.md` said the decision id is a ULID; the code writes a UUID.
2. `SKILL.md` and `tests/corpus_retrieval_tests.sql` said the ledger's "immutability" is tested; it is append-only for the application role.
3. `SKILL.md` said the skills "are not Cortex Code CLI skill files" and listed "CoCo phase evidence" without saying no CLI session is recorded; it now points to `.cortex/skills/` and `evidence/coco/README.md` and says the table is a map of artifacts, not a record of sessions.
