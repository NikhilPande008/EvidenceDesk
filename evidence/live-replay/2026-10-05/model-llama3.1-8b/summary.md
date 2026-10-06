# Live model replay over the seeded alerts — 2026-10-05

**Synthetic data. One model. Counts over the seeded alerts; none of this is accuracy on real cases.**

- Code: commit `f05eeeb` + uncommitted changes; prompt version `v2.2`; corpus read from the environment below; environment: `FIU_COPILOT_CR2`; role: `FIU_APP_ROLE_CR2`.
- Model requested: `llama3.1-8b` (no fallback model allowed); model(s) that answered: `llama3.1-8b`. Decoding: temperature 0, structured outputs on. Nothing was recorded to the ledger.

## Result

- Assessments valid (all 11 factors parsed): **16 of 16**.
- Factors the model called *triggered*: **83**, of which the record supports **75** (grounded).
- Drafts written: **0**; passing the hard evidence gate: **0** (first draft: **0**; one-shot repair tried on **0**, passed on **0**); drafts containing at least one unsupported fact: **0** (0 facts in total); drafts with unverified assertions listed for the officer: **0**.
- Seconds: assessment median 24.6, max 33.9; draft plus quality check median None, max None.

## Recommendation beside the scenario author's label

| Label (author) | Recommendation | Alerts |
|---|---|---|
| CONTESTED | FILE | 2 |
| CONTESTED | REVIEW | 2 |
| FILE | FILE | 7 |
| FILE | REVIEW | 2 |
| NOT_FILE | REVIEW | 3 |

FILE / NOT_FILE labels are the author's expectation; CONTESTED means the scenario has no pre-determined answer. REVIEW and INSUFFICIENT_EVIDENCE are the application declining to recommend, which is not an error.

## Per alert

| Alert | Label | Recommendation | Triggered | Grounded | Draft | Hard gate | Unsupported facts | Model | Assessment s |
|---|---|---|---|---|---|---|---|---|---|
| ALERT-01 | FILE | FILE | 5 | 5 | — | — | — | llama3.1-8b | 17.8 |
| ALERT-02 | FILE | FILE | 6 | 6 | — | — | — | llama3.1-8b | 18.1 |
| ALERT-03 | CONTESTED | REVIEW | 5 | 5 | — | — | — | llama3.1-8b | 28.5 |
| ALERT-04 | FILE | FILE | 8 | 6 | — | — | — | llama3.1-8b | 33.7 |
| ALERT-05 | FILE | FILE | 4 | 4 | — | — | — | llama3.1-8b | 24.1 |
| ALERT-06 | FILE | FILE | 4 | 4 | — | — | — | llama3.1-8b | 33.9 |
| ALERT-07 | NOT_FILE | REVIEW | 4 | 3 | — | — | — | llama3.1-8b | 19.1 |
| ALERT-08 | NOT_FILE | REVIEW | 2 | 2 | — | — | — | llama3.1-8b | 19.4 |
| ALERT-09 | FILE | FILE | 8 | 8 | — | — | — | llama3.1-8b | 26.7 |
| ALERT-10 | FILE | REVIEW | 7 | 4 | — | — | — | llama3.1-8b | 19.7 |
| ALERT-11 | CONTESTED | FILE | 6 | 6 | — | — | — | llama3.1-8b | 24.4 |
| ALERT-12 | FILE | FILE | 6 | 6 | — | — | — | llama3.1-8b | 29.0 |
| ALERT-13 | CONTESTED | REVIEW | 3 | 1 | — | — | — | llama3.1-8b | 24.6 |
| ALERT-14 | CONTESTED | FILE | 10 | 10 | — | — | — | llama3.1-8b | 28.0 |
| ALERT-15 | FILE | REVIEW | 2 | 2 | — | — | — | llama3.1-8b | 22.1 |
| ALERT-16 | NOT_FILE | REVIEW | 3 | 3 | — | — | — | llama3.1-8b | 27.4 |

## How to read this

- The assessment and the draft come from the live model; every check after them is deterministic and runs against the record in the environment.
- A draft that fails the hard gate is the gate working: the officer would be told which fact is unsupported before anything is recorded.
- The same author wrote the alerts, the labels and the validator. The fabrication benchmark (`evidence/fabrication-benchmark/`) is where the gate's own catch rate is measured.
