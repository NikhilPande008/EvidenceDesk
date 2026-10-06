---
name: evidencedesk-audit-ledger
description: Run the read-only EvidenceDesk ledger reconciliation and explain each finding, including concurrent decisions on one alert, without ever modifying the ledger.
---

# Reconcile the decision ledger (read-only)

The ledger is append-only: the application role may INSERT and SELECT only. This skill reads it and reports; it never writes to it.

## Steps

1. Report, connecting as the default application role:

   ```
   python3 scripts/audit_ledger.py report            # exit 1 if COMPROMISED
   python3 scripts/audit_ledger.py report --json     # the same, machine-readable
   ```

2. Explain each finding in the report in the report's own terms. Findings you are likely to meet:
   - COMPROMISED findings (`TAMPERED_ROW`: the stored `ROW_HASH` does not match the row; `DELETED_RECORD`, `MODIFIED_SINCE_EXPORT`, `EXPORT_FIELDS_DIFFER`,
     `EXPORT_CHAIN_BROKEN`): the serious ones. Say so plainly, stop proposing fixes, and escalate to the ledger owner.
   - `LEGACY_UNHASHED_ROWS` and `PROVENANCE_INCOMPLETE`: ATTENTION, not failure. Those decisions pre-date the hash or the provenance record.
   - `HASH_NOT_COMPUTABLE`: ATTENTION. The integrity view returned no recomputed hash; say that the rows could not be checked.
   - `CONCURRENT_DECISIONS`: two decisions on one alert were written against the same earlier state (same `decision_sequence.prior_count`). The ledger cannot
     prevent this (Snowflake concurrent INSERTs do not lock and uniqueness is not enforced on this account); it is **detected, never prevented**. Both rows are
     kept. The desk lead decides which stands and records a superseding decision with a written reason.
   - `NOT_YET_EXPORTED`: ATTENTION until `export` runs; those rows are not yet covered against deletion.
3. To see how many rows are not yet exported without writing anything: `python3 scripts/audit_ledger.py export` (plan only).

## Rules

- Never run `export --apply`, `provision`, or any other command with `--apply` unless the user asks for that exact step in this conversation. Those use other roles.
- Never issue UPDATE, DELETE, TRUNCATE or DROP against `DECISION_LEDGER`, and never "repair" a row. A correction is a new decision that supersedes the old one.
- Do not print connection details or tokens. Errors are already reduced to one secret-free sentence; keep them that way.
- A clean report is a statement about the rows the application role can see at that moment, not about rows it cannot.
