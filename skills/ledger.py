"""
DECISION_LEDGER logic that must be identical in Python and in SQL:

  * the row-hash expression (single definition, embedded in the INSERT *and* in the
    DECISION_LEDGER_INTEGRITY_V view in domain/corpus/export/ddl/regulatory_corpus.sql —
    tests/test_ledger.py fails if the two ever diverge, and the live test proves the hash
    recomputed from the STORED row equals the hash written at insert time)
  * working-day SLA arithmetic (shared by the recorder and the UI)
  * the override rule (when a PO decision needs a recorded reason)
  * the provenance metadata schema required to reconstruct a decision

Pure Python + SQL text; no Snowflake calls here.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

IST = timezone(timedelta(hours=5, minutes=30))
SLA_WORKING_DAYS = 7
PROVENANCE_SCHEMA_VERSION = "3"

# ── row hash (SQL) ───────────────────────────────────────────────────────────
_TS_FMT = "'YYYY-MM-DD\"T\"HH24:MI:SS.FF6'"


def _ts(col: str) -> str:
    return f"TO_VARCHAR(CONVERT_TIMEZONE('UTC', {col}), {_TS_FMT})"


ts_sql = _ts      # public alias: the one UTC timestamp rendering shared by the row hash and the audit export


# Every column that constitutes the decision record, in canonical order. CREATED_AT (a
# server default) and ROW_HASH itself are deliberately excluded.
HASH_EXPR = (
    "SHA2(TO_JSON(OBJECT_CONSTRUCT_KEEP_NULL("
    "'decision_id', DECISION_ID, "
    "'alert_id', ALERT_ID, "
    "'customer_ref', CUSTOMER_REF, "
    "'disposition', DISPOSITION, "
    "'decision_maker_id', DECISION_MAKER_ID, "
    f"'suspicion_formed_at', {_ts('SUSPICION_FORMED_AT')}, "
    f"'decision_made_at', {_ts('DECISION_MADE_AT')}, "
    "'sla_days_remaining', SLA_DAYS_REMAINING, "
    "'rationale_text', RATIONALE_TEXT, "
    "'rules_cited', RULES_CITED, "
    "'poe_factors_assessed', POE_FACTORS_ASSESSED, "
    "'rfi_triggers', RFI_TRIGGERS, "
    "'str_reference', STR_REFERENCE, "
    "'metadata', METADATA_JSON)), 256)"
)

LEDGER_TABLE = "FIU_COPILOT.AML.DECISION_LEDGER"
INTEGRITY_VIEW = "FIU_COPILOT.AML.DECISION_LEDGER_INTEGRITY_V"

INTEGRITY_VIEW_SQL = f"""CREATE OR REPLACE VIEW DECISION_LEDGER_INTEGRITY_V AS
SELECT
    DECISION_ID, ALERT_ID, DISPOSITION, DECISION_MADE_AT,
    ROW_HASH AS STORED_HASH,
    COMPUTED_HASH,
    IFF(ROW_HASH IS NULL, 'LEGACY_UNHASHED',
        IFF(ROW_HASH = COMPUTED_HASH, 'INTACT', 'TAMPERED')) AS INTEGRITY_STATUS
