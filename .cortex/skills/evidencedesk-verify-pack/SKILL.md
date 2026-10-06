---
name: evidencedesk-verify-pack
description: Verify an EvidenceDesk inspection pack (decision dossier JSON) offline, with no Snowflake and no application, and explain the verdict without overstating it.
---

# Verify an inspection pack offline

An inspection pack is the JSON file the application's "Inspection pack" download produces for one recorded decision (`evidencedesk.decision-dossier/1`).
This skill checks it from the file alone.

## Steps

1. Confirm the file is the pack and not a screenshot or an export of something else: it is a JSON object with `"schema": "evidencedesk.decision-dossier/1"`.
2. Run the verifier from the repository root (it needs only the Python standard library and `skills/dossier.py`):

   ```
   python3 scripts/verify_dossier.py <pack.json> [--html <page.html>]
   ```

3. Read the exit status and the per-check lines:
   - `0`: no check failed. The verdict is VERIFIED, or INCOMPLETE where a check cannot be run on that decision (for example a decision recorded before provenance existed).
   - `1`: a check failed. Name the failed checks from the `Verdict:` line. Do not suggest the file is "slightly off": a hash that does not match is a different record.
   - `2`: the file could not be read as JSON.

## What a clean result does and does not show

- It shows that the file is as sealed, that the ledger row in the file hashes to the stored `ROW_HASH`, that the stored gate and regulatory basis are consistent with the
  rationale, and that the digests of the rationale and the included transactions match those recorded at the time.
- It does **not** show that the ledger still holds that row. That is what the audit export is for (see the `evidencedesk-audit-ledger` skill).
- It does not show that the decision was right. It shows that the record of it has not been altered since it was written.

## Rules

- Never edit a pack to make it verify. Never recompute and write a hash into it.
- Do not connect to Snowflake for this task; the point of the pack is that a reviewer without access can check it.
- Do not quote a verdict you did not run in this session.
