# Opt-in column masking: what was checked (T7)

**Environment: the isolated clean-room database only. Production was not touched. Synthetic data. No ledger row was read, written or changed.**

`deploy/10_governance_optin.sql` creates two masking policies and attaches them to `TRANSACTIONS.COUNTERPARTY` and `ALERTS.CUSTOMER_PROFILE`. A role that is not the
application role reads `*** masked ***`. It is opt-in: no deploy step runs it. `scripts/governance_policies.py` plans by default; `--apply` executes.

| File | What it shows |
|---|---|
| `probe_after_apply.txt` | After applying: the owner role reads 92 of 92 counterparties and 19 of 19 profiles masked; the application role reads all of them in clear. Same tables, same moment |
| `remove.txt` | `remove --apply` ran every statement (detach, detach, drop, drop) |
| `probe_after_remove.txt` | Afterwards the owner role reads all of them in clear again: the environment is back to how it was before the check |

## What this does and does not establish

- It establishes that, on this account, a masking policy keyed to `CURRENT_ROLE()` is accepted (so the edition supports it) and does what its header says for these two columns
  and these two roles.
- It was not run against a third role, and it was not run with the hosted application open: the claim that the app keeps working is the probe's "application role reads
  clear", not an application test. The environment was left without the policies after the check, so the live suites that ran afterwards say nothing about it.
- It is not row-level security. Which alerts a role may see needs an entitlement source (a desk, a branch, a jurisdiction) that this prototype does not have; none was invented.
- Free text that repeats the same names (`ALERT_NARRATIVE`, the ledger's rationale) is not masked.
- The owner role is masked too once the policy is on. That is the point of separating the person who loads data from the person who reads it, and it is a change to how
  the owner role is used, which a team would have to accept.
