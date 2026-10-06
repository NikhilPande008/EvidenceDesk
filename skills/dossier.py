"""
The inspection pack: one decision, everything needed to show later what the officer saw, assumed, acknowledged and decided, as a file that can be
attached to a case-management record and checked WITHOUT the application or Snowflake.

  build(reconstruction, alert, transactions, ...)   -> the dossier (a dict; JSON-serialisable), sealed with its own SHA-256
  verify(dossier)                                   -> every check that can be replayed offline, each ok / not ok / not possible, with the reason
  render_html(dossier)                              -> a printable page of the same content (no scripts, no external resources)

What `verify` can prove from the file alone, and what it cannot:

  * the file is exactly as it was sealed (dossier_sha256);
  * the LEDGER ROW HASH: the row's columns are included in the exact form the hash is computed over, so the SHA-256 the ledger stored is recomputed here with
    the same serialisation Snowflake's TO_JSON uses (compact, keys sorted, UTF-8). A match means this file's decision row is the row the ledger sealed;
  * the stored defensibility gate is consistent with its own conditions, and the stored regulatory basis still hashes to its own digest;
  * the rationale text still hashes to the digest in the provenance, and the included transactions still hash to the evidence digest;
  * for a FILE, the deterministic evidence gate re-run on the stored rationale against the included transactions passes;
  * overrides, supersession reasons and acknowledgements are present where the gate required them.

It cannot prove that the ledger still holds this row (a deleted row leaves no trace in the file; that is what the audit export is for), nor that the
included case record is the one the officer saw (only its digest, recorded at the time, says so).

Pure Python: no model, no database, no clock of its own (the generation time is passed in).
"""

from __future__ import annotations

import hashlib
import html
import json
import math
from datetime import datetime, timezone
from typing import Any

SCHEMA = "evidencedesk.decision-dossier/1"
HASH_COLUMNS = ("decision_id", "alert_id", "customer_ref", "disposition", "decision_maker_id", "suspicion_formed_at", "decision_made_at",
                "sla_days_remaining", "rationale_text", "rules_cited", "poe_factors_assessed", "rfi_triggers", "str_reference", "metadata")
_TS = "%Y-%m-%dT%H:%M:%S.%f"


# ── the ledger's own serialisation ────────────────────────────────────────────────────────────────────────────────────────────
def sf_json(value: Any) -> str:
    """JSON text exactly as Snowflake's TO_JSON writes a VARIANT: compact, object keys sorted, non-ASCII kept as UTF-8, whole-valued numbers without a
    decimal point, strings escaped as JSON. Limit: a number with more digits than a float holds (Snowflake keeps arbitrary-precision NUMBER) cannot be
    reproduced; none occurs in the provenance the recorder writes. Checked against the live ledger (tests/test_dossier.py reads the recorded rows in evidence/)."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return "null"
        if value == int(value) and abs(value) < 1e15:
            return str(int(value))
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(sf_json(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(f"{json.dumps(str(k), ensure_ascii=False)}:{sf_json(value[k])}" for k in sorted(value, key=str)) + "}"
    return json.dumps(str(value), ensure_ascii=False)


def utc_text(ts: Any) -> str | None:
    """A timestamp in the form the row hash uses: UTC, 'YYYY-MM-DDTHH:MM:SS.ffffff'."""
    if ts is None:
        return None
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).strftime(_TS)


def row_hash_input(row: dict) -> str:
    """The exact text the ledger hashes for a row. `row` holds the HASH_COLUMNS (timestamps already in utc_text form or datetimes)."""
    obj = {k: row.get(k) for k in HASH_COLUMNS}
    obj["suspicion_formed_at"] = utc_text(obj["suspicion_formed_at"])
    obj["decision_made_at"] = utc_text(obj["decision_made_at"])
    if obj["sla_days_remaining"] is not None:
        obj["sla_days_remaining"] = int(obj["sla_days_remaining"])
    return sf_json(obj)


def row_hash(row: dict) -> str:
    return hashlib.sha256(row_hash_input(row).encode("utf-8")).hexdigest()


def _variant(value: Any) -> Any:
    """A VARIANT column as the connector returns it (a JSON string) or already parsed."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def ledger_row(decision: dict, metadata: Any) -> dict:
    """The decision row in hashable form, from reconstruct_decision()['decision'] (upper-case column keys) and its parsed provenance."""
    get = lambda k: decision.get(k.upper(), decision.get(k))  # noqa: E731
    return {
        "decision_id": get("decision_id"), "alert_id": get("alert_id"), "customer_ref": get("customer_ref"), "disposition": get("disposition"),
        "decision_maker_id": get("decision_maker_id"), "suspicion_formed_at": utc_text(get("suspicion_formed_at")), "decision_made_at": utc_text(get("decision_made_at")),
        "sla_days_remaining": None if get("sla_days_remaining") is None else int(get("sla_days_remaining")), "rationale_text": get("rationale_text"),
        "rules_cited": _variant(get("rules_cited")), "poe_factors_assessed": _variant(get("poe_factors_assessed")), "rfi_triggers": _variant(get("rfi_triggers")),
        "str_reference": get("str_reference"), "metadata": metadata,
    }


