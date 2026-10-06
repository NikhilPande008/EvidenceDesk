# Case feed contract

EvidenceDesk investigates signals that other systems raise. This is what a detection or case-management system sends it, what is refused at the door,
and how an export in another shape is mapped onto it. The contract is code: [`skills/feed_contract.py`](../skills/feed_contract.py), checked by
`tests/test_feed_contract.py`. The loader is [`scripts/load_feed.py`](../scripts/load_feed.py).

All data in this repository is synthetic. Send an institution's real data only after the controls in [SECURITY.md](../SECURITY.md) exist: this prototype has no
masking, no row-access policy and no pseudonymisation of its own, so the references below must already be pseudonymous when they arrive.

## Two files

**alerts**: one row per alert.

| Field | Required | Meaning |
|---|---|---|
| `alert_id` | yes | Unique id of the alert in the source system. Letters, digits, `.`, `_`, `-`; at most 20 characters. |
| `customer_ref` | yes | Pseudonymous customer reference. Never a name or an account number. At most 20 characters. |
| `alert_date` | yes | `YYYY-MM-DD`, the day the detector raised it. Not in the future. |
| `alert_type` | yes | Detector rule name, for example `MULE_PASSTHROUGH`. |
| `alert_amount_inr` | yes | The amount the alert is about, in rupees. Positive. |
| `signal_source` | no | Which system raised it, for example `INTERNAL_RULE`. |
| `account_type` | no | `SAVINGS`, `CURRENT`, `NRO` and so on. |
| `customer_profile` | no | One-line KYC summary (at most 500 characters). |
| `alert_narrative` | no | What the detector observed: observations, not conclusions (at most 2000 characters). |
| `suspicion_formed_at` | no | ISO 8601 **with a time zone**. When suspicion formed; it starts the 7-working-day clock. Leave it empty if unknown: it is never inferred from the alert date. |
| `rfi_triggers` | no | Detector tags separated by `;`. |

**transactions**: one row per transfer behind an alert.

| Field | Required | Meaning |
|---|---|---|
| `txn_id` | yes | Unique id of the row. Same character rules, at most 20 characters. |
| `alert_id` | yes | The alert this row belongs to. It must be an alert accepted in the same feed. |
| `txn_date` | yes | `YYYY-MM-DD` value date. |
| `txn_type` | yes | `CREDIT` (into the customer's account) or `DEBIT` (out of it). |
| `amount_inr` | yes | Rupees, positive. |
| `channel` | no | `UPI`, `NEFT`, `RTGS`, `IMPS`, `CASH`, `SWIFT`, `ATM` and so on. |
| `counterparty` | no | The other party, named as the source system names it. |
| `is_flagged` | no | `true` or `false`: the source system's watch-list or registry flag. |
| `customer_ref` | no | Defaults to the alert's customer. |

CSV (UTF-8, header row) or a JSON list of objects. Samples: [`domain/feeds/canonical_alerts.csv`](../domain/feeds/canonical_alerts.csv) and
[`canonical_transactions.csv`](../domain/feeds/canonical_transactions.csv).

## What is refused, and what is only warned about

A row is **refused**, with the field and the reason, when a required field is missing, an id is malformed or repeated, a date is not a real `YYYY-MM-DD` date
(or is in the future), an amount is not a positive number, `txn_type` is not `CREDIT` or `DEBIT`, text carries a control character or is too long, a
`suspicion_formed_at` has no time zone, or a transaction points at an alert that was not accepted. **Nothing is repaired or guessed.** Accepted rows still
load when others are refused.

Only a **warning** (the row loads; the officer will see the consequence): an alert with no transaction rows (the evidence gate has nothing to check a
narrative against, so FILE is blocked); credits and debits that both differ from the alert amount by more than 1% (the case page shows an
amount-reconciliation finding); no `suspicion_formed_at` (the clock reads "not recorded").

## A feed in another shape

[`domain/feeds/tm_export_mapping.json`](../domain/feeds/tm_export_mapping.json) maps a transaction-monitoring export with its own column names, `D`/`C` codes, `Y`/`N`
flags, `DD/MM/YYYY` dates, a zone-less timestamp (the mapping says which zone it is in) and Indian digit grouping (`4,60,000`) onto the contract. The sample
export also carries three deliberately bad rows; the loader refuses them with the reason and loads the rest.

```bash
python scripts/load_feed.py --alerts domain/feeds/tm_export_alerts.csv --transactions domain/feeds/tm_export_transactions.csv \
       --map domain/feeds/tm_export_mapping.json            # a DRY RUN: validates, reports, writes nothing
```

## Loading

The default is a dry run. `--apply` needs an **owner role** (the application role cannot write alerts, by design) and `--expect-database NAME`, the database
the connection is really on; it refuses on a mismatch, so a feed cannot land in the wrong environment by accident. Loading is a `MERGE`: running a feed twice
updates the same alerts and does not duplicate them. A feed carries signals and the rows behind them, never an answer key and never a decision.
Evidence that this works against Snowflake: [`evidence/feed-load/2026-10-06/`](../evidence/feed-load/2026-10-06/live_transaction_proof.txt).

## What this does not do

It is a batch loader, not an integration: no streaming, no API, no scheduling, no entity resolution, and no write-back of decisions to the source system. A
production deployment would feed this from its transaction-monitoring system on a schedule and attach the inspection pack of each decision to its case record.
