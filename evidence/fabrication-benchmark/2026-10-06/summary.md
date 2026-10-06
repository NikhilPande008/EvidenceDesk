# Fabrication-catch benchmark: deterministic evidence validator

- Run (UTC): 2026-10-06 03:56:16Z  ·  commit `6d154c9` (uncommitted changes present)
- Record: ALERT-01 as seeded (5 UPI transactions; 12 figures derivable from them: transactions, totals, subset sums, income). No model, no Snowflake.

## Read this first

The author wrote both the validator and these narratives. The in-distribution set mostly shows that the validator keeps catching what it was built to catch; the **stress set** is the generalisation estimate, and the **limits** below are what it cannot see. Intervals are Wilson 95%.

## Headline numbers

| Question | Result |
|---|---|
| Faithful narratives wrongly blocked (hard) | 0/70 (0.0%, 95% interval 0.0-5.2%) |
| Faithful narratives wrongly flagged for acknowledgement (soft) | 0/70 (0.0%, 95% interval 0.0-5.2%) |
| Faithful narratives for the other alerts with real rows (ALERT-01, ALERT-02, ALERT-03, ALERT-04, ALERT-05, ALERT-07, ALERT-08, ALERT-11, ALERT-12, ALERT-14, ALERT-15, ALERT-16, ALERT-17, ALERT-18, ALERT-19) wrongly blocked | 0/69 (0.0%, 95% interval 0.0-5.3%) |
| Fabricated narratives blocked, in-distribution (154 narratives, 9 claim classes) | 154/154 (100.0%, 95% interval 97.6-100.0%); named the right class 154/154 (100.0%, 95% interval 97.6-100.0%) |
| Soft fabrications flagged for acknowledgement (22 narratives) | 18/22 (81.8%, 95% interval 61.5-92.7%) |
| Stress set S (regression record: round-1 fixes were written against it) | 40/40 (100.0%, 95% interval 91.2-100.0%) |
| Stress set S2 (regression record: its misses motivated round 2) | 35/42 (83.3%, 95% interval 69.4-91.7%) |
| Stress set S3 (**the estimate to quote**: written before round 2, never tuned on; 3 of its 38 phrasings are in the shapes round 2 patched) | 30/38 (78.9%, 95% interval 63.6-88.9%) |
| Mis-attribution, development set M (every fact real, claim false; the check was built against it) | 9/9 |
| Mis-attribution, set N (written before the check; partly seen while designing it) | 15/15 |
| Set Q on the current code (a regression record: two changes were made after Q was first measured) | 12/20; correct statements wrongly flagged 0/20 |
| Correctly bound statements (set P) wrongly flagged | 0/18 |

## In-distribution, by claim class

| Class | Narratives | Blocked | Named the right class |
|---|---|---|---|
| amount | 30 | 100.0% | 100.0% |
| channel | 14 | 100.0% | 100.0% |
| date | 20 | 100.0% | 100.0% |
| entity | 16 | 100.0% | 100.0% |
| geography | 20 | 100.0% | 100.0% |
| identifier | 14 | 100.0% | 100.0% |
| profile_fact | 16 | 100.0% | 100.0% |
| profile_income | 12 | 100.0% | 100.0% |
| txn_id | 12 | 100.0% | 100.0% |

## Stress sets, by claim class

**Set S**: amount 10/10; channel 6/6; date 6/6; entity 5/5; geography 6/6; identifier 3/3; profile_fact 3/3; profile_income 1/1

**Set S2**: amount 10/10; channel 5/6; date 8/8; entity 4/5; geography 2/5; identifier 3/3; profile_fact 2/4; profile_income 1/1

**Set S3**: amount 8/8; channel 5/6; date 5/6; entity 4/6; geography 3/6; identifier 2/2; profile_fact 2/3; profile_income 1/1

## Stress phrasings still not caught

