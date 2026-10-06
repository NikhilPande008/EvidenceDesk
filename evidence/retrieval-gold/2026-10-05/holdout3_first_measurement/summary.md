# Regulatory reference: gold query run

- Run (UTC): 2026-10-05 17:57:59Z  ·  commit `e2021d8` (uncommitted changes present)
- Corpus v1.1.1 (snapshot 2026-10-05, 13 PROVEN, 23 ASSUMED)  ·  semantic floor `MIN_COSINE = 0.42`  ·  lexical coverage floor `0.5`
- Path under test: `CoPilotSkills.regulatory_lookup_with_basis` (Cortex Search + scope guard) against the live account; 0 of 98 queries were served by the keyword fallback.

## Results

| Set | Answerable answered | Unanswerable refused | Missed (answered but should abstain) | False refusals | Expected rule in top 5 |
|---|---|---|---|---|---|
| Calibration (G, X, W, K: 43 queries) | 20/20 | 22/22 (100.0%) | none | none | 18/20 |
| Holdout (H01-H10: 10 queries, not used to set any threshold) | 3/4 | 6/6 (100.0%) | none | H08 | 3/4 |
| Holdout 2 (J01-J25: 25 queries, written before the generic foreign-regime screen) | 10/10 | 15/15 (100.0%) | none | none | 8/10 |
| Holdout 3 (L01-L20: 20 queries, written after the generic screen was built, measured once) | 8/8 | 11/12 (91.7%) | L05 | none | 5/8 |

Known gaps in the calibration set: 1; caught: K01.

## What this does and does not show

- The queries are written by the corpus author, so this is a regression and calibration record, not an independent benchmark.
- The semantic floor and the unknown-acronym rule were set or added after seeing calibration results; the holdout is the fairer number.
- Questions about a foreign regime that reuse Indian STR vocabulary score high on similarity (0.5-0.65) and are caught only by the named-regime screen. Where the screen does not list the regime, the guard can miss them. Misses are listed, not hidden.

## Misses against expectation

- **H01** (expected abstain, got abstain, cosine None, coverage None): What is the Suspicious Activity Report filing deadline for a bank in the United States?
- **H02** (expected abstain, got abstain, cosine None, coverage None): How should a Canadian bank file an unusual transaction report with FINTRAC?
- **H08** (expected answer, got abstain, cosine 0.517, coverage 0.429): Can we file an STR for a customer whose account was never opened?
- **L03** (expected abstain, got abstain, cosine 0.39, coverage 0.6): Does an Australian bank need to report international funds transfers?
- **L05** (expected abstain, got answer, cosine 0.465, coverage 0.5): What must a bank in the Cayman Islands do when it suspects money laundering?
- **L07** (expected abstain, got abstain, cosine 0.521, coverage 0.429): Under Egyptian rules, how long are customer due diligence files retained?
- **L12** (expected abstain, got abstain, cosine 0.42, coverage 0.4): Can an Indonesian bank share an STR with its parent bank?
