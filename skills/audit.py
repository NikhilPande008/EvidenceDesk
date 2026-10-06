"""
Ledger audit: a NON-DESTRUCTIVE integrity reconciliation and an append-only audit EXPORT.

Why this exists, and what it does NOT do
  Database RBAC is the primary protection: the app role can only INSERT and SELECT on DECISION_LEDGER.
  ROW_HASH (skills/ledger.py) makes an in-place EDIT detectable. Neither shows that a row was DELETED by someone holding
  the object-owner role (or ACCOUNTADMIN). This module adds the missing witness: an export of (decision id, row hash)
  pairs, hash-CHAINED and kept where the ledger owner cannot rewrite it (deploy/05_audit_export.sql, opt-in). Reconciling
  the live ledger against the export then reports deleted rows, rows changed since export, and a broken chain.

  Residual risk (reported plainly in every report, see LIMITS): nothing here makes owner-role deletion impossible. It makes
  it detectable AFTER the first export, for rows that were exported, provided the export itself has not been rewritten by
  someone holding ACCOUNTADMIN or the audit role. Rows deleted before they were exported are undetectable. Legacy rows
  (no ROW_HASH) are anchored by existence only.

Phase 14 adds three things (all pure):
  * `export_protection_status` — one honest answer to "is the audit export provisioned, current and externally copied?", for the Decision
    archive and the readiness page. It never says the ledger is immutable.
  * `worm_package` / `verify_package` / `verify_package_sequence` — an export segment prepared for an EXTERNAL write-once store: an NDJSON body
    plus a detached manifest (body SHA-256, chain head, the previous package's head), so segments chain from one to the next and can be
    verified offline, by someone who never touches Snowflake.
  * `WORM_REQUIREMENTS` / `RESIDUAL_RISK` — what the external store must provide, and the risk that remains without it.
Nothing here writes to a store. Writing a package to a place the ledger owner cannot rewrite is a PRODUCTION REQUIREMENT; the local-directory
sink in scripts/audit_ledger.py is a simulation and says so.

Pure functions over rows fetched by the caller (`execute(sql) -> list[dict]`): no Snowflake import, no side effects.
Nothing here ever issues UPDATE / DELETE / TRUNCATE / DROP.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from skills.ledger import INTEGRITY_VIEW, LEDGER_TABLE, missing_provenance, ts_sql

EXPORT_FORMAT = "fiu-ledger-audit/1"
GENESIS = "0" * 64
AUDIT_TABLE = "FIU_COPILOT.AUDIT.LEDGER_EXPORT"

INTACT, TAMPERED, LEGACY, UNKNOWN = "INTACT", "TAMPERED", "LEGACY_UNHASHED", "UNKNOWN"
VERDICT_COMPROMISED, VERDICT_ATTENTION, VERDICT_CONSISTENT = "COMPROMISED", "ATTENTION", "CONSISTENT"

LIMITS = (
    "Per-row hashes detect an edited row; they cannot show that a row was deleted.",
    "Deletion is detectable only against an audit export taken earlier, and only for rows that were already exported — a row "
    "deleted before the first export that included it is undetectable.",
    "A holder of the ledger-owner role together with the audit role (or ACCOUNTADMIN) can alter the ledger and the export "
    "together. The export is a witness that raises the cost of tampering; it does not make owner-role deletion impossible.",
    "Legacy rows (written before ROW_HASH existed) carry no content hash: an export proves they EXISTED, not what they said.",
)

LEDGER_ROWS_SQL = f"""SELECT d.DECISION_ID, d.ALERT_ID, d.DISPOSITION,
       {ts_sql('d.DECISION_MADE_AT')} AS DECISION_MADE_AT_UTC,
       i.STORED_HASH, i.COMPUTED_HASH, TO_JSON(d.METADATA_JSON) AS META_TEXT
