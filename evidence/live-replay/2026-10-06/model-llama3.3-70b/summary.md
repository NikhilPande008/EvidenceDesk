# Live model replay over the seeded alerts — 2026-10-06

**Synthetic data. One model. Counts over the seeded alerts; none of this is accuracy on real cases.**

- Code: commit `5075f1b` + uncommitted changes; prompt version `v2.2`; corpus read from the environment below; environment: `FIU_COPILOT_CR2`; role: `FIU_APP_ROLE_CR2`.
- Model requested: `llama3.3-70b` (no fallback model allowed); model(s) that answered: `llama3.3-70b`. Decoding: temperature 0, structured outputs on. Nothing was recorded to the ledger.

## Result

- Assessments valid (all 11 factors parsed): **16 of 16**.
- Factors the model called *triggered*: **117**, of which the record supports **111** (grounded).
- Drafts written: **0**; passing the hard evidence gate: **0** (first draft: **0**; one-shot repair tried on **0**, passed on **0**); drafts containing at least one unsupported fact: **0** (0 facts in total); drafts with unverified assertions listed for the officer: **0**.
- Seconds: assessment median 58.8, max 62.1; draft plus quality check median None, max None.

## Recommendation beside the scenario author's label

| Label (author) | Recommendation | Alerts |
|---|---|---|
| CONTESTED | FILE | 3 |
| CONTESTED | REVIEW | 1 |
| FILE | FILE | 8 |
| FILE | REVIEW | 1 |
| NOT_FILE | FILE | 1 |
| NOT_FILE | REVIEW | 2 |

FILE / NOT_FILE labels are the author's expectation; CONTESTED means the scenario has no pre-determined answer. REVIEW and INSUFFICIENT_EVIDENCE are the application declining to recommend, which is not an error.

## Per alert

| Alert | Label | Recommendation | Triggered | Grounded | Draft | Hard gate | Unsupported facts | Model | Assessment s |
|---|---|---|---|---|---|---|---|---|---|
| ALERT-01 | FILE | FILE | 8 | 8 | — | — | — | llama3.3-70b | 58.8 |
| ALERT-02 | FILE | FILE | 8 | 8 | — | — | — | llama3.3-70b | 58.2 |
| ALERT-03 | CONTESTED | REVIEW | 6 | 6 | — | — | — | llama3.3-70b | 47.8 |
| ALERT-04 | FILE | FILE | 9 | 9 | — | — | — | llama3.3-70b | 46.1 |
| ALERT-05 | FILE | FILE | 8 | 8 | — | — | — | llama3.3-70b | 48.1 |
| ALERT-06 | FILE | FILE | 6 | 6 | — | — | — | llama3.3-70b | 43.6 |
| ALERT-07 | NOT_FILE | REVIEW | 6 | 5 | — | — | — | llama3.3-70b | 58.5 |
| ALERT-08 | NOT_FILE | FILE | 4 | 4 | — | — | — | llama3.3-70b | 60.7 |
| ALERT-09 | FILE | FILE | 7 | 7 | — | — | — | llama3.3-70b | 47.5 |
| ALERT-10 | FILE | FILE | 8 | 7 | — | — | — | llama3.3-70b | 62.1 |
| ALERT-11 | CONTESTED | FILE | 9 | 8 | — | — | — | llama3.3-70b | 54.2 |
| ALERT-12 | FILE | FILE | 8 | 8 | — | — | — | llama3.3-70b | 60.8 |
| ALERT-13 | CONTESTED | FILE | 7 | 6 | — | — | — | llama3.3-70b | 58.9 |
| ALERT-14 | CONTESTED | FILE | 9 | 9 | — | — | — | llama3.3-70b | 61.5 |
| ALERT-15 | FILE | REVIEW | 6 | 6 | — | — | — | llama3.3-70b | 61.6 |
| ALERT-16 | NOT_FILE | REVIEW | 8 | 6 | — | — | — | llama3.3-70b | 59.4 |

## How to read this

- The assessment and the draft come from the live model; every check after them is deterministic and runs against the record in the environment.
- A draft that fails the hard gate is the gate working: the officer would be told which fact is unsupported before anything is recorded.
- The same author wrote the alerts, the labels and the validator. The fabrication benchmark (`evidence/fabrication-benchmark/`) is where the gate's own catch rate is measured.