# ── build ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def seal(dossier: dict) -> str:
    body = {k: v for k, v in dossier.items() if k != "dossier_sha256"}
    return hashlib.sha256(sf_json(body).encode("utf-8")).hexdigest()


def _clean_txn(t: dict) -> dict:
    return {"txn_id": t.get("txn_id"), "date": str(t.get("date")), "type": t.get("type"), "amount_inr": round(float(t.get("amount_inr") or 0), 2),
            "channel": t.get("channel"), "counterparty": t.get("counterparty"), "is_flagged": bool(t.get("is_flagged"))}


def build(reconstruction: dict, alert: dict | None, transactions: list[dict] | None, *, generated_at: datetime, app_version: str = "") -> dict:
    """The dossier for one reconstructed decision. `reconstruction` is CoPilotSkills.reconstruct_decision()'s result."""
    if not reconstruction.get("found"):
        raise ValueError("decision not found")
    d, meta = reconstruction["decision"], reconstruction.get("provenance")
    row = ledger_row(d, meta)
    status = d.get("INTEGRITY_STATUS") or d.get("integrity_status")
    alert = alert or {}
    txns = [_clean_txn(t) for t in (transactions or [])]
    meta = meta if isinstance(meta, dict) else {}
    dossier = {
        "schema": SCHEMA,
        "notice": "Synthetic data. This file records a decision made in a prototype; it is not a regulatory filing and does not submit anything to FIU-IND.",
        "generated_at_utc": utc_text(generated_at),
        "app": {"name": "EvidenceDesk", "version": app_version or None, "prompt_version": meta.get("prompt_version"), "skill_version": meta.get("skill_version")},
        "decision": {k: row[k] for k in ("decision_id", "alert_id", "customer_ref", "disposition", "decision_maker_id", "suspicion_formed_at", "decision_made_at",
                                         "sla_days_remaining", "str_reference", "rationale_text", "rules_cited", "rfi_triggers")},
        "ledger_row": row,
        "ledger_row_hash": {"stored": d.get("ROW_HASH") or d.get("row_hash"), "status_in_ledger_at_export": status},
        "provenance": meta,
        "reconstruction_at_export": {k: {"ok": v.get("ok"), "detail": v.get("detail")} for k, v in (reconstruction.get("checks") or {}).items()},
        "case_record": {
            "alert": {k: (str(alert.get(k)) if alert.get(k) is not None else None) for k in ("ALERT_ID", "CUSTOMER_REF", "ALERT_DATE", "ALERT_TYPE", "SIGNAL_SOURCE", "ACCOUNT_TYPE",
                                                                                              "CUSTOMER_PROFILE", "ALERT_AMOUNT_INR", "ALERT_NARRATIVE")},
            "transactions": txns,
        },
        "summary": summary(row, meta),
    }
    dossier["dossier_sha256"] = seal(dossier)
    return dossier


