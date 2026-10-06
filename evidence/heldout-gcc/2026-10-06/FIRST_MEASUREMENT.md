# Held-out Gulf-remittance alerts (R4): first measurement

**Synthetic data. Three alerts, one run, one model (`llama3.3-70b`, no fallback), temperature 0, structured outputs on, assessment and draft, `FIU_COPILOT_CR2`.
Nothing was recorded to the ledger. The labels are the author's expectation.**
Raw evidence: `evidence/live-replay/2026-10-06/heldout-gcc-first-measurement/` (`results.json`, `summary.md`, `raw_responses.json`).
The prediction was committed before this run: [`PREDICTION.md`](PREDICTION.md) (commit `0ee1155`).

## Result

| Alert | Author's label | Recommendation | Factors the model called triggered | Nexus factors that counted toward FILE | Draft |
|---|---|---|---|---|---|
| ALERT-17 | FILE | **FILE** (as labelled) | 002 003 004 005 006 007 008 009 010 011 | 006, 007, 010, 011 | READY, passed the hard gate first time, 0 unsupported facts |
| ALERT-18 | NOT_FILE | **FILE** (not as labelled) | 003 008 009 011 | **011 only** | READY, passed, 0 unsupported facts |
| ALERT-19 | NOT_FILE | **FILE** (not as labelled) | 002 004 005 006 009 010 011 | 006, 010, 011 | READY, passed, 0 unsupported facts |

- 1 of 1 FILE-labelled alert recommended FILE. **0 of 2 NOT_FILE-labelled alerts were recommended anything but FILE.**
- Every triggered factor was grounded (21 of 21), and the three drafts passed the deterministic evidence gate with no unsupported fact. The failure is not
  fabrication: every fact the model used is in the record. It is a judgement about what the facts mean.
- The record-backed nexus rule (T3) discounted nothing on any of the three (`discounted_nexus_factors` is empty for all). The recommendation before and after the
  record check was the same.

## Why it failed, read from the result and not guessed

- **ALERT-18**: the only nexus factor that counted was **POE-011, Geographies**. The model triggered it on an employer in Dubai paying a UAE-resident engineer's
  NRE account. The T3 rule tests POE-007 and POE-010 only; it has no test for geography, so the factor stood and carried the recommendation alone.
- **ALERT-19**: POE-006 (source of income) cannot be tested against the record (no income or exit documents are on the alert), POE-011 as above, and
  POE-010 (complexity) is supported by the frozen rule's "cross-border hop" clause, which is true of any inward SWIFT row.
- **ALERT-17 vs ALERT-18**, the pair with the same total (Rs.14.2L): the model recommended FILE on both. The record separates them (eight unrelated remitters and
  onward flow to unidentified accounts, against one employer named at the KYC refresh and onward flow to a loan and the customer's own term deposit), and the
  recommendation did not.

This is what `PREDICTION.md` said could happen for the complexity clause. The geography route was not predicted.

## What was deliberately not done

- **The rule was not changed in response.** Any edit would be shaped by these three alerts, and the same three would then no longer be held out. A test of a
  changed rule needs new alerts written after the change.
- **No jurisdiction list was added.** The corpus itself says the product "should maintain a current jurisdiction risk list" (POE-011, RFI-008) and does not
  hold one; the author cannot verify the current FATF composition from here, so a hard-coded list would be an unverified claim. Until one exists with an owner
  and a refresh date, the application cannot check the model's geography claim and the officer has to.

## What this means for the product

- The application still declines to record anything on the model's say-so: the officer decides, the challenge panel argues the opposite case, and the evidence
  gate checks every fact in a narrative. This measurement says the *recommendation* is over-eager on legitimate cross-border corridors.
- The recommendation direction on these alerts should not be quoted as accuracy. It is a stated limitation next to the T3 result on ALERT-16.
- What would address it, in order: a maintained jurisdiction-risk reference (data, with an owner), a rule that a cross-border hop alone is not complexity,
  and a new held-out set to measure either. All three are open.
