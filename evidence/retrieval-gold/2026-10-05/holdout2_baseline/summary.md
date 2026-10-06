# Regulatory reference: gold query run

- Run (UTC): 2026-10-05 17:54:06Z  ·  commit `e2021d8` (uncommitted changes present)
- Corpus v1.1.1 (snapshot 2026-10-05, 13 PROVEN, 23 ASSUMED)  ·  semantic floor `MIN_COSINE = 0.42`  ·  lexical coverage floor `0.5`
- Path under test: `CoPilotSkills.regulatory_lookup_with_basis` (Cortex Search + scope guard) against the live account; 0 of 78 queries were served by the keyword fallback.

## Results

| Set | Answerable answered | Unanswerable refused | Missed (answered but should abstain) | False refusals | Expected rule in top 5 |
|---|---|---|---|---|---|
| Calibration (G, X, W, K: 43 queries) | 19/20 | 22/22 (100.0%) | none | G19 | 18/20 |
| Holdout (H01-H10: 10 queries, not used to set any threshold) | 3/4 | 4/6 (66.7%) | H01, H02 | H08 | 3/4 |
| Holdout 2 (J01-J25: 25 queries, written before the generic foreign-regime screen) | 9/10 | 11/15 (73.3%) | J01, J03, J06, J12 | J23 | 8/10 |

Known gaps in the calibration set: 1; caught: K01.

## What this does and does not show

- The queries are written by the corpus author, so this is a regression and calibration record, not an independent benchmark.
- The semantic floor and the unknown-acronym rule were set or added after seeing calibration results; the holdout is the fairer number.
- Questions about a foreign regime that reuse Indian STR vocabulary score high on similarity (0.5-0.65) and are caught only by the named-regime screen. Where the screen does not list the regime, the guard can miss them. Misses are listed, not hidden.

## Misses against expectation

- **G19** (expected answer, got abstain, cosine 0.448, coverage 0.333): Does an STR need to say that the beneficiary is in Dubai?
- **H01** (expected abstain, got answer, cosine 0.484, coverage 0.625): What is the Suspicious Activity Report filing deadline for a bank in the United States?
- **H02** (expected abstain, got answer, cosine 0.443, coverage 0.571): How should a Canadian bank file an unusual transaction report with FINTRAC?
- **H08** (expected answer, got abstain, cosine 0.517, coverage 0.429): Can we file an STR for a customer whose account was never opened?
- **J01** (expected abstain, got answer, cosine 0.498, coverage 0.667): What is the deadline to file a suspicious activity report in Germany?
- **J02** (expected abstain, got abstain, cosine 0.434, coverage 0.444): How quickly must a Hong Kong bank report suspected money laundering to the JFIU?
- **J03** (expected abstain, got answer, cosine 0.497, coverage 0.667): Do Japanese banks have to report large cash transactions?
- **J04** (expected abstain, got abstain, cosine 0.393, coverage 0.333): Which agency in the Philippines receives covered transaction reports?
- **J05** (expected abstain, got abstain, cosine 0.549, coverage 0.571): How does a Nigerian bank submit a suspicious transaction report to the NFIU?
- **J06** (expected abstain, got answer, cosine 0.611, coverage 0.833): What is Canada's threshold for large cash transaction reports?
- **J07** (expected abstain, got abstain, cosine 0.474, coverage 0.375): How long must a bank in Qatar keep customer due diligence records?
- **J08** (expected abstain, got abstain, cosine 0.367, coverage 0.5): What triggers a SAR at an American bank?
- **J09** (expected abstain, got abstain, cosine 0.307, coverage 0.333): How should a Swiss private bank file a report with MROS?
- **J10** (expected abstain, got abstain, cosine 0.381, coverage 0.0): What are the beneficial ownership reporting duties for companies in the UK?
- **J12** (expected abstain, got answer, cosine 0.52, coverage 0.5): When must an exchange house in Dubai report a suspicious transaction?
- **J23** (expected answer, got abstain, cosine 0.454, coverage 0.429): A remitter in Dubai sent funds to our customer. What should the STR say about the remitter's country?
