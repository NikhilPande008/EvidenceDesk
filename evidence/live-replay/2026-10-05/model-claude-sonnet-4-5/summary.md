# Live model replay over the seeded alerts — 2026-10-05

**Synthetic data. One model. Counts over the seeded alerts; none of this is accuracy on real cases.**

- Code: commit `f05eeeb` + uncommitted changes; prompt version `v2.2`; corpus read from the environment below; environment: `FIU_COPILOT_CR2`; role: `FIU_APP_ROLE_CR2`.
- Model requested: `claude-sonnet-4-5` (no fallback model allowed); model(s) that answered: `claude-sonnet-4-5`. Decoding: temperature 0, structured outputs on. Nothing was recorded to the ledger.

## Result

- Assessments valid (all 11 factors parsed): **16 of 16**.
- Factors the model called *triggered*: **132**, of which the record supports **129** (grounded).
- Drafts written: **0**; passing the hard evidence gate: **0** (first draft: **0**; one-shot repair tried on **0**, passed on **0**); drafts containing at least one unsupported fact: **0** (0 facts in total); drafts with unverified assertions listed for the officer: **0**.
- Seconds: assessment median 29.6, max 34.1; draft plus quality check median None, max None.

## Recommendation beside the scenario author's label

| Label (author) | Recommendation | Alerts |
|---|---|---|
| CONTESTED | FILE | 4 |
| FILE | FILE | 9 |
| NOT_FILE | FILE | 3 |

FILE / NOT_FILE labels are the author's expectation; CONTESTED means the scenario has no pre-determined answer. REVIEW and INSUFFICIENT_EVIDENCE are the application declining to recommend, which is not an error.

## Per alert

| Alert | Label | Recommendation | Triggered | Grounded | Draft | Hard gate | Unsupported facts | Model | Assessment s |
|---|---|---|---|---|---|---|---|---|---|
| ALERT-01 | FILE | FILE | 9 | 9 | — | — | — | claude-sonnet-4-5 | 31.3 |
| ALERT-02 | FILE | FILE | 9 | 9 | — | — | — | claude-sonnet-4-5 | 29.7 |
| ALERT-03 | CONTESTED | FILE | 8 | 8 | — | — | — | claude-sonnet-4-5 | 30.5 |
| ALERT-04 | FILE | FILE | 9 | 9 | — | — | — | claude-sonnet-4-5 | 29.7 |
| ALERT-05 | FILE | FILE | 5 | 5 | — | — | — | claude-sonnet-4-5 | 26.2 |
| ALERT-06 | FILE | FILE | 10 | 10 | — | — | — | claude-sonnet-4-5 | 29.6 |
| ALERT-07 | NOT_FILE | FILE | 5 | 4 | — | — | — | claude-sonnet-4-5 | 27.8 |
| ALERT-08 | NOT_FILE | FILE | 6 | 6 | — | — | — | claude-sonnet-4-5 | 26.9 |
| ALERT-09 | FILE | FILE | 10 | 10 | — | — | — | claude-sonnet-4-5 | 28.7 |
| ALERT-10 | FILE | FILE | 10 | 10 | — | — | — | claude-sonnet-4-5 | 30.6 |
| ALERT-11 | CONTESTED | FILE | 9 | 9 | — | — | — | claude-sonnet-4-5 | 30.9 |
| ALERT-12 | FILE | FILE | 10 | 10 | — | — | — | claude-sonnet-4-5 | 26.5 |
| ALERT-13 | CONTESTED | FILE | 9 | 8 | — | — | — | claude-sonnet-4-5 | 27.5 |
| ALERT-14 | CONTESTED | FILE | 8 | 8 | — | — | — | claude-sonnet-4-5 | 28.0 |
| ALERT-15 | FILE | FILE | 7 | 6 | — | — | — | claude-sonnet-4-5 | 34.1 |
| ALERT-16 | NOT_FILE | FILE | 8 | 8 | — | — | — | claude-sonnet-4-5 | 28.2 |

## How to read this

- The assessment and the draft come from the live model; every check after them is deterministic and runs against the record in the environment.
- A draft that fails the hard gate is the gate working: the officer would be told which fact is unsupported before anything is recorded.
- The same author wrote the alerts, the labels and the validator. The fabrication benchmark (`evidence/fabrication-benchmark/`) is where the gate's own catch rate is measured.
