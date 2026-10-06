---
name: evidencedesk-load-feed
description: Validate an institution's alert and transaction feed against the EvidenceDesk data contract with a dry run, report what would be refused and why, and write only when explicitly told to.
---

# Load a case feed (dry run first)

The contract is `skills/feed_contract.py`; the columns and rules are in `docs/DATA_CONTRACT.md`. A feed carries signals and the rows behind them. It never carries an
answer key or a decision, and the loader refuses one that does.

## Steps

1. Dry run. This writes nothing and prints what would be accepted and what would be refused, with the reason for each refusal:

   ```
   python3 scripts/load_feed.py --alerts <alerts.csv> --transactions <transactions.csv> [--map <mapping.json>] [--report report.json]
   ```

   A feed in another shape needs a mapping file; `domain/feeds/tm_export_mapping.json` is the worked example (a monitoring-system export).
2. Show the user the counts and every refusal. Do not reword a refusal into something softer. If rows are refused, say which and why, and stop.
3. Only if the user explicitly asks to write, and only with an owner role (the application role cannot write):

   ```
   python3 scripts/load_feed.py ... --apply --expect-database <DATABASE> [--schema AML]
   ```

   `--expect-database` must name the database the connection is actually on; the loader refuses if it does not. Re-running is safe (the write is a MERGE).

## Rules

- Never pass `--apply` on your own initiative, and never against the production database from a test or demonstration.
- Never invent rows, fill a missing field with a plausible value, or infer a suspicion time from an alert date. A missing optional field stays missing.
- A loaded feed changes what the queue shows. Say what changed (counts), not that the data is "clean".