FROM {LEDGER_TABLE} d
LEFT JOIN {INTEGRITY_VIEW} i ON i.DECISION_ID = d.DECISION_ID
ORDER BY d.DECISION_MADE_AT, d.DECISION_ID"""

ANCHOR_SQL = f"""SELECT SEQ, EXPORT_ID, DECISION_ID, ALERT_ID, DISPOSITION, DECISION_MADE_AT_UTC, ROW_HASH, CONTENT_ANCHORED,
       PREV_CHAIN_HASH, CHAIN_HASH, TO_VARCHAR(EXPORTED_AT) AS EXPORTED_AT
FROM {AUDIT_TABLE} ORDER BY SEQ"""


# ── classification ───────────────────────────────────────────────────────────
def classify_row(row: dict) -> dict:
    """Integrity + provenance state of one ledger row, derived from the stored and recomputed hashes (not from a label)."""
    stored, computed = row.get("STORED_HASH"), row.get("COMPUTED_HASH")
    if not stored:
        integrity = LEGACY
    elif not computed:
        integrity = UNKNOWN
    else:
        integrity = INTACT if stored == computed else TAMPERED
    meta = row.get("META_TEXT")
    if integrity == LEGACY:
        provenance_missing = None                      # legacy rows predate provenance: not expected, not reported as missing
    else:
        try:
            parsed = json.loads(meta) if isinstance(meta, str) else meta
        except ValueError:
            parsed = None
        provenance_missing = missing_provenance(parsed)
    return {"decision_id": row.get("DECISION_ID"), "integrity": integrity, "provenance_missing": provenance_missing}


# ── hash chain / export ──────────────────────────────────────────────────────
def chain_hash(prev: str, seq: int, decision_id: str, row_hash: str | None, made_at: str | None) -> str:
    material = f"{prev}|{seq}|{decision_id}|{row_hash or LEGACY}|{made_at or ''}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def export_records(rows: list[dict], previous: dict | None = None) -> list[dict]:
    """Export records for ledger rows NOT already in `previous` (the last stored record, or None for the first export).
    Incremental: each segment chains from the previous head, so the whole export is one verifiable chain."""
    prev_hash = (previous or {}).get("CHAIN_HASH") or GENESIS
    seq = int((previous or {}).get("SEQ") or 0)
    out = []
    for r in rows:
        seq += 1
        row_hash = r.get("STORED_HASH") or None
        made_at = r.get("DECISION_MADE_AT_UTC")
        h = chain_hash(prev_hash, seq, r["DECISION_ID"], row_hash, made_at)
        out.append({"SEQ": seq, "DECISION_ID": r["DECISION_ID"], "ALERT_ID": r.get("ALERT_ID"), "DISPOSITION": r.get("DISPOSITION"),
                    "DECISION_MADE_AT_UTC": made_at, "ROW_HASH": row_hash, "CONTENT_ANCHORED": bool(row_hash),
                    "PREV_CHAIN_HASH": prev_hash, "CHAIN_HASH": h})
        prev_hash = h
    return out


def verify_chain(records: list[dict]) -> list[str]:
    """Problems in an export chain (empty = the chain is internally consistent from genesis)."""
    errors, prev, expect = [], GENESIS, 1
    for rec in sorted(records, key=lambda r: int(r["SEQ"])):
        seq = int(rec["SEQ"])
        if seq != expect:
            errors.append(f"sequence gap before SEQ {seq} (expected {expect}) — an export record is missing")
            expect = seq
        if rec.get("PREV_CHAIN_HASH") != prev:
            errors.append(f"SEQ {seq}: does not chain from the previous record")
        if rec.get("CHAIN_HASH") != chain_hash(rec.get("PREV_CHAIN_HASH") or "", seq, rec["DECISION_ID"], rec.get("ROW_HASH"), rec.get("DECISION_MADE_AT_UTC")):
            errors.append(f"SEQ {seq}: record content does not match its chain hash — the export was altered")
        prev, expect = rec.get("CHAIN_HASH"), seq + 1
    return errors


def build_manifest(records: list[dict], *, exported_by: str | None = None, exported_at: str | None = None) -> dict:
    return {
        "format": EXPORT_FORMAT, "exported_at": exported_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "exported_by": exported_by, "count": len(records),
        "first_seq": records[0]["SEQ"] if records else None, "last_seq": records[-1]["SEQ"] if records else None,
        "head_chain_hash": records[-1]["CHAIN_HASH"] if records else None,
        "content_anchored": sum(1 for r in records if r["CONTENT_ANCHORED"]), "existence_only": sum(1 for r in records if not r["CONTENT_ANCHORED"]),
    }


def to_ndjson(records: list[dict], manifest: dict) -> str:
    """A self-describing, append-only text export: one manifest line, then one record per line."""
    return "\n".join([json.dumps({"manifest": manifest}, sort_keys=True)] + [json.dumps(r, sort_keys=True) for r in records]) + "\n"


def export_insert_sql(records: list[dict], export_id: str, lit: Callable[[Any], str]) -> list[str]:
    """INSERT statements (one per record) for AUDIT_TABLE. `lit` renders a value as a safe Snowflake literal."""
    cols = "SEQ, EXPORT_ID, DECISION_ID, ALERT_ID, DISPOSITION, DECISION_MADE_AT_UTC, ROW_HASH, CONTENT_ANCHORED, PREV_CHAIN_HASH, CHAIN_HASH"
    stmts = []
    for r in records:
        vals = ", ".join([str(int(r["SEQ"])), lit(export_id), lit(r["DECISION_ID"]), lit(r["ALERT_ID"]), lit(r["DISPOSITION"]),
                          lit(r["DECISION_MADE_AT_UTC"]), "NULL" if not r["ROW_HASH"] else lit(r["ROW_HASH"]),
                          "TRUE" if r["CONTENT_ANCHORED"] else "FALSE", lit(r["PREV_CHAIN_HASH"]), lit(r["CHAIN_HASH"])])
        stmts.append(f"INSERT INTO {AUDIT_TABLE} ({cols}) VALUES ({vals})")
    return stmts


# ── concurrent decisions ─────────────────────────────────────────────────────
def find_concurrent_decisions(rows: list[dict]) -> list[dict]:
    """Decisions on ONE alert that were written against the same earlier state: [{alert_id, prior_count, decision_ids}], one entry per such group.

    Each row written by the recorder carries `decision_sequence.prior_count`, the number of decisions the ledger already held for the alert when it was
    written. Two rows of one alert with the same count did not know about each other: they were submitted at the same time. The ledger cannot prevent
    that (an INSERT-only role, no uniqueness to enforce), so it is DETECTED here. Rows written before this field existed are not grouped: a legacy ledger
    full of repeat decisions is not a race."""
    groups: dict[tuple[str, int], list[str]] = {}
    for r in rows:
        meta = r.get("META_TEXT")
        try:
            parsed = json.loads(meta) if isinstance(meta, str) else meta
        except ValueError:
            continue
        seq = parsed.get("decision_sequence") if isinstance(parsed, dict) else None
        count = seq.get("prior_count") if isinstance(seq, dict) else None
        if isinstance(count, int) and not isinstance(count, bool) and r.get("ALERT_ID") and r.get("DECISION_ID"):
            groups.setdefault((str(r["ALERT_ID"]), count), []).append(str(r["DECISION_ID"]))
    return [{"alert_id": a, "prior_count": c, "decision_ids": ids} for (a, c), ids in sorted(groups.items()) if len(ids) > 1]


# ── reconciliation ───────────────────────────────────────────────────────────
def reconcile(rows: list[dict], anchor: list[dict] | None = None, *, anchor_error: str | None = None) -> dict:
    """Non-destructive integrity report for the live ledger, optionally against the audit export.

    Findings (code → meaning): TAMPERED_ROW · LEGACY_UNHASHED_ROWS · PROVENANCE_INCOMPLETE · CONCURRENT_DECISIONS (detected, not preventable) · EXPORT_CHAIN_BROKEN ·
    DELETED_RECORD (exported, now absent) · MODIFIED_SINCE_EXPORT (hash differs from the exported one) ·
    EXPORT_FIELDS_DIFFER (the export's alert id / disposition differs from the live row) · NOT_YET_EXPORTED (rows newer than the last export). Verdict: COMPROMISED (tamper / deletion / broken or altered export) >
    ATTENTION (legacy rows, incomplete provenance, rows awaiting export) > CONSISTENT."""
    classes = [classify_row(r) for r in rows]
    by_integrity: dict[str, int] = {}
    for c in classes:
        by_integrity[c["integrity"]] = by_integrity.get(c["integrity"], 0) + 1
    tampered = [c["decision_id"] for c in classes if c["integrity"] == TAMPERED]
    unknown = [c["decision_id"] for c in classes if c["integrity"] == UNKNOWN]
    incomplete = [{"decision_id": c["decision_id"], "missing": c["provenance_missing"]} for c in classes if c["provenance_missing"]]
    findings: list[dict] = []

    def add(code: str, severity: str, ids: list, detail: str):
        if ids:
            findings.append({"code": code, "severity": severity, "count": len(ids), "ids": [i if isinstance(i, str) else i.get("decision_id") for i in ids][:50], "detail": detail})

    add("TAMPERED_ROW", "COMPROMISED", tampered, "stored ROW_HASH does not match the row — edited after it was written")
    add("HASH_NOT_COMPUTABLE", "ATTENTION", unknown, "the integrity view returned no recomputed hash for these rows")
    add("LEGACY_UNHASHED_ROWS", "ATTENTION", [c["decision_id"] for c in classes if c["integrity"] == LEGACY],
        "rows predate ROW_HASH: content cannot be verified (an export can still prove they existed)")
    add("PROVENANCE_INCOMPLETE", "ATTENTION", incomplete, "rows written with ROW_HASH but missing required provenance fields")
    concurrent = find_concurrent_decisions(rows)
    add("CONCURRENT_DECISIONS", "ATTENTION", [i for g in concurrent for i in g["decision_ids"]],
        "two or more decisions on one alert were written against the same earlier state (" + ", ".join(f"{g['alert_id']}: {len(g['decision_ids'])}" for g in concurrent[:5]) +
        "): they were submitted at the same time, which the ledger cannot prevent; both rows are kept and the officers should reconcile them")

    anchor_info = {"present": False, "records": 0, "chain_valid": None, "head": None, "reason": anchor_error or "no audit export available"}
    deleted, modified, not_exported = [], [], []
    if anchor is not None:                      # [] = the export exists but is empty: present, covers nothing yet
        chain_errors = verify_chain(anchor)
        anchor_info = {"present": True, "records": len(anchor), "chain_valid": not chain_errors,
                       "head": sorted(anchor, key=lambda r: int(r["SEQ"]))[-1]["CHAIN_HASH"] if anchor else None, "reason": None,
                       "last_exported_at": max((str(r.get("EXPORTED_AT")) for r in anchor if r.get("EXPORTED_AT")), default=None)}
        if chain_errors:
            findings.append({"code": "EXPORT_CHAIN_BROKEN", "severity": "COMPROMISED", "count": len(chain_errors), "ids": [], "detail": "; ".join(chain_errors[:3])})
        live = {r["DECISION_ID"]: r for r in rows}
        for rec in anchor:
            cur = live.get(rec["DECISION_ID"])
            if cur is None:
                deleted.append(rec["DECISION_ID"])
            elif rec.get("ROW_HASH") and (cur.get("STORED_HASH") != rec["ROW_HASH"] or cur.get("COMPUTED_HASH") != rec["ROW_HASH"]):
                modified.append(rec["DECISION_ID"])
        exported = {rec["DECISION_ID"] for rec in anchor}
        not_exported = [r["DECISION_ID"] for r in rows if r["DECISION_ID"] not in exported]
        # The chain commits to (decision id, row hash, time). ALERT_ID and DISPOSITION in an export record are convenience copies: the row hash
        # commits to them in the LEDGER, so the live row is authoritative and a different copy in the export is an incident either way.
        field_diff = [rec["DECISION_ID"] for rec in anchor if rec["DECISION_ID"] in live and any(
            rec.get(k) is not None and str(rec.get(k)) != str(live[rec["DECISION_ID"]].get(k)) for k in ("ALERT_ID", "DISPOSITION"))]
        add("EXPORT_FIELDS_DIFFER", "COMPROMISED", field_diff, "the export's alert id or disposition differs from the live ledger row (the chain does not cover those two copies)")
        add("DELETED_RECORD", "COMPROMISED", deleted, "exported earlier, now absent from DECISION_LEDGER")
        add("MODIFIED_SINCE_EXPORT", "COMPROMISED", modified, "the row's hash differs from the one in the audit export (even if the row looks INTACT)")
        add("NOT_YET_EXPORTED", "ATTENTION", not_exported, "newer than the last audit export — not yet covered against deletion")

    if any(f["severity"] == "COMPROMISED" for f in findings):
        verdict = VERDICT_COMPROMISED
    elif findings:
        verdict = VERDICT_ATTENTION
    else:
        verdict = VERDICT_CONSISTENT
    return {
        "ledger_rows": len(rows), "by_integrity": by_integrity, "findings": findings, "verdict": verdict,
        "anchor": anchor_info,
        "deletion_detectable": bool(anchor_info["present"] and anchor_info["chain_valid"]),
        "tampered_ids": tampered, "deleted_ids": deleted, "modified_since_export_ids": modified, "not_yet_exported_ids": not_exported,
        "provenance_incomplete": incomplete,
        "chain_heads": [r["CHAIN_HASH"] for r in sorted(anchor or [], key=lambda r: int(r["SEQ"]))][-10000:],
        "limits": list(LIMITS),
    }


# ── fetch helpers (the caller supplies `execute(sql) -> list[dict]`) ─────────
def fetch_ledger_rows(execute: Callable[[str], list[dict]]) -> list[dict]:
    return execute(LEDGER_ROWS_SQL)


def fetch_anchor(execute: Callable[[str], list[dict]]) -> tuple[list[dict] | None, str | None]:
    """(records, None) — or (None, reason) when the audit table does not exist / is not readable (reported, never hidden)."""
    try:
        return execute(ANCHOR_SQL), None
    except Exception as err:  # noqa: BLE001 - the reason is surfaced in the report; the audit table is opt-in
        msg = " ".join(str(err).split())
        if "does not exist" in msg or "not authorized" in msg or "Insufficient privileges" in msg:
            return None, "audit export table not available (not provisioned, or not readable by this role)"
        return None, "audit export table could not be read" + (f": {msg[:80]}" if msg else "")


# ── export protection status (what the Decision archive and the readiness page show) ──────────────────────
RESIDUAL_RISK = ("Without an independent write-once copy of the audit export, a holder of the ledger-owner role (or ACCOUNTADMIN) can delete ledger "
                 "rows that were never exported, and — if they also hold the audit role — can rewrite the in-Snowflake export to match. The Snowflake "
                 "ledger on its own is append-only for the application role, not immutable.")
WORM_REQUIREMENTS = (
    "An object store with write-once retention in COMPLIANCE mode (for example S3 Object Lock, Azure immutable blob storage, GCS retention lock), so no principal — including the account owner — can shorten the retention or delete before it expires.",
    "A retention period at least as long as the institution's record-retention obligation (set by the institution's policy; the corpus's retention rules are not independently verified).",
    "A different cloud account or tenant from the one holding the ledger, with credentials that Snowflake administrators do not hold.",
    "A write-only identity for the exporter (create, no overwrite, no delete) and a separate read identity for the verifier.",
    "Versioning enabled and delete protection (MFA-delete or equivalent) so an overwrite is itself a retained, visible event.",
    "Independent monitoring: an alert if an export is late, a chain head does not advance, or the object store's retention configuration changes.",
    "A scheduled restore-and-verify drill: fetch the packages, run verify_package_sequence, and reconcile against the live ledger.",
)
PACKAGE_FORMAT = "fiu-ledger-audit-package/1"

_TS = re.compile(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})(?:\.\d+)?\s*(Z|[+-]\d{2}:?\d{2})?")


def _parse_ts(value) -> datetime | None:
    """A Snowflake TO_VARCHAR(TIMESTAMP_TZ) string ('2026-10-02 10:05:23.000 -0700') or an ISO string → an aware datetime, else None."""
    m = _TS.search(str(value or ""))
    if not m:
        return None
    zone = m.group(3)
    offset = timezone.utc if zone in (None, "Z") else timezone(timedelta(hours=int(zone[:3]), minutes=(1 if zone[0] != "-" else -1) * int(zone[-2:])))
    try:
        return datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}").replace(tzinfo=offset)
    except ValueError:
        return None


STATUS_NOT_PROVISIONED, STATUS_CHAIN_BROKEN, STATUS_BEHIND, STATUS_CURRENT = "NOT_PROVISIONED", "CHAIN_BROKEN", "BEHIND", "CURRENT"
EXTERNAL_NOT_ATTESTED, EXTERNAL_MATCHES, EXTERNAL_BEHIND, EXTERNAL_MISMATCH = "NOT_ATTESTED", "ATTESTED_MATCHES_HEAD", "ATTESTED_BEHIND", "ATTESTED_MISMATCH"


def export_protection_status(report: dict, *, attestation: dict | None = None, max_age_hours: int = 24, now: datetime | None = None) -> dict:
    """Is audit-export protection provisioned and current — and is there an independent external copy? Derived from a `reconcile()` report only.

    level  NOT_PROVISIONED · CHAIN_BROKEN · BEHIND · CURRENT       (CURRENT means every ledger row is in a valid hash chain; it never means immutable)
    external  NOT_ATTESTED (the default: this application cannot see outside Snowflake) · ATTESTED_* when a self-reported attestation of the
              external copy's chain head is supplied and compared with the in-Snowflake head. An attestation is a CLAIM about another system.
    Always returns the residual-risk statement and `immutable_claim: False`."""
    anchor = report.get("anchor") or {}
    pending = len(report.get("not_yet_exported_ids") or [])
    rows = int(report.get("ledger_rows") or 0)
    if not anchor.get("present"):
        level, headline = STATUS_NOT_PROVISIONED, "Audit export protection is not provisioned."
        detail = f"No audit export exists ({anchor.get('reason') or 'not available'}). Deletion of ledger rows by the owner role would not be detected."
    elif not anchor.get("chain_valid"):
        level, headline = STATUS_CHAIN_BROKEN, "The audit export chain is broken."
        detail = "The export no longer verifies from its first record. Treat the ledger and the export as compromised until explained."
    elif pending:
        level, headline = STATUS_BEHIND, f"Audit export is behind by {pending} ledger row(s)."
        detail = f"{pending} of {rows} ledger row(s) are not yet in the export, so deleting those rows would not be detected."
    else:
        level, headline = STATUS_CURRENT, "Audit export is current."
        detail = (f"All {rows} ledger row(s) are in a valid hash chain ({anchor.get('records')} record(s)). Deletion of exported rows is detectable. "
                  "This is a witness, not write-once storage.")
    age_h = None
    ts = _parse_ts(anchor.get("last_exported_at"))
    if ts is not None and now is not None:
        age_h = round(((now if now.tzinfo else now.replace(tzinfo=timezone.utc)) - ts).total_seconds() / 3600, 1)
    stale = level == STATUS_BEHIND and age_h is not None and age_h > max_age_hours
    external, ext_detail = EXTERNAL_NOT_ATTESTED, ("No independent write-once copy has been attested. This application cannot see outside Snowflake, so it does not "
                                                    "claim that one exists.")
    if isinstance(attestation, dict) and attestation.get("head_chain_hash"):
        head = str(attestation["head_chain_hash"])
        known = {str(r) for r in (report.get("chain_heads") or [])} | ({anchor.get("head")} if anchor.get("head") else set())
        if anchor.get("head") and head == anchor["head"]:
            external, ext_detail = EXTERNAL_MATCHES, "A self-reported external copy matches the current chain head. It is a claim about another system; it was not checked from here."
        elif head in known:
            external, ext_detail = EXTERNAL_BEHIND, "A self-reported external copy holds an earlier chain head; newer export records are not yet copied."
        else:
            external, ext_detail = EXTERNAL_MISMATCH, "The self-reported external chain head does not appear in the in-Snowflake export. Treat as an integrity incident until explained."
    return {"level": level, "headline": headline, "detail": detail, "provisioned": bool(anchor.get("present")), "current": level == STATUS_CURRENT,
            "pending_rows": pending, "ledger_rows": rows, "last_exported_age_hours": age_h, "behind_schedule": stale,
            "external": external, "external_detail": ext_detail, "residual_risk": RESIDUAL_RISK, "immutable_claim": False,
            "worm_requirements": list(WORM_REQUIREMENTS)}


# ── packages for an external write-once store ────────────────────────────────
def worm_package(records: list[dict], manifest: dict, *, export_id: str = "export") -> dict:
    """An export segment prepared for an external write-once store: {object_key, ndjson, manifest_object_key, manifest}. Nothing is written here.

    The detached manifest holds the SHA-256 of the NDJSON body, the first record's PREV_CHAIN_HASH (the previous package's head — the link) and
    the last record's CHAIN_HASH (this package's head), so a verifier holding only the packages can check each body and the links between them."""
    if not records:
        raise ValueError("an empty export segment is not packaged")
    body = to_ndjson(records, manifest)
    first, last = records[0], records[-1]
    safe_id = "".join(ch for ch in str(export_id) if ch.isalnum() or ch in "-_")[:64] or "export"
    stem = f"fiu-ledger-audit/{safe_id}-{int(first['SEQ']):08d}-{int(last['SEQ']):08d}"
    man = {"format": PACKAGE_FORMAT, "ndjson_object": stem + ".ndjson", "ndjson_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
           "first_seq": int(first["SEQ"]), "last_seq": int(last["SEQ"]), "count": len(records), "prev_head": first["PREV_CHAIN_HASH"], "head": last["CHAIN_HASH"],
           "content_anchored": sum(1 for r in records if r["CONTENT_ANCHORED"]), "existence_only": sum(1 for r in records if not r["CONTENT_ANCHORED"]),
           "created_at": manifest.get("exported_at"), "exported_by": manifest.get("exported_by"),
           "write_once_requirements": list(WORM_REQUIREMENTS), "immutable_claim": False}
    return {"object_key": stem + ".ndjson", "ndjson": body, "manifest_object_key": stem + ".manifest.json",
            "manifest": man, "manifest_json": json.dumps(man, sort_keys=True, indent=2) + "\n"}


def parse_ndjson(text: str) -> tuple[dict | None, list[dict], list[str]]:
    """(manifest line, records, problems) from an NDJSON export body."""
    manifest, records, problems = None, [], []
    for n, line in enumerate((text or "").splitlines(), 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            problems.append(f"line {n} is not valid JSON")
            continue
        if isinstance(obj, dict) and "manifest" in obj and manifest is None and not records:
            manifest = obj["manifest"]
        elif isinstance(obj, dict) and "SEQ" in obj:
            records.append(obj)
        else:
            problems.append(f"line {n} is neither the manifest nor an export record")
    return manifest, records, problems


def verify_package(ndjson_text: str, manifest_json: str | dict, *, expected_prev_head: str | None = None) -> dict:
    """Verify ONE package offline: body hash, manifest-versus-records agreement, the hash chain inside it, and (optionally) its link to the
    previous package's head. Returns {ok, problems[], head, prev_head, first_seq, last_seq, count}."""
    problems: list[str] = []
    try:
        man = json.loads(manifest_json) if isinstance(manifest_json, str) else dict(manifest_json)
    except (ValueError, TypeError):
        return {"ok": False, "problems": ["the manifest is not valid JSON"], "head": None, "prev_head": None, "first_seq": None, "last_seq": None, "count": 0}
    if man.get("format") != PACKAGE_FORMAT:
        problems.append(f"unknown package format {man.get('format')!r}")
    if hashlib.sha256((ndjson_text or "").encode("utf-8")).hexdigest() != man.get("ndjson_sha256"):
        problems.append("the NDJSON body does not match the SHA-256 in the manifest — the body was altered or truncated")
    head_line, records, parse_problems = parse_ndjson(ndjson_text)
    problems += parse_problems
    if head_line is None:
        problems.append("the body has no manifest line")
    elif head_line.get("format") != EXPORT_FORMAT:
        problems.append(f"the body's own manifest has an unknown format {head_line.get('format')!r}")
    records.sort(key=lambda r: int(r["SEQ"]))
    if int(man.get("count") or -1) != len(records):
        problems.append(f"the manifest says {man.get('count')} record(s); the body holds {len(records)}")
    if records:
        if int(man.get("first_seq") or -1) != int(records[0]["SEQ"]) or int(man.get("last_seq") or -1) != int(records[-1]["SEQ"]):
            problems.append("the manifest's sequence range does not match the records")
        if man.get("head") != records[-1].get("CHAIN_HASH"):
            problems.append("the manifest's head is not the last record's chain hash")
        if man.get("prev_head") != records[0].get("PREV_CHAIN_HASH"):
            problems.append("the manifest's previous head is not the first record's PREV_CHAIN_HASH")
        # inside a package the chain is checked link by link; the FIRST record is checked against the declared previous head
        prev, expect = records[0]["PREV_CHAIN_HASH"], int(records[0]["SEQ"])
        for rec in records:
            seq = int(rec["SEQ"])
            if seq != expect:
                problems.append(f"sequence gap before SEQ {seq} (expected {expect})")
                expect = seq
            if rec.get("PREV_CHAIN_HASH") != prev:
                problems.append(f"SEQ {seq}: does not chain from the previous record")
            if rec.get("CHAIN_HASH") != chain_hash(rec.get("PREV_CHAIN_HASH") or "", seq, rec["DECISION_ID"], rec.get("ROW_HASH"), rec.get("DECISION_MADE_AT_UTC")):
                problems.append(f"SEQ {seq}: record content does not match its chain hash — altered")
            prev, expect = rec.get("CHAIN_HASH"), seq + 1
    if expected_prev_head is not None and man.get("prev_head") != expected_prev_head:
        problems.append("this package does not chain from the previous package's head")
    return {"ok": not problems, "problems": problems[:20], "head": man.get("head"), "prev_head": man.get("prev_head"),
            "first_seq": man.get("first_seq"), "last_seq": man.get("last_seq"), "count": len(records)}


def verify_package_sequence(packages: list[tuple[str, str | dict]]) -> dict:
    """Verify an ordered list of (ndjson_text, manifest) packages end to end: each verifies, the first starts at genesis, each starts where the
    previous ended, and sequence numbers are contiguous. This is the check an external auditor runs on the write-once store."""
    problems, prev_head, expect_seq, results = [], GENESIS, 1, []
    for i, (body, man) in enumerate(packages, 1):
        r = verify_package(body, man, expected_prev_head=prev_head)
        results.append(r)
        problems += [f"package {i}: {p}" for p in r["problems"]]
        if r["first_seq"] is not None and int(r["first_seq"]) != expect_seq:
            problems.append(f"package {i}: starts at SEQ {r['first_seq']}, expected {expect_seq} — a package is missing or repeated")
        if r["head"]:
            prev_head, expect_seq = r["head"], int(r["last_seq"]) + 1
    return {"ok": not problems, "problems": problems[:30], "packages": len(packages), "head": prev_head if packages else None,
            "last_seq": expect_seq - 1 if packages else 0, "results": results}
