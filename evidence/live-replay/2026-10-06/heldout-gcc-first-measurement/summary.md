# Live model replay over the seeded alerts — 2026-10-06

**Synthetic data. One model. Counts over the seeded alerts; none of this is accuracy on real cases.**

- Code: commit `0ee1155` + uncommitted changes; prompt version `v2.2`; corpus read from the environment below; environment: `FIU_COPILOT_CR2`; role: `FIU_APP_ROLE_CR2`.
- Model requested: `llama3.3-70b` (no fallback model allowed); model(s) that answered: `llama3.3-70b`. Decoding: temperature 0, structured outputs on. Nothing was recorded to the ledger.

## Result

- Assessments valid (all 11 factors parsed): **3 of 3**.
- Factors the model called *triggered*: **21**, of which the record supports **21** (grounded).
- Drafts written: **3**; passing the hard evidence gate: **3** (first draft: **3**; one-shot repair tried on **0**, passed on **0**); drafts containing at least one unsupported fact: **0** (0 facts in total); drafts with unverified assertions listed for the officer: **0**.
- Seconds: assessment median 58.9, max 60.2; draft plus quality check median 86.69999999999999, max 98.0.

## Recommendation beside the scenario author's label

| Label (author) | Recommendation | Alerts |
|---|---|---|
| FILE | FILE | 1 |
| NOT_FILE | FILE | 2 |

FILE / NOT_FILE labels are the author's expectation; CONTESTED means the scenario has no pre-determined answer. REVIEW and INSUFFICIENT_EVIDENCE are the application declining to recommend, which is not an error.

## Per alert

| Alert | Label | Recommendation | Triggered | Grounded | Draft | Hard gate | Unsupported facts | Model | Assessment s |
|---|---|---|---|---|---|---|---|---|---|
| ALERT-17 | FILE | FILE | 10 | 10 | READY | pass | 0 | llama3.3-70b | 58.9 |
| ALERT-18 | NOT_FILE | FILE | 4 | 4 | READY | pass | 0 | llama3.3-70b | 45.9 |
| ALERT-19 | NOT_FILE | FILE | 7 | 7 | READY | pass | 0 | llama3.3-70b | 60.2 |

## How to read this

- The assessment and the draft come from the live model; every check after them is deterministic and runs against the record in the environment.
- A draft that fails the hard gate is the gate working: the officer would be told which fact is unsupported before anything is recorded.
- The same author wrote the alerts, the labels and the validator. The fabrication benchmark (`evidence/fabrication-benchmark/`) is where the gate's own catch rate is measured.
