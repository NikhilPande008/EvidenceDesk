# Live model replay over the seeded alerts — 2026-10-05

**Synthetic data. One model. Counts over the seeded alerts; none of this is accuracy on real cases.**

- Code: commit `61e86a3` + uncommitted changes; prompt version `v2.1`; corpus read from the environment below; environment: `FIU_COPILOT_CR2`; role: `FIU_APP_ROLE_CR2`.
- Model(s) that answered: `llama3.1-8b`, `llama3.3-70b`. Nothing was recorded to the ledger.

## Result

- Assessments valid (all 11 factors parsed): **16 of 16**.
- Factors the model called *triggered*: **96**, of which the record supports **96** (grounded).
- Drafts written: **16**; passing the hard evidence gate first time: **15**; drafts containing at least one unsupported fact: **0** (0 facts in total); drafts with unverified assertions listed for the officer: **1**.
- Seconds: assessment median 79.6, max 148.2; draft plus quality check median 116.5, max 128.8.

## Recommendation beside the scenario author's label

| Label (author) | Recommendation | Alerts |
|---|---|---|
| CONTESTED | FILE | 3 |
| CONTESTED | REVIEW | 1 |
| FILE | FILE | 8 |
| FILE | NOT_FILE | 1 |
| NOT_FILE | FILE | 1 |
| NOT_FILE | REVIEW | 2 |

FILE / NOT_FILE labels are the author's expectation; CONTESTED means the scenario has no pre-determined answer. REVIEW and INSUFFICIENT_EVIDENCE are the application declining to recommend, which is not an error.

## Per alert

| Alert | Label | Recommendation | Triggered | Grounded | Draft | Hard gate | Unsupported facts |
|---|---|---|---|---|---|---|---|
| ALERT-01 | FILE | FILE | 7 | 7 | READY | pass | 0 |
| ALERT-02 | FILE | FILE | 7 | 7 | READY | pass | 0 |
| ALERT-03 | CONTESTED | REVIEW | 5 | 5 | NEEDS_REVISION | pass | 0 |
| ALERT-04 | FILE | FILE | 7 | 7 | READY | pass | 0 |
| ALERT-05 | FILE | FILE | 8 | 8 | READY | pass | 0 |
| ALERT-06 | FILE | FILE | 5 | 5 | REJECT | BLOCKED | 0 |
| ALERT-07 | NOT_FILE | REVIEW | 4 | 4 | NEEDS_REVISION | pass | 0 |
| ALERT-08 | NOT_FILE | REVIEW | 3 | 3 | READY | pass | 0 |
| ALERT-09 | FILE | FILE | 7 | 7 | READY | pass | 0 |
| ALERT-10 | FILE | FILE | 7 | 7 | READY | pass | 0 |
| ALERT-11 | CONTESTED | FILE | 7 | 7 | READY | pass | 0 |
| ALERT-12 | FILE | FILE | 9 | 9 | READY | pass | 0 |
| ALERT-13 | CONTESTED | FILE | 6 | 6 | NEEDS_REVISION | pass | 0 |
| ALERT-14 | CONTESTED | FILE | 8 | 8 | READY | pass | 0 |
| ALERT-15 | FILE | NOT_FILE | 0 | 0 | NEEDS_REVISION | pass | 0 |
| ALERT-16 | NOT_FILE | FILE | 6 | 6 | READY | pass | 0 |

## How to read this

- The assessment and the draft come from the live model; every check after them is deterministic and runs against the record in the environment.
- A draft that fails the hard gate is the gate working: the officer would be told which fact is unsupported before anything is recorded.
- The same author wrote the alerts, the labels and the validator. The fabrication benchmark (`evidence/fabrication-benchmark/`) is where the gate's own catch rate is measured.
