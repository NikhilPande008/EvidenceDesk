# The real model over all 19 alerts, 6 October: what the two runs add up to

**Synthetic data. One model (`llama3.3-70b`, no fallback), temperature 0, structured outputs on, `FIU_COPILOT_CR2`, application role. Nothing was recorded to the ledger.
The labels are the author's expectation. None of this is accuracy on real cases.**

## Where the numbers come from

- `results.json` and `summary.md` in this folder (the raw model replies are not kept in the repository): the full run over all 19 alerts. **16 of 19 assessments were valid.** ALERT-17, ALERT-18 and ALERT-19 produced no result
  (Cortex statement timeout or cancellation), ALERT-05's draft call errored, and ALERT-09's draft was blocked because its quality-check call timed out (the application failed closed, as it should).
  That run is kept exactly as it came out.
- `retry-of-timed-out-alerts/`: a second run of ALERT-05, 09, 17, 18, 19 only. 5 of 5 valid, 5 drafts, all passed the hard gate first time.
- `heldout-gcc-first-measurement/`: the earlier run of ALERT-17..19 alone (see `evidence/heldout-gcc/2026-10-06/`). The retry reproduced its three recommendations.
- The sleep of the machine running the harness (about 70 minutes, visible as a gap in the Cortex query history) fell between calls, not inside one; it does not affect the per-call seconds below.

**Combined, "latest valid result per alert":** the retry's result for ALERT-05, 09, 17, 18, 19 and the full run's for the other 14. Nothing was averaged and no result was selected for how it looked.

## Combined result (19 alerts)

| | |
|---|---|
| Assessments valid (all 11 factors parsed) | 19 of 19 |
| Factors called *triggered* / supported by the record | 138 / 130 (94.2%). "Supported" only means the cited transaction ids exist in the record |
| Drafts written / passing the hard evidence gate | 19 / 19: 18 first time, 1 after the one-shot repair (ALERT-06, a channel the record did not hold) |
| Drafts with an unsupported fact in the final text | 0 |
| Drafts with unverified assertions listed for the officer | 2 |
| Assessment seconds | median 77.5, max 116.2 |
| Draft plus quality check, seconds | median 130.4, max 206.3 |

## Recommendation beside the author's label

| Label | Recommendation | Alerts |
|---|---|---|
| FILE (10) | FILE | 01, 02, 05, 06, 09, 10, 12, 17 (8) |
| FILE (10) | REVIEW | 04, 15 (2) |
| NOT_FILE (5) | REVIEW | 07, 16 (2) |
| NOT_FILE (5) | FILE | 08, 18, 19 (3) |
| CONTESTED (4) | FILE | 11, 13, 14 (3) |
| CONTESTED (4) | REVIEW | 03 (1) |

REVIEW is the application declining to recommend, which is not an error. FILE on a NOT_FILE-labelled alert is the miss this table is for.

## What the record check (T3) did

`recommendation_before_record_check` against `recommendation` moved exactly two alerts, both from FILE to REVIEW:

- **ALERT-16**, the legitimate twin of ALERT-01: intended. The model triggered Beneficiary and Complexity; the record has a named hospital as the only recipient and no cross-border hop,
  no repeated cash and no flagged party, so both were discounted.
- **ALERT-04**, a PEP receiving corporate credits and labelled FILE by the author: **a cost of the rule.** The only money-nature factor of the model's that was grounded was Complexity (POE-010);
  Income Level (POE-005) and Source of Income (POE-006) were triggered but cited no transaction, so they were not grounded. The record has six credits from named companies, nothing flagged,
  no cross-border hop and no cash, so the rule discounted Complexity ("a pass-through shape only") and the recommendation fell to REVIEW. Nothing is lost beyond the recommendation: the officer
  still sees the alert, the factors and the record. On the 5 October replies the rule moved only ALERT-16 (`tests/test_nexus_support.py`); a different reply from the same model on 6 October moved
  a second one. A rule that can only discount will sometimes discount a case an author would file, and this is one.

ALERT-08, ALERT-18 and ALERT-19 (all NOT_FILE-labelled) are still recommended FILE. The Gulf-remittance two are the held-out miss explained in `evidence/heldout-gcc/2026-10-06/FIRST_MEASUREMENT.md`.

## Limits

- One model, one run (plus the retry), 19 alerts the author wrote. The same model gave different recommendations on the same alert across runs at temperature 0 (see `evidence/live-replay/MODEL_COMPARISON_2026-10-06.md`).
- The median assessment time (about 78 s) is the figure a desk would feel; it did not improve with structured outputs.
- ALERT-17..19 are not held out for the T3 rule in any run after the first; the retry is a repeat, not a new test.