def summary(row: dict, meta: dict) -> dict:
    """The human reading of the stored provenance: who decided what, against what the AI said, on what basis, with what acknowledged."""
    basis = meta.get("regulatory_basis") or {}
    gate = meta.get("defensibility_gate") or {}
    ack = meta.get("acknowledgements") or {}
    sup = meta.get("supersession")
    ident = meta.get("decision_identity") or {}
    ai_out = meta.get("ai_output") or {}
    return {
        "decided_by": row["decision_maker_id"], "identity_authenticated": bool(ident.get("authenticated")) if ident else None,
        "disposition": row["disposition"], "ai_said": meta.get("ai_recommendation"), "ai_model": meta.get("model_name"),
        "ai_output_source": ai_out.get("source") or ("live" if (meta.get("ai_recommendation") not in (None, "NOT_RUN")) else None),
        "overrode_ai": bool(meta.get("override")), "override_reason": meta.get("override_reason"),
        "basis": {"grade": basis.get("grade"), "corpus_version": basis.get("corpus_version"), "snapshot_date": basis.get("snapshot_date"),
                  "proven": basis.get("proven_rule_ids") or [], "assumed": basis.get("assumed_rule_ids") or [],
                  "independently_verified": basis.get("independently_verified_count")},
        "gate": {"status": gate.get("status"), "blocking": gate.get("blocking_codes") or [], "warnings": gate.get("warning_codes") or [],
                 "satisfied_acknowledgements": gate.get("satisfied_codes") or []},
        "acknowledged": {k: v for k, v in ack.items() if v not in (None, False, [], "")},
        "supersedes": ({"prior_count": sup.get("prior_count"), "supersedes_decision_id": sup.get("supersedes_decision_id"), "reason": sup.get("reason")} if sup else None),
        "evidence_txn_ids": meta.get("evidence_txn_ids") or [],
    }


# ── verify ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _check(ok: bool | None, detail: str) -> dict:
    return {"ok": ok, "detail": detail}


