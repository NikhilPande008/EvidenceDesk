# Live model replay over the seeded alerts — 2026-10-06

**Synthetic data. One model. Counts over the seeded alerts; none of this is accuracy on real cases.**

- Code: commit `060ff14` + uncommitted changes; prompt version `v2.2`; corpus read from the environment below; environment: `FIU_COPILOT_CR2`; role: `FIU_APP_ROLE_CR2`.
- Model requested: `llama3.3-70b` (no fallback model allowed); model(s) that answered: `llama3.3-70b`. Decoding: temperature 0, structured outputs on. Nothing was recorded to the ledger.

## Result

- Assessments valid (all 11 factors parsed): **16 of 16** (3 alerts skipped or failed).
- Factors the model called *triggered*: **117**, of which the record supports **109** (grounded).
- Drafts written: **15**; passing the hard evidence gate: **14** (first draft: **13**; one-shot repair tried on **1**, passed on **1**); drafts containing at least one unsupported fact: **0** (0 facts in total); drafts with unverified assertions listed for the officer: **1**.
- Seconds: assessment median 78.7, max 116.2; draft plus quality check median 128.1, max 206.3.

## Recommendation beside the scenario author's label

| Label (author) | Recommendation | Alerts |
|---|---|---|
| CONTESTED | FILE | 3 |
| CONTESTED | REVIEW | 1 |
| FILE | FILE | 7 |
| FILE | REVIEW | 2 |
| NOT_FILE | FILE | 1 |
| NOT_FILE | REVIEW | 2 |

FILE / NOT_FILE labels are the author's expectation; CONTESTED means the scenario has no pre-determined answer. REVIEW and INSUFFICIENT_EVIDENCE are the application declining to recommend, which is not an error.

## Per alert

| Alert | Label | Recommendation | Triggered | Grounded | Draft | Hard gate | Unsupported facts | Model | Assessment s |
|---|---|---|---|---|---|---|---|---|---|
| ALERT-01 | FILE | FILE | 8 | 8 | READY | pass | 0 | llama3.3-70b | 86.8 |
| ALERT-02 | FILE | FILE | 8 | 8 | READY | pass | 0 | llama3.3-70b | 65.8 |
| ALERT-03 | CONTESTED | REVIEW | 6 | 6 | NEEDS_REVISION | pass | 0 | llama3.3-70b | 62.6 |
| ALERT-04 | FILE | REVIEW | 9 | 7 | READY | pass | 0 | llama3.3-70b | 58.3 |
| ALERT-05 | FILE | FILE | 8 | 8 | — | — | — | llama3.3-70b | 55.8 |
| ALERT-06 | FILE | FILE | 6 | 6 | READY | pass | 0 | llama3.3-70b | 3.1 |
| ALERT-07 | NOT_FILE | REVIEW | 6 | 5 | NEEDS_REVISION | pass | 0 | llama3.3-70b | 74.6 |
| ALERT-08 | NOT_FILE | FILE | 4 | 4 | READY | pass | 0 | llama3.3-70b | 69.2 |
| ALERT-09 | FILE | FILE | 7 | 7 | NEEDS_MANUAL_REVIEW | BLOCKED | 0 | llama3.3-70b | 99.1 |
| ALERT-10 | FILE | FILE | 8 | 7 | READY | pass | 0 | llama3.3-70b | 116.2 |
| ALERT-11 | CONTESTED | FILE | 9 | 8 | READY | pass | 0 | llama3.3-70b | 78.7 |
| ALERT-12 | FILE | FILE | 8 | 8 | READY | pass | 0 | llama3.3-70b | 84.6 |
| ALERT-13 | CONTESTED | FILE | 7 | 6 | READY | pass | 0 | llama3.3-70b | 74.5 |
| ALERT-14 | CONTESTED | FILE | 9 | 9 | READY | pass | 0 | llama3.3-70b | 93.1 |
| ALERT-15 | FILE | REVIEW | 6 | 6 | READY | pass | 0 | llama3.3-70b | 92.5 |
| ALERT-16 | NOT_FILE | REVIEW | 8 | 6 | READY | pass | 0 | llama3.3-70b | 87.8 |
| ALERT-17 | FILE | — | — | — | — | — | No Cortex model available in this region. Last error: 000630 (57014): Statement reached its statement or warehouse timeout of 120 second(s) and was canceled. | — | — |
| ALERT-18 | NOT_FILE | — | — | — | — | — | 000604 (57014): SQL execution canceled | — | — |
| ALERT-19 | NOT_FILE | — | — | — | — | — | 000604 (57014): SQL execution canceled | — | — |

## How to read this

- The assessment and the draft come from the live model; every check after them is deterministic and runs against the record in the environment.
- A draft that fails the hard gate is the gate working: the officer would be told which fact is unsupported before anything is recorded.
- The same author wrote the alerts, the labels and the validator. The fabrication benchmark (`evidence/fabrication-benchmark/`) is where the gate's own catch rate is measured.