FROM (
    SELECT *, {HASH_EXPR} AS COMPUTED_HASH
    FROM DECISION_LEDGER
)"""


class LedgerBlocked(ValueError):
    """The decision may not be recorded (validation / evidence gate). Nothing was written."""


class LedgerWriteError(RuntimeError):
    """The database write or its integrity check failed. Nothing was committed."""


# ── SLA (7 working days, Mon–Fri, no holiday calendar) ───────────────────────
def to_ist_date(value: Any) -> date:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(IST).date()
    if isinstance(value, date):
        return value
    text = str(value).strip().replace("Z", "+00:00")
    try:
        return to_ist_date(datetime.fromisoformat(text))
    except ValueError:
        return date.fromisoformat(text[:10])


def working_days_elapsed(start: Any, end: Any) -> int:
    """Mon–Fri days in (start, end]. Negative span → 0."""
    d, stop, n = to_ist_date(start), to_ist_date(end), 0
    while d < stop:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def sla_days_remaining(formed_at: Any, decided_at: Any) -> int:
    """Working days left of the 7-WD STR window at decision time (negative = overdue)."""
    return SLA_WORKING_DAYS - working_days_elapsed(formed_at, decided_at)


# ── override rule ────────────────────────────────────────────────────────────
MIN_OVERRIDE_REASON_CHARS = 20


def is_override(ai_recommendation: str | None, disposition: str) -> bool:
    """A PO decision is an override when it contradicts a definite AI recommendation, or
    files where the AI could not support filing. REVIEW / DEFERRED are never overrides."""
    ai = (ai_recommendation or "").upper()
    if disposition == "DEFERRED":
        return False
    if ai == "FILE":
        return disposition == "NOT_FILE"
    if ai == "NOT_FILE":
        return disposition in ("FILE", "ESCALATE")
    if ai in ("INSUFFICIENT_EVIDENCE", "NEEDS_MANUAL_REVIEW"):
        return disposition == "FILE"
    return False


# ── evidence + text fingerprints ─────────────────────────────────────────────
def evidence_snapshot_sha256(transactions: list[dict] | None) -> str:
    """Fingerprint of the exact transaction evidence a decision was made on."""
    rows = sorted(
        (
            {
                "txn_id": t.get("txn_id"),
                "date": str(t.get("date")),
                "type": t.get("type"),
                "amount_inr": round(float(t.get("amount_inr") or 0), 2),
                "channel": t.get("channel"),
                "counterparty": t.get("counterparty"),
                "is_flagged": bool(t.get("is_flagged")),
            }
            for t in (transactions or [])
        ),
        key=lambda r: str(r["txn_id"]),
    )
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def text_sha256(text: str | None) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


# ── provenance metadata (METADATA_JSON) ──────────────────────────────────────
# Every key must be present on every row written by the recorder. A value of None is
# only legitimate for the two conditional fields below.
_V2_KEYS = (
    "schema_version", "ai_recommendation", "human_decision", "override", "corpus_version",
    "regulatory_basis", "model_name", "prompt_version", "skill_version", "evidence_txn_ids",
    "evidence_snapshot_sha256", "poe_assessment", "gos", "written_by_role",
)
# v3 (2026-10-01): the regulatory basis is an object (skills.governance.build_regulatory_basis) and the deterministic
# defensibility gate result + the PO's acknowledgements are persisted with the decision.
# Phase 14 (2026-10-03): the INSERT also stamps `written_by_user` (CURRENT_USER()) beside `written_by_role`, and the recorder may add the optional
# objects `evidence_quality`, `decision_identity` and `feedback` (see build_provenance). None is a required key, so no row becomes incomplete.
# v4 (2026-10-02): the independent-review protocol adds a `human_review` object (skills.human_review). It is version-scoped
# and OPT-IN — a row carries it (and declares v4) only when the recorder is given one; otherwise the row is v3 exactly as
# before. Each row is judged for completeness against the key set of the version IT declares (missing_provenance), so older
# rows stay complete and the existing ROW_HASH (over the whole METADATA_JSON) covers the new key with no hash change.
_V3_KEYS = _V2_KEYS + ("defensibility_gate", "acknowledgements")
PROVENANCE_SCHEMA_VERSION_WITH_REVIEW = "4"
REQUIRED_PROVENANCE_KEYS_BY_VERSION = {
    "2": _V2_KEYS,
    "3": _V3_KEYS,
    "4": _V3_KEYS + ("human_review",),
}
REQUIRED_PROVENANCE_KEYS = REQUIRED_PROVENANCE_KEYS_BY_VERSION[PROVENANCE_SCHEMA_VERSION]
CONDITIONAL_NULLABLE = ("override_reason", "unverified_claims_acknowledged")


DESK_SESSION_BASIS = ("Browser session of the Principal Officer, from the first time this case was opened on the Investigation desk to the click that recorded the "
                      "decision. It includes idle time and a tab left open, excludes any work outside the application, and subtracts the time spent waiting for a model. "
                      "A proxy, not a time-and-motion study.")
_MAX_DESK_SECONDS = 7 * 24 * 3600


def clean_desk_session(raw: Any) -> dict | None:
    """The only shape of a desk-session measurement the ledger accepts: whole seconds, bounded, model waiting never larger than the session. Anything
    else (not a mapping, no numbers, negative, not finite) is dropped, so a client cannot write a malformed or absurd value into a sealed row."""
    if not isinstance(raw, dict):
        return None

    def secs(v: Any) -> int | None:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        if f != f or f in (float("inf"), float("-inf")) or f < 0:
            return None
        return int(min(round(f), _MAX_DESK_SECONDS))

    desk = secs(raw.get("desk_seconds"))
    if desk is None:
        return None
    wait = min(secs(raw.get("model_wait_seconds")) or 0, desk)
    opened = str(raw.get("opened_at_utc") or "")[:25]
    return {"opened_at_utc": opened or None, "desk_seconds": desk, "model_wait_seconds": wait, "hands_on_upper_bound_seconds": desk - wait,
            "basis": DESK_SESSION_BASIS}


def build_provenance(
    *,
    disposition: str,
    ai_recommendation: str | None,
    override_reason: str | None,
    corpus_version: str | None,
    regulatory_basis: dict | None,
    model_name: str | None,
    prompt_version: str,
    skill_version: str,
    evidence_txn_ids: list[str] | None,
    transactions: list[dict] | None,
    poe_assessment: list[dict] | None,
    gos_narrative: str,
    gos_quality: dict | None,
    unverified_claims_acknowledged: bool | None,
    defensibility_gate: dict | None = None,
    acknowledgements: dict | None = None,
    challenge: dict | None = None,
    human_review: dict | None = None,
    evidence_quality: dict | None = None,
    decision_identity: dict | None = None,
    feedback: dict | None = None,
    supersession: dict | None = None,
    ai_output: dict | None = None,
    desk_session: dict | None = None,
    decision_sequence: dict | None = None,
    sla_basis: str = "working_days_mon_fri_no_holiday_calendar_IST",
) -> dict:
    """Everything needed to reconstruct WHY the decision was made, apart from the row itself.

    `human_review` (opt-in, skills.human_review): when supplied the row declares schema_version v4 and carries the review
    object; when None the row is v3 exactly as before. Either way it lives INSIDE this dict (METADATA_JSON), so the row hash
    covers it unchanged."""
    ai = ai_recommendation or "NOT_RUN"
    q = gos_quality or {}
    prov = {
        "schema_version":           PROVENANCE_SCHEMA_VERSION_WITH_REVIEW if human_review is not None else PROVENANCE_SCHEMA_VERSION,
        "ai_recommendation":        ai,
        "human_decision":           disposition,
        "override":                 is_override(ai_recommendation, disposition),
        "override_reason":          override_reason or None,
        "corpus_version":           corpus_version or "UNKNOWN",
        "regulatory_basis":         regulatory_basis or {},
        "model_name":               model_name or "NOT_RUN",
        "prompt_version":           prompt_version,
        "skill_version":            skill_version,
        "evidence_txn_ids":         sorted(set(evidence_txn_ids or [])),
        "evidence_snapshot_sha256": evidence_snapshot_sha256(transactions),
        "poe_assessment": [
            {
                "factor_id": f.get("factor_id"),
                "assessment": f.get("assessment"),
                "evidence": f.get("evidence"),
                "evidence_txn_ids": f.get("evidence_txn_ids") or [],
                "grounded": f.get("grounded"),
            }
            for f in (poe_assessment or []) if isinstance(f, dict)
        ],
        "gos": {
            "narrative_sha256":           text_sha256(gos_narrative),
            "status":                     q.get("status", "NOT_CHECKED"),
            "quality_score":              q.get("quality_score"),
            "hard_gate_passed":           q.get("hard_gate_passed"),
            "ai_output_valid":            q.get("ai_output_valid"),
            "unsupported_claims_by_type": q.get("unsupported_claims_by_type") or {},
            "unverified_assertions":      q.get("unverified_assertions") or [],
        },
        "unverified_claims_acknowledged": unverified_claims_acknowledged,
        "defensibility_gate":       defensibility_gate or {},
        "acknowledgements":         acknowledgements or {},
        # what argued AGAINST the decision that was made, as the recorder computed it (optional: absent on earlier rows)
        "challenge":                challenge or {},
        "sla_basis":                sla_basis,
    }
    if human_review is not None:
        prov["human_review"] = human_review
    # Optional objects (Phase 14). Like `challenge`, each is ABSENT on earlier rows and is not a required key: a row is complete without
    # it. They live inside METADATA_JSON, so the existing ROW_HASH covers them with no change to the hash expression.
    #   evidence_quality   skills.evidence_quality.stored_snapshot — codes, effects and static titles of the case record's issues
    #   decision_identity  skills.identity.stored — whether the recorded ID came from an authenticated session or was typed
    #   feedback           skills.feedback.capture — AI acceptance / rejection and the structured closure reason (monitoring only)
    #   supersession       the earlier decisions on the same alert this one follows, and the officer's reason (absent on a first decision)
    #   ai_output          present only when the AI output came from a SAVED real reply, not a live call: {source, captured_at, model}
    #   decision_sequence  {"prior_count": n}: how many decisions the ledger already held for this alert when this one was written. Two rows of one alert with
    #                      the same count were written against the same earlier state (see skills.audit.find_concurrent_decisions)
    #   desk_session       the officer's time on the desk for this decision (a browser-session proxy, see DESK_SESSION_BASIS); absent when not supplied
    for key, value in (("evidence_quality", evidence_quality), ("decision_identity", decision_identity), ("feedback", feedback), ("supersession", supersession),
                       ("ai_output", ai_output), ("desk_session", clean_desk_session(desk_session)), ("decision_sequence", decision_sequence)):
        if value is not None:
            prov[key] = value
    return prov


def missing_provenance(meta: Any) -> list[str]:
    """Required provenance keys absent (or null) in a stored METADATA_JSON. A row is judged against the key set of the
    schema_version it declares (a v2 row is complete as v2); a row declaring none, or an unknown one, against the current set."""
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except ValueError:
            return list(REQUIRED_PROVENANCE_KEYS)
    if not isinstance(meta, dict):
        return list(REQUIRED_PROVENANCE_KEYS)
    required = REQUIRED_PROVENANCE_KEYS_BY_VERSION.get(str(meta.get("schema_version")), REQUIRED_PROVENANCE_KEYS)
    return [k for k in required if meta.get(k) is None]


# ── SQL builders ─────────────────────────────────────────────────────────────
def build_insert_sql(lit, *, decision_id, alert_id, customer_ref, disposition, decision_maker_id,
                     suspicion_formed_at, decision_made_at, sla_remaining, rationale_text,
                     rules_cited, poe_factors, rfi_triggers, str_reference, metadata: dict) -> str:
    """One INSERT that stores the row AND its ROW_HASH, computed by the same SQL expression the
    integrity view uses. `lit` renders a Python value as a safe Snowflake string literal."""
    def jlit(obj) -> str:
        return f"PARSE_JSON({lit(json.dumps(obj, sort_keys=True, ensure_ascii=False))})"
    str_ref_sql = "NULL" if not str_reference else lit(str_reference)
    return f"""INSERT INTO {LEDGER_TABLE} (
    DECISION_ID, ALERT_ID, CUSTOMER_REF, DISPOSITION, DECISION_MAKER_ID,
    SUSPICION_FORMED_AT, DECISION_MADE_AT, SLA_DAYS_REMAINING, RATIONALE_TEXT,
    RULES_CITED, POE_FACTORS_ASSESSED, RFI_TRIGGERS, STR_REFERENCE, METADATA_JSON, ROW_HASH
)
SELECT
    DECISION_ID, ALERT_ID, CUSTOMER_REF, DISPOSITION, DECISION_MAKER_ID,
    SUSPICION_FORMED_AT, DECISION_MADE_AT, SLA_DAYS_REMAINING, RATIONALE_TEXT,
    RULES_CITED, POE_FACTORS_ASSESSED, RFI_TRIGGERS, STR_REFERENCE, METADATA_JSON,
    {HASH_EXPR} AS ROW_HASH
