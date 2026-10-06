# Live model replay over the seeded alerts — 2026-10-05

**Synthetic data. One model. Counts over the seeded alerts; none of this is accuracy on real cases.**

- Code: commit `e2021d8` + uncommitted changes; prompt version `v2.2`; corpus read from the environment below; environment: `FIU_COPILOT_CR2`; role: `FIU_APP_ROLE_CR2`.
- Model requested: `llama3.3-70b`; model(s) that answered: `llama3.3-70b`. Decoding: temperature 0, structured outputs off. Nothing was recorded to the ledger.

## Result

- Assessments valid (all 11 factors parsed): **4 of 4**.
- Factors the model called *triggered*: **26**, of which the record supports **26** (grounded).
- Drafts written: **0**; passing the hard evidence gate first time: **0**; drafts containing at least one unsupported fact: **0** (0 facts in total); drafts with unverified assertions listed for the officer: **0**.
- Seconds: assessment median 92.4, max 95.7; draft plus quality check median None, max None.

## Recommendation beside the scenario author's label

| Label (author) | Recommendation | Alerts |
|---|---|---|
| CONTESTED | REVIEW | 1 |
| FILE | FILE | 2 |
| NOT_FILE | FILE | 1 |

FILE / NOT_FILE labels are the author's expectation; CONTESTED means the scenario has no pre-determined answer. REVIEW and INSUFFICIENT_EVIDENCE are the application declining to recommend, which is not an error.

## Per alert

| Alert | Label | Recommendation | Triggered | Grounded | Draft | Hard gate | Unsupported facts | Model | Assessment s |
|---|---|---|---|---|---|---|---|---|---|
| ALERT-01 | FILE | FILE | 7 | 7 | — | — | — | llama3.3-70b | 95.7 |
| ALERT-16 | NOT_FILE | FILE | 5 | 5 | — | — | — | llama3.3-70b | 79.6 |
| ALERT-03 | CONTESTED | REVIEW | 5 | 5 | — | — | — | llama3.3-70b | 92.4 |
| ALERT-12 | FILE | FILE | 9 | 9 | — | — | — | llama3.3-70b | 88.8 |

## How to read this

- The assessment and the draft come from the live model; every check after them is deterministic and runs against the record in the environment.
- A draft that fails the hard gate is the gate working: the officer would be told which fact is unsupported before anything is recorded.
- The same author wrote the alerts, the labels and the validator. The fabrication benchmark (`evidence/fabrication-benchmark/`) is where the gate's own catch rate is measured.