def verify(dossier: dict) -> dict:
    """Replay every check that needs nothing but the file. {checks: {name: {ok: True|False|None, detail}}, verdict: 'VERIFIED'|'FAILED'|'INCOMPLETE'}.
    `ok` None = this check cannot be run on this file (stated, never silently passed)."""
    from skills import defensibility as DG
    from skills import governance as GV
    from skills.grounding import validate_narrative
    from skills.ledger import evidence_snapshot_sha256, missing_provenance, MIN_OVERRIDE_REASON_CHARS, text_sha256

    checks: dict[str, dict] = {}
    if not isinstance(dossier, dict) or dossier.get("schema") != SCHEMA:
        return {"checks": {"schema": _check(False, f"not a {SCHEMA} file")}, "verdict": "FAILED"}
    checks["schema"] = _check(True, SCHEMA)
    sealed = dossier.get("dossier_sha256")
    checks["file_sealed"] = _check(sealed == seal(dossier), "the file hashes to the digest it carries" if sealed == seal(dossier)
                                   else "the file does not match its own digest: it was edited after it was written")

    row = dossier.get("ledger_row") or {}
    stored = (dossier.get("ledger_row_hash") or {}).get("stored")
    if stored:
        again = row_hash(row)
        checks["ledger_row_hash"] = _check(again == stored, "the ledger row's SHA-256, recomputed here with Snowflake's serialisation, equals the hash the ledger stored"
                                           if again == stored else "the row in this file does not hash to the hash the ledger stored")
    else:
        checks["ledger_row_hash"] = _check(None, "the ledger row carries no hash (it predates integrity sealing)")
    same = {k: (row.get(k) == (dossier.get("decision") or {}).get(k)) for k in ("decision_id", "disposition", "rationale_text", "decision_maker_id")}
    checks["summary_matches_row"] = _check(all(same.values()), "the decision section is the ledger row" if all(same.values()) else f"the decision section differs from the ledger row: {[k for k, v in same.items() if not v]}")

    meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    missing = missing_provenance(meta) if meta else ["metadata"]
    checks["provenance_complete"] = _check(not missing, "all required provenance fields present" if not missing else f"missing: {', '.join(missing)}")

    gate = meta.get("defensibility_gate")
    if isinstance(gate, dict) and gate.get("gate_version"):
        consistent, allowed = DG.gate_consistent(gate), bool(gate.get("can_record"))
        checks["gate_consistent"] = _check(consistent and allowed, f"stored gate v{gate.get('gate_version')} is consistent with its own conditions and allowed the write ({gate.get('status')})"
                                           if consistent and allowed else "the stored gate is inconsistent with its conditions, or it did not allow the write")
    else:
        checks["gate_consistent"] = _check(None, "no stored gate (the row predates the defensibility gate)")

    basis = meta.get("regulatory_basis")
    if isinstance(basis, dict) and basis.get("schema") == GV.BASIS_SCHEMA:
        checks["regulatory_basis_intact"] = _check(GV.basis_intact(basis), "the stored basis hashes to its own digest" if GV.basis_intact(basis) else "the stored basis was edited after the write")
    else:
        checks["regulatory_basis_intact"] = _check(None, "no hashed regulatory basis in this row")

    gos = (meta.get("gos") or {}).get("narrative_sha256")
    text = row.get("rationale_text")
    checks["rationale_digest"] = _check(None if not gos else text_sha256(text) == gos, "no rationale digest recorded" if not gos else
                                        ("the rationale text equals the text the provenance digested" if text_sha256(text) == gos else "the rationale text differs from the one digested at the time"))

    txns = (dossier.get("case_record") or {}).get("transactions") or []
    snap = meta.get("evidence_snapshot_sha256")
    if snap and txns:
        ok = evidence_snapshot_sha256(txns) == snap
        checks["evidence_digest"] = _check(ok, "the included transactions are the ones the decision was made on (digest equal)" if ok else
                                           "the included transactions differ from the evidence the decision was made on (they changed since, or this file was edited)")
    else:
        checks["evidence_digest"] = _check(None, "no evidence digest or no transactions in the file")

    alert = (dossier.get("case_record") or {}).get("alert") or {}
    if row.get("disposition") == "FILE" and txns:
        r = validate_narrative(text or "", txns, profile_text=alert.get("CUSTOMER_PROFILE") or "", alert_narrative=alert.get("ALERT_NARRATIVE") or "",
                               context_dates=[d for d in (alert.get("ALERT_DATE"), (row.get("suspicion_formed_at") or "")[:10]) if d])
        checks["evidence_gate_replay"] = _check(bool(r["passed"]), "the evidence gate re-run on the stored rationale passes" if r["passed"] else f"the stored rationale FAILS the evidence gate: {r['unsupported_claims_by_type']}")
    else:
        checks["evidence_gate_replay"] = _check(None, "not a FILE decision, or no transactions in the file")

    reason_ok = len((meta.get("override_reason") or "").strip()) >= MIN_OVERRIDE_REASON_CHARS
    checks["override_recorded"] = _check((not meta.get("override")) or reason_ok, "no override" if not meta.get("override") else
                                         ("the override carries a written reason" if reason_ok else "an override is recorded without a written reason"))
    sup = meta.get("supersession")
    if sup:
        sup_ok = len(str(sup.get("reason") or "").strip()) >= MIN_OVERRIDE_REASON_CHARS and bool(sup.get("supersedes_decision_id"))
        checks["supersession_recorded"] = _check(sup_ok, "a later decision carries the earlier decision id and a written reason" if sup_ok else "a repeat decision lacks the earlier decision id or its reason")
    else:
        checks["supersession_recorded"] = _check(None, "a first decision on this alert (nothing superseded)")

    failed = [k for k, v in checks.items() if v["ok"] is False]
    return {"checks": checks, "verdict": "FAILED" if failed else ("INCOMPLETE" if any(v["ok"] is None for v in checks.values()) else "VERIFIED"), "failed": failed}


# ── print ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def render_html(dossier: dict, verification: dict | None = None) -> str:
    """A printable page of the dossier. Every dynamic value is escaped; there is no script and no external resource."""
    e = lambda v: html.escape("" if v is None else str(v), quote=True)  # noqa: E731
    s, d = dossier.get("summary") or {}, dossier.get("decision") or {}
    v = verification or verify(dossier)
    rows = "".join(f"<tr><td>{e(k.replace('_', ' '))}</td><td class='{'ok' if c['ok'] else ('no' if c['ok'] is False else 'na')}'>{'OK' if c['ok'] else ('FAILED' if c['ok'] is False else 'not possible')}</td><td>{e(c['detail'])}</td></tr>"
                   for k, c in v["checks"].items())
    basis = s.get("basis") or {}
    txn_rows = "".join(f"<tr><td>{e(t['txn_id'])}</td><td>{e(t['date'])}</td><td>{e(t['type'])}</td><td class='r'>{t['amount_inr']:,.2f}</td><td>{e(t['channel'])}</td><td>{e(t['counterparty'])}{' (flagged)' if t.get('is_flagged') else ''}</td></tr>"
                       for t in (dossier.get("case_record") or {}).get("transactions") or [])
    ack = "".join(f"<li>{e(k.replace('_', ' '))}: {e(val)}</li>" for k, val in (s.get("acknowledged") or {}).items()) or "<li>none required or recorded</li>"
    sup = s.get("supersedes")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Decision dossier {e(d.get('decision_id'))}</title>