FROM (
    SELECT
        {lit(decision_id)}::VARCHAR            AS DECISION_ID,
        {lit(alert_id)}::VARCHAR               AS ALERT_ID,
        {lit(customer_ref)}::VARCHAR           AS CUSTOMER_REF,
        {lit(disposition)}::VARCHAR            AS DISPOSITION,
        {lit(decision_maker_id)}::VARCHAR      AS DECISION_MAKER_ID,
        {lit(suspicion_formed_at)}::TIMESTAMP_TZ AS SUSPICION_FORMED_AT,
        {lit(decision_made_at)}::TIMESTAMP_TZ    AS DECISION_MADE_AT,
        {int(sla_remaining)}::NUMBER           AS SLA_DAYS_REMAINING,
        {lit(rationale_text)}::VARCHAR         AS RATIONALE_TEXT,
        {jlit(rules_cited)}                    AS RULES_CITED,
        {jlit(poe_factors)}                    AS POE_FACTORS_ASSESSED,
        {jlit(rfi_triggers)}                   AS RFI_TRIGGERS,
        {str_ref_sql}::VARCHAR                 AS STR_REFERENCE,
        OBJECT_INSERT(OBJECT_INSERT({jlit(metadata)}, 'written_by_role', CURRENT_ROLE(), TRUE), 'written_by_user', CURRENT_USER(), TRUE) AS METADATA_JSON
)"""
