# Which model drafts the assessment: a measured comparison (T2)

**Synthetic data, one run per model, assessment step only (`--no-draft`), the 16 seeded alerts, `FIU_COPILOT_CR2`, temperature 0, structured outputs on, no fallback allowed.
Nothing was recorded to the ledger. The labels were written by the same author as the alerts and the validator, so none of this is accuracy on real cases.**

Sources: `2026-10-05/model-llama3.1-8b/`, `2026-10-05/model-claude-sonnet-4-5/`, `2026-10-06/model-llama3.3-70b/` (each has `summary.md`, `results.json`, `raw_responses.json`).

## Result

| | llama3.1-8b | llama3.3-70b | claude-sonnet-4-5 |
|---|---|---|---|
| Assessments with all 11 factors parsed | 16 / 16 | 16 / 16 | 16 / 16 |
| Factors called *triggered* | 83 | 117 | 132 |
| ...of which the record supports | 75 (90.4 %) | 111 (94.9 %) | 129 (97.7 %) |
| Triggered but not supported by the record | 8 | 6 | 3 |
| Assessment seconds, median (max) | 24.6 (33.9) | 58.8 (62.1) | 29.6 (34.1) |
| Recommendation on the 9 author-labelled FILE alerts | 7 FILE, 2 REVIEW | 8 FILE, 1 REVIEW | 9 FILE |
| Recommendation on the 3 author-labelled NOT_FILE alerts | 3 REVIEW | 1 FILE, 2 REVIEW | 3 FILE |
| Recommendation on the 4 CONTESTED alerts | 2 FILE, 2 REVIEW | 3 FILE, 1 REVIEW | 4 FILE |

## What the numbers say, and what they do not

- **Every model produced a parseable assessment every time.** Fail-closed parsing was never exercised by these runs, so they say nothing about it either way.
- **claude-sonnet-4-5 recommended FILE on all 16 alerts**, including the three the author labelled NOT_FILE and the four contested ones. It triggers the most factors (8.3 per alert against 7.3 and 5.2) and therefore its recommendation never separates the cases. For a tool whose point is a defensible decision, a model that always supports filing is the wrong default even though it is about twice as fast as llama3.3-70b and has the best support rate.
- **llama3.1-8b is the opposite**: it declined to recommend FILE on all three NOT_FILE alerts, but also on two of the nine FILE alerts, and has the lowest support rate (8 of 83 triggered factors are not backed by the record).
- **llama3.3-70b is the only one of the three whose recommendation differs between the groups** (8 of 9 FILE, 2 of 3 NOT_FILE declined) and it is the slowest by about a factor of two (median 58.8 s, which stays a real cost at the desk).
- It still recommended FILE on one NOT_FILE alert (ALERT-08). The application's deterministic gates, the strength rule on the challenge and the officer's own decision sit after the model; this table is about the model only.
- 16 alerts and one run each cannot rank models. Treat the differences between 70b and 8b as indicative and the Sonnet result (no discrimination at all across 16 alerts) as the strongest finding.
- **Run-to-run variation is real at temperature 0.** The same model on the same alert did not always give the same recommendation across runs (ALERT-16: FILE in the A/B runs, REVIEW in this run), and latency moved with service load (the same model's median was 81 s and 92 s in the A/B runs and 58.8 s here). One run is not a distribution.
- **ALERT-16's result is a regression record, not a held-out one**: the nexus rule (T3) was designed after that alert was seen. A held-out check needs alerts written after the rule was frozen (R4).

## Decision

Keep `llama3.3-70b` as the primary and `llama3.1-8b` as the declared fallback (unchanged in `skills/core.py`). Not chosen on accuracy; chosen because it is the only approved model tested here that does not recommend FILE regardless of the case. The replay answers in the app are labelled with the model that answered, so a fallback is visible.

## Structured outputs on/off (T1), 4 alerts, llama3.3-70b requested

Folders `2026-10-05/ab-structured-on/` and `ab-structured-off/` (alerts 01, 16, 03, 12).

- All four assessments parsed with structured outputs on and with them off. This does not show that structured outputs improve validity: nothing failed in either arm.
- **The comparison is not clean.** In the "on" arm ALERT-01 was answered by the fallback `llama3.1-8b`, so only three alerts are comparable pairs. The difference on those three was -16.9, -16.7 and +1.4 seconds (on minus off, negative = faster with structured outputs on), against a noise level of 20 s or more between runs of the same model. No latency benefit can be claimed from this.
- The reason to keep the schema on is that it removes the parser's reliance on the model happening to emit well-formed JSON; it is not a latency or a quality claim.