<style>body{{font:14px/1.5 system-ui,sans-serif;max-width:900px;margin:24px auto;padding:0 16px;color:#1b2330}}h1{{font-size:1.4rem}}h2{{font-size:1.05rem;margin-top:1.6em;border-bottom:1px solid #ccd}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ccd;padding:4px 8px;text-align:left;vertical-align:top}}.r{{text-align:right}}.ok{{color:#14653a}}.no{{color:#a8231b;font-weight:600}}.na{{color:#667}}
.note{{background:#f3f5f9;border-left:4px solid #5a7aa0;padding:8px 12px}}pre{{white-space:pre-wrap;background:#f6f7f9;padding:8px 12px;border:1px solid #dde}}@media print{{body{{margin:0}}}}</style></head><body>
<h1>Decision dossier</h1><p class="note">{e(dossier.get('notice'))}</p>
<p>Alert <b>{e(d.get('alert_id'))}</b> · customer {e(d.get('customer_ref'))} · decision <code>{e(d.get('decision_id'))}</code><br>
<b>{e(d.get('disposition'))}</b> by {e(d.get('decision_maker_id'))}{' (identity authenticated)' if s.get('identity_authenticated') else ' (identity typed, not authenticated)' if s.get('identity_authenticated') is False else ''} at {e(d.get('decision_made_at'))} UTC ·
suspicion formed {e(d.get('suspicion_formed_at') or 'not recorded')} · SLA days remaining at decision {e(d.get('sla_days_remaining'))}</p>
<h2>Verification (replayed from this file alone): {e(v['verdict'])}</h2><table><tr><th>Check</th><th>Result</th><th>Detail</th></tr>{rows}</table>
<h2>What the AI said, and what the officer did</h2><p>AI recommendation: <b>{e(s.get('ai_said'))}</b>{' (model ' + e(s.get('ai_model')) + ')' if s.get('ai_model') and s.get('ai_model') != 'NOT_RUN' else ''}{' · output source: ' + e(s.get('ai_output_source')) if s.get('ai_output_source') else ''}.
Officer decided <b>{e(s.get('disposition'))}</b>{'; this overrode the AI. Reason: ' + e(s.get('override_reason')) if s.get('overrode_ai') else ''}.</p>
{('<p class="note">Supersedes an earlier decision (' + e(sup.get('supersedes_decision_id')) + '), ' + e(sup.get('prior_count')) + ' earlier decision(s) on this alert. Reason: ' + e(sup.get('reason')) + '</p>') if sup else ''}
<h2>Regulatory basis</h2><p>Corpus {e(basis.get('corpus_version'))} (snapshot {e(basis.get('snapshot_date'))}); grade {e(basis.get('grade'))}. PROVEN: {e(', '.join(basis.get('proven') or []) or 'none')}. ASSUMED: {e(', '.join(basis.get('assumed') or []) or 'none')}.
Independently verified rules: {e(basis.get('independently_verified'))}. PROVEN means a primary source is cited by the corpus author; it is not independent verification.</p>
<h2>Acknowledged by the officer</h2><ul>{ack}</ul>
<h2>Rationale, exactly as recorded</h2><pre>{e(d.get('rationale_text'))}</pre>
<h2>Case record the file was sealed with</h2><table><tr><th>Txn</th><th>Date</th><th>Type</th><th>Amount (INR)</th><th>Channel</th><th>Counterparty</th></tr>{txn_rows}</table>
<p>Ledger row hash: <code>{e((dossier.get('ledger_row_hash') or {}).get('stored'))}</code> · dossier digest: <code>{e(dossier.get('dossier_sha256'))}</code> · generated {e(dossier.get('generated_at_utc'))} UTC</p>
</body></html>"""
