# Why not just ask a model to check the narrative? (T5)

**Synthetic data. 160 cases the author wrote, a validator the author wrote, a checking prompt the author wrote, one run per model, temperature 0, structured output, no fallback model.
Counts with Wilson 95% intervals. None of this is accuracy in the field.**
Sources: `llm-llama3.3-70b/` and `llm-claude-sonnet-4-5/` (each has `results.json` and `summary.md`); harness `scripts/eval_llm_checker.py`; the validator-only arm is `python3 scripts/eval_llm_checker.py --offline`.

The alternative to the deterministic evidence gate is a second model call that reads the case record and the draft and lists what the record does not support. Both were put
on the same cases. "Flagged" means the checker listed at least one unsupported statement.

| | Deterministic validator | `llama3.3-70b` as checker | `claude-sonnet-4-5` as checker |
|---|---|---|---|
| Fabricated narratives caught (S2 + S3, 80 cases) | 65/80 (81.2%) | 76/80 (95.0%) | 80/80 (100.0%) |
| ...of which S3, never tuned on (38 cases) | 30/38 (78.9%) | 37/38 (97.4%) | 38/38 (100.0%) |
| Mis-attributions caught (set Q, 20 cases) | 12/20 (60.0%) | 19/20 (95.0%) | 18/20 (90.0%) |
| **Faithful narratives wrongly flagged (40 cases)** | **0/40 (0.0%, interval 0.0-8.8)** | **39/40 (97.5%)** | **15/40 (37.5%, interval 24.2-53.0)** |
| **Correct statements wrongly flagged (set R, 20 cases)** | **0/20 (0.0%, interval 0.0-16.1)** | **14/20 (70.0%)** | **5/20 (25.0%, interval 11.2-46.9)** |
| Seconds per check, median | microseconds | 22.3 | 14.0 |
| Tokens per check, median | none | 811 | 1522 |
| Same answer on three asks (24 cases) | deterministic | 24 of 24 | 23 of 24 |
| Unusable replies | none | 5 | 0 |

## What this shows

- **A model as the only gate would block most true narratives.** `llama3.3-70b` flagged 39 of 40 faithful narratives; `claude-sonnet-4-5` flagged 15 of 40. A gate that cries wolf at
  that rate gets overridden or switched off, and then it catches nothing. The validator wrongly flagged none of 60 faithful or correct cases (the upper end of the interval is
  still 8.8% and 16.1%, so "zero" is a count over these cases and not a promise).
- **The stronger model catches more than the validator does.** `claude-sonnet-4-5` caught all 80 fabrications and 18 of 20 mis-attributions, against 65 and 12 for the validator. The
  validator's misses are real (listed in `evidence/fabrication-benchmark/2026-10-05/`): unlisted places, meaning gaps, partial sums. A model's higher recall is a reason to consider it
  as an advisory second look beside the gate, with a person reading its list. It is not implemented, and these numbers do not say it would help a decision.
- **What the models objected to, from a read of 8 of Sonnet's 20 false flags.** In three of the eight the model's own explanation says the amount matches the record (for
  example that Rs.94,200 equals 0.942 lakh) and flags the sentence anyway. The others object to a rounded or derived percentage, to an inference ("opened in June 2025" from
  "14 months old"), or to a count. This is a small sample, read by the author, and it is not a classification of the 20.
- **Cost and repeatability.** The validator takes microseconds and no tokens; a checker call took 14 to 22 seconds and 800 to 1,500 tokens per narrative, and one case out of 24
  changed its answer between asks for Sonnet at temperature 0.

## Limits that matter

- The author wrote the cases, the validator and the checking prompt. A different prompt could move the false-flag rate in either direction; this one asks the model to list every
  unsupported statement, which invites over-flagging. The test is of this prompt, not of every possible checker.
- `llama3.3-70b` had 5 unusable replies (statement timeouts at 120 s, on four fabricated cases and one mis-attribution) because other jobs were using the same warehouse at the time.
  They count as misses against the model, so its catch rates are understated by up to 5 cases; they do not touch its false-flag counts, which are what the comparison turns on.
- S2 was used while building validator fixes (a regression record); S3 and Q were not tuned on, which is why they are reported separately.
- One run each. The models differ run to run even at temperature 0 (see the repeatability row).

## Decision

The evidence gate stays deterministic and is the only thing that blocks a filing. A model's list of doubts is not used to block or to allow. The application's existing model quality
check on a draft is unchanged by this comparison. Whether a second-look list from a stronger model helps an officer is untested.