- **Y20** (channel, set S2): The funds were sent through a mobile wallet.
- **Y26** (geography, set S2): A counterparty in Lithuania was involved.
- **Y27** (geography, set S2): Payments went to Vanuatu.
- **Y28** (geography, set S2): Funds were sent to Oslo.
- **Y32** (entity, set S2): The beneficiary is Zenith Securities.
- **Y40** (profile_fact, set S2): The customer is a serving government official.
- **Y42** (profile_fact, set S2): The customer is 29 years old.
- **Z11** (date, set S3): On the 3rd day of September the account was used.
- **Z16** (channel, set S3): The customer used a mobile banking app to push funds.
- **Z21** (geography, set S3): Funds were transferred to Hungary.
- **Z23** (geography, set S3): A payment reached Casablanca.
- **Z26** (geography, set S3): The recipient lives in Chittagong.
- **Z29** (entity, set S3): Funds went to Nair & Nair.
- **Z32** (entity, set S3): A wallet company, PhonePe, was involved.
- **Z38** (profile_fact, set S3): He is a government servant.

## Soft fabrications not flagged, and why

A percentage passes when it is within 0.6 points of any ratio derivable from the transactions. Fabricated figures that happen to land there are not flagged:

- **H09** (percentage): ... to UPI handle C (I4C-flagged). The customer's declared income is Rs.28K per month. 99.9% of the credits were withdrawn.
- **H09** (percentage): ... handle. The credits total Rs.3.45L and 98.8% of that left the account within days. 99.9% of the credits were withdrawn.
- **H11** (percentage): ...ed handle. The credits total Rs.3.45L and 98.8% of that left the account within days. 40% of the funds were sent abroad.
- **H11** (percentage): ...credits are about 12 times that income, and none of the counterparties is documented. 40% of the funds were sent abroad.

## Published limits

1. **Attribution is checked only in unambiguous sentences, and only some of it.** The check (skills/attribution.py) reads one amount that is a single transaction with one named party, a direction cue, a date, a total's side, a ratio's side, "all credits/debits" and a flagged party. A sentence with several parties and amounts, a negation, a hypothetical, or an amount that is also a sum of transactions is skipped, not guessed at. Findings are SOFT (the officer acknowledges them before filing), because the extraction is heuristic. On the fresh set Q it missed:

   - Q01 (wrong direction): "Rs.11,00,000 was paid to ABC Infrastructure Ltd on 2026-07-15."
   - Q06 (partial sum called the total): "The credits totalled Rs.4,80,000 over two months."
   - Q07 (wrong direction): "Rs.6,20,000 left the account for DEF Engineering Pvt Ltd on 2026-06-20."
   - Q13 (wrong date): "Rs.4,20,000 was transferred by NEFT on 2026-08-19."
   - Q14 (wrong direction): "ACCT-02-B paid out Rs.1,42,500 by NEFT."
   - Q15 (ratio on the wrong side): "Of the credits received, 100% were forwarded to flagged handle C."
   - Q19 (wrong direction (cue not read)): "UPI handle B was the recipient of Rs.1.4L."
   - Q20 (two parties in one sentence): "Rs.1.4L went from UPI handle A to UPI handle C."

   Anything outside those patterns (causal links, "X is the largest sender", paraphrase the cues do not read) is still accepted wherever the text places it.

2. **Coarser notation, wider acceptance.** A stated amount is accepted within half a displayed unit of any derivable figure, which is exactly a correct rounding of a record figure. The share of displayed figures accepted:

   - whole lakh (Rs.4 lakh): 3/10 (30.0%)
   - one decimal lakh (Rs.4.3 lakh): 11/100 (11.0%)
   - two decimals lakh (Rs.4.35 lakh): 7/199 (3.5%)
   - exact rupees (Rs.4,35,000): 7/397 (1.8%)

3. **Percentages are a soft check with a wide band.** 9 of 99 whole percentages pass unflagged (9.1%): [8, 27, 28, 32, 40, 41, 71, 72, 99].
4. **Lists, not understanding.** Geographies, companies and channels are matched against lists and patterns. Anything outside them is not seen (see the stress sets).
5. **English, INR, India-centric.** No other language or currency is checked beyond foreign amounts being unsupported unless the record contains them.

