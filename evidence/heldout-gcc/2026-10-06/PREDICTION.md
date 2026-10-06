# Held-out Gulf-remittance alerts (R4): what was written down before the model saw them

**Synthetic data. Written 2026-10-06 before any model was run on ALERT-17, ALERT-18 or ALERT-19. The labels are the author's expectation, not an adjudicated outcome.**

ALERT-17, ALERT-18 and ALERT-19 (`scripts/setup_alerts.py`, scenario ids G1 to G3) were written after the nexus rule (`skills/nexus_support.py`, DG-19, T3) was
frozen. That rule was designed after ALERT-16 was seen, so the 16-alert replay is a regression record for it; these three alerts are the first cases it has
not been shaped by. The result of their first live replay is a **first measurement**: it will be reported whichever way it falls, and the rule is **not** edited
in response to it.

| Alert | Pattern | Author's label | Same total as |
|---|---|---|---|
| ALERT-17 | Eight inward SWIFT credits from eight Gulf-city remitters with no recorded relationship, then cash withdrawals and two unidentified beneficiary accounts at other banks | FILE | ALERT-18 (Rs.14.2L) |
| ALERT-18 | Six monthly inward SWIFT credits from one employer named at the last KYC refresh, then a loan instalment and a term deposit in the customer's own name | NOT_FILE | ALERT-17 (Rs.14.2L) |
| ALERT-19 | One inward SWIFT credit from a former UAE employer (reference: end-of-service payment), then a term deposit in the customer's own name; no exit documents attached | NOT_FILE | none (Rs.21.5L) |

## What the frozen rule says offline (deterministic, no model)

`skills.nexus_support.assess` on each alert's rows:

| Alert | POE-007 Beneficiary | POE-010 Complexity |
|---|---|---|
| ALERT-17 | supported (a recipient is unidentified) | supported (the record shows a cross-border hop) |
| ALERT-18 | **not** supported (every outgoing row goes to a named counterparty with no flag) | supported (the record shows a cross-border hop) |
| ALERT-19 | **not** supported (the only outgoing row goes to a named counterparty with no flag) | supported (the record shows a cross-border hop) |

## Prediction

- **ALERT-17**: the rule leaves both factors standing, so a model that triggers either one can recommend FILE. Expected to match the label.
- **ALERT-18 and ALERT-19**: the beneficiary factor is discounted, which is the intended protection. **The complexity factor is not**, because the rule treats any SWIFT
  row as a cross-border hop, and these two alerts are legitimate inward remittances on a Gulf corridor. If the model triggers complexity on them, the rule as frozen
  cannot stop a FILE recommendation, and the first measurement will show it. This is a limitation of the rule that was visible before the run; it is stated here
  so that it is not discovered afterwards and described as a surprise.
- Whatever the model recommends, the officer's decision, the strength rule on the challenge panel and the deterministic evidence gate on any narrative sit after it.
  Nothing here records a decision.

## What is not claimed

Three alerts, one run, one author. This cannot show that the rule generalises. It can show that it does not.
