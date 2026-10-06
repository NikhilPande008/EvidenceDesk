"""
The case feed contract: what an institution sends EvidenceDesk, and what is refused at the door.

EvidenceDesk investigates signals other systems raise. It needs two files from the institution's detection or case-management system:

  alerts        one row per alert        (alert_id, customer_ref, alert_date, alert_type, alert_amount_inr, ... optional suspicion_formed_at)
  transactions  one row per transfer     (txn_id, alert_id, txn_date, txn_type CREDIT|DEBIT, amount_inr, ... optional channel, counterparty, is_flagged)

`apply_mapping` turns a differently shaped export (other column names, D/C codes, Y/N flags, DD/MM/YYYY dates, thousands separators) into this shape
with a small mapping file, so an institution does not have to reshape its data by hand. `validate` then checks every row and every link and returns
what is accepted, what is rejected and why, and what is only worth a warning. Nothing is guessed: a row that cannot be read exactly is rejected with
its reason, never repaired.

Pure Python: no database, no model, no clock of its own (`today` is passed in). The loader (scripts/load_feed.py) writes only the ACCEPTED rows, only
with an owner role, and only when told which database it expects to be writing to.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,19}")                      # ALERTS / TRANSACTIONS key columns are VARCHAR(20)
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
TXN_TYPES = ("CREDIT", "DEBIT")
MAX_AMOUNT = 10 ** 12                                                         # Rs.1 lakh crore: beyond this a row is a typing error, not a transaction
FUTURE_TOLERANCE_DAYS = 1
RECONCILIATION_TOLERANCE = 0.01                                               # the credits (or debits, for an outward alert) vs the alert amount

ALERT_FIELDS = {
    "alert_id": {"required": True, "max": 20, "help": "unique id of the alert in the source system"},
    "customer_ref": {"required": True, "max": 20, "help": "pseudonymous customer reference (never a name or an account number)"},
    "alert_date": {"required": True, "help": "YYYY-MM-DD, the day the detector raised it"},
    "alert_type": {"required": True, "max": 100, "help": "detector rule name, e.g. MULE_PASSTHROUGH"},
    "alert_amount_inr": {"required": True, "help": "the amount the alert is about, in rupees"},
    "signal_source": {"required": False, "max": 100, "help": "which system raised it, e.g. INTERNAL_RULE"},
    "account_type": {"required": False, "max": 50, "help": "SAVINGS | CURRENT | NRO ..."},
    "customer_profile": {"required": False, "max": 500, "help": "one-line KYC summary"},
    "alert_narrative": {"required": False, "max": 2000, "help": "what the detector observed (observations, not conclusions)"},
    "suspicion_formed_at": {"required": False, "help": "ISO 8601 with a time zone: when suspicion formed; starts the 7-working-day clock. Leave empty if unknown: it is never inferred"},
    "rfi_triggers": {"required": False, "help": "detector tags, separated by ';'"},
}
TXN_FIELDS = {
    "txn_id": {"required": True, "max": 20, "help": "unique id of the transaction row"},
    "alert_id": {"required": True, "max": 20, "help": "the alert this row belongs to"},
    "txn_date": {"required": True, "help": "YYYY-MM-DD value date"},
    "txn_type": {"required": True, "help": "CREDIT (into the customer's account) or DEBIT (out of it)"},
    "amount_inr": {"required": True, "help": "rupees, positive"},
    "channel": {"required": False, "max": 30, "help": "UPI | NEFT | RTGS | IMPS | CASH | SWIFT | ATM ..."},
    "counterparty": {"required": False, "max": 200, "help": "the other party, named as the source system names it"},
    "is_flagged": {"required": False, "help": "true / false: the source system's watch-list or registry flag"},
    "customer_ref": {"required": False, "max": 20, "help": "defaults to the alert's customer"},
}


# ── mapping ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def apply_mapping(rows: list[dict], fields: dict[str, dict], mapping: dict | None, kind: str) -> list[dict]:
    """Rename columns, translate coded values and re-read dates, per `mapping[kind]`:
         {"columns": {"alert_id": "AlertRef", ...}, "values": {"txn_type": {"D": "DEBIT", "C": "CREDIT"}}, "date_formats": {"txn_date": "%d/%m/%Y"},
          "datetime_formats": {"suspicion_formed_at": {"format": "%d/%m/%Y %H:%M", "tz": "+05:30"}}, "strip_thousands": ["amount_inr"]}
    A canonical field with no mapped column keeps its own name. Unmapped columns are dropped. A value that cannot be translated is left as it is, so
    validation rejects it with the original text in the reason."""
    spec = (mapping or {}).get(kind) or {}
    cols, values, dfmt, strip = spec.get("columns") or {}, spec.get("values") or {}, spec.get("date_formats") or {}, set(spec.get("strip_thousands") or [])
    dtfmt = spec.get("datetime_formats") or {}
    out = []
    for raw in rows:
        row: dict[str, Any] = {}
        for field in fields:
            src = cols.get(field, field)
            v = raw.get(src)
            if isinstance(v, str):
                v = v.strip()
            if v in ("", None):
                row[field] = None
                continue
            if field in values and isinstance(v, str) and v in values[field]:
                v = values[field][v]
            if field in dfmt and isinstance(v, str):
                try:
                    v = datetime.strptime(v, dfmt[field]).date().isoformat()
                except ValueError:
                    pass                                                       # left as typed: validation reports it
            if field in dtfmt and isinstance(v, str):
                try:                                                           # a timestamp the source writes without a zone: the mapping SAYS which zone it is in
                    from datetime import timezone
                    sign, hh, mm = (1 if dtfmt[field]["tz"][0] != "-" else -1), int(dtfmt[field]["tz"][-5:-3]), int(dtfmt[field]["tz"][-2:])
                    v = datetime.strptime(v, dtfmt[field]["format"]).replace(tzinfo=timezone(sign * timedelta(hours=hh, minutes=mm))).isoformat()
                except (ValueError, KeyError, IndexError):
                    pass
            if field in strip and isinstance(v, str):
                v = v.replace(",", "")
            row[field] = v
        out.append(row)
    return out


# ── field readers ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _text(v: Any, spec: dict, name: str, why: list[str]) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    if CONTROL_RE.search(s):
        why.append(f"{name} contains a control character")
        return None
    if spec.get("max") and len(s) > spec["max"]:
        why.append(f"{name} is {len(s)} characters; the limit is {spec['max']}")
        return None
    return s


def _date(v: Any, name: str, why: list[str], today: date) -> str | None:
    if v is None:
        return None
    try:
        d = date.fromisoformat(str(v).strip()[:10]) if re.fullmatch(r"\d{4}-\d{2}-\d{2}(T.*)?", str(v).strip()) else None
    except ValueError:
        d = None
    if d is None:
        why.append(f"{name} {str(v)[:30]!r} is not a YYYY-MM-DD date")
        return None
    if d > today + timedelta(days=FUTURE_TOLERANCE_DAYS):
        why.append(f"{name} {d} is in the future")
        return None
    if d.year < 2000:
        why.append(f"{name} {d} is before 2000")
        return None
    return d.isoformat()


def _amount(v: Any, name: str, why: list[str]) -> float | None:
    if v is None:
        return None
    try:
        f = float(str(v).replace(",", "").strip())
    except ValueError:
        why.append(f"{name} {str(v)[:30]!r} is not a number")
        return None
    if f != f or f in (float("inf"), float("-inf")) or f <= 0 or f > MAX_AMOUNT:
        why.append(f"{name} {f} is not a positive amount below {MAX_AMOUNT:,}")
        return None
    return round(f, 2)


def _bool(v: Any, name: str, why: list[str]) -> bool | None:
    if v is None:
        return False
    s = str(v).strip().lower()
    if s in ("true", "1", "yes", "y", "t"):
        return True
    if s in ("false", "0", "no", "n", "f", ""):
        return False
    why.append(f"{name} {str(v)[:20]!r} is not true or false")
    return None


def _suspicion(v: Any, why: list[str]) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        why.append(f"suspicion_formed_at {s[:30]!r} is not an ISO 8601 timestamp")
        return None
    if dt.tzinfo is None:
        why.append("suspicion_formed_at has no time zone (the 7-working-day clock needs one)")
        return None
    return dt.isoformat()


# ── validation ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def validate(alerts: list[dict], transactions: list[dict], *, today: date) -> dict:
    """Check canonical-shaped rows. Returns
         {alerts: [accepted alert dicts], transactions: [accepted txn dicts], rejected: [{file, row, id, reasons}], warnings: [{id, text}], summary: {...}}
    Row numbers are 1-based positions in the file (header excluded)."""
    rejected: list[dict] = []
    warnings: list[dict] = []
    ok_alerts: list[dict] = []
    seen: set[str] = set()
    for i, raw in enumerate(alerts, 1):
        why: list[str] = []
        r: dict[str, Any] = {}
        for f, spec in ALERT_FIELDS.items():
            v = raw.get(f)
            if f in ("alert_date",):
                r[f] = _date(v, f, why, today)
            elif f == "alert_amount_inr":
                r[f] = _amount(v, f, why)
            elif f == "suspicion_formed_at":
                r[f] = _suspicion(v, why)
            elif f == "rfi_triggers":
                tags = [t.strip() for t in str(v).split(";") if t.strip()] if v else []
                r[f] = tags if all(ID_RE.fullmatch(t) for t in tags) else (why.append("rfi_triggers holds a tag that is not a plain id") or [])
            else:
                r[f] = _text(v, spec, f, why)
            if spec["required"] and r[f] in (None, "") and not any(w.startswith(f) for w in why):
                why.append(f"{f} is required")
        aid = r.get("alert_id")
        if aid and not ID_RE.fullmatch(aid):
            why.append("alert_id may hold letters, digits, '.', '_' and '-' only (at most 20 characters)")
        if aid in seen:
            why.append(f"alert_id {aid} appears more than once in this feed")
        if why:
            rejected.append({"file": "alerts", "row": i, "id": str(raw.get("alert_id"))[:30], "reasons": why})
            continue
        seen.add(aid)
        ok_alerts.append(r)

    alert_by_id = {a["alert_id"]: a for a in ok_alerts}
    ok_txns: list[dict] = []
    seen_t: set[str] = set()
    for i, raw in enumerate(transactions, 1):
        why = []
        t: dict[str, Any] = {}
        for f, spec in TXN_FIELDS.items():
            v = raw.get(f)
            if f == "txn_date":
                t[f] = _date(v, f, why, today)
            elif f == "amount_inr":
                t[f] = _amount(v, f, why)
            elif f == "is_flagged":
                t[f] = _bool(v, f, why)
            elif f == "txn_type":
                s = str(v).strip().upper() if v is not None else None
                t[f] = s if s in TXN_TYPES else (why.append(f"txn_type {str(v)[:20]!r} is not CREDIT or DEBIT") or None)
            else:
                t[f] = _text(v, spec, f, why)
            if spec["required"] and t[f] in (None, "") and not any(w.startswith(f) for w in why):
                why.append(f"{f} is required")
        tid = t.get("txn_id")
        if tid and not ID_RE.fullmatch(tid):
            why.append("txn_id may hold letters, digits, '.', '_' and '-' only (at most 20 characters)")
        if tid in seen_t:
            why.append(f"txn_id {tid} appears more than once in this feed")
        if t.get("alert_id") and t["alert_id"] not in alert_by_id:
            why.append(f"alert_id {t['alert_id']} is not an accepted alert in this feed")
        if why:
            rejected.append({"file": "transactions", "row": i, "id": str(raw.get("txn_id"))[:30], "reasons": why})
            continue
        t["customer_ref"] = t.get("customer_ref") or alert_by_id[t["alert_id"]]["customer_ref"]
        seen_t.add(tid)
        ok_txns.append(t)

    by_alert: dict[str, list[dict]] = {}
    for t in ok_txns:
        by_alert.setdefault(t["alert_id"], []).append(t)
    for a in ok_alerts:
        rows = by_alert.get(a["alert_id"], [])
        if not rows:
            warnings.append({"id": a["alert_id"], "text": "no transaction rows: the evidence gate cannot check a narrative against this alert, and FILE will be blocked"})
            continue
        for side in ("CREDIT", "DEBIT"):
            total = sum(t["amount_inr"] for t in rows if t["txn_type"] == side)
            if total and abs(total - a["alert_amount_inr"]) / a["alert_amount_inr"] <= RECONCILIATION_TOLERANCE:
                break
        else:
            warnings.append({"id": a["alert_id"], "text": f"neither the credits nor the debits reconcile to the alert amount within {RECONCILIATION_TOLERANCE:.0%}; the case page will show an amount-reconciliation finding"})
        if a["suspicion_formed_at"] is None:
            warnings.append({"id": a["alert_id"], "text": "no suspicion_formed_at: the 7-working-day clock shows 'not recorded' until the officer enters one"})
    return {"alerts": ok_alerts, "transactions": ok_txns, "rejected": rejected, "warnings": warnings,
            "summary": {"alerts_in": len(alerts), "alerts_accepted": len(ok_alerts), "transactions_in": len(transactions), "transactions_accepted": len(ok_txns),
                        "rejected": len(rejected), "warnings": len(warnings)}}


def load_params(alert: dict) -> dict:
    """The parameter dict scripts/setup_alerts.MERGE_SQL takes, for one accepted alert. Feed alerts carry no scenario label and no answer key."""
    import json
    return {"ALERT_ID": alert["alert_id"], "SCENARIO_ID": "FEED", "CUSTOMER_REF": alert["customer_ref"], "ALERT_DATE": alert["alert_date"], "ALERT_TYPE": alert["alert_type"],
            "SIGNAL_SOURCE": alert["signal_source"], "ACCOUNT_TYPE": alert["account_type"], "CUSTOMER_PROFILE": alert["customer_profile"],
            "ALERT_AMOUNT_INR": alert["alert_amount_inr"], "ALERT_NARRATIVE": alert["alert_narrative"], "RFI_TRIGGERS": json.dumps(alert["rfi_triggers"]),
            "POE_FACTORS": "[]", "RULES_CITED": "[]", "SUSPICION_FORMED_AT": alert["suspicion_formed_at"], "ALERT_STATUS": "OPEN"}


def txn_params(t: dict) -> dict:
    return {"TXN_ID": t["txn_id"], "ALERT_ID": t["alert_id"], "CUSTOMER_REF": t["customer_ref"], "TXN_DATE": t["txn_date"], "TXN_TYPE": t["txn_type"], "AMOUNT_INR": t["amount_inr"],
            "CHANNEL": t["channel"], "COUNTERPARTY": t["counterparty"], "IS_FLAGGED": bool(t["is_flagged"])}
