"""
Evidence quality — deterministic data-quality, ambiguity and contradiction checks over ONE case record.

No model, no database, no clock of its own (`now` is passed in). The same inputs always give the same findings.

WHAT IT DOES
  Looks at the alert row, its transaction rows and (optionally) the owner of each transaction row, and reports what is MISSING, STALE,
  CONTRADICTORY, UNAVAILABLE, UNSUPPORTED or UNRESOLVED — each as a finding with an EFFECT the Principal Officer can act on:

    INFORMATIONAL            shown and stored; never stops anything
    REQUIRES_ACKNOWLEDGEMENT the PO must tick an acknowledgement before FILE / a closure           (gate: EVIDENCE_QUALITY_ACK_REQUIRED)
    REQUIRES_MANUAL_REVIEW   the PO must do a manual check and write down what they did            (gate: EVIDENCE_QUALITY_MANUAL_REVIEW)
    BLOCKS_FILING            FILE cannot be recorded until the underlying fact is fixed              (gate: EVIDENCE_QUALITY_BLOCKS_FILING)

  The EFFECTS ARE PRODUCT POLICY (this table, below), not a regulatory requirement. They are enforced by the one decision gate
  (skills/defensibility.py), which the recorder re-runs; this module only classifies.

WHAT IT DOES NOT DO
  * It does not decide whether to file. It does not rate the customer. It does not call a model.
  * A finding derived from FREE TEXT (the detector narrative or the profile line) is a pattern match, labelled `text_pattern`, and can
    never BLOCK — at most it asks for a manual review. Only structured fields (rows, amounts, dates, types) can block.
  * "Recommended next evidence" is a list of SUGGESTED INVESTIGATION STEPS, not conclusions. Every sentence is a fixed template.

Pure functions; nothing here reads or writes the database.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime
from typing import Any

from skills import evidence as ev
from skills.grounding import validate_narrative

POLICY_VERSION = "1"

# effects, weakest to strongest
INFORMATIONAL, REQUIRES_ACKNOWLEDGEMENT, REQUIRES_MANUAL_REVIEW, BLOCKS_FILING = (
    "INFORMATIONAL", "REQUIRES_ACKNOWLEDGEMENT", "REQUIRES_MANUAL_REVIEW", "BLOCKS_FILING")
EFFECTS = (INFORMATIONAL, REQUIRES_ACKNOWLEDGEMENT, REQUIRES_MANUAL_REVIEW, BLOCKS_FILING)
RANK = {e: i for i, e in enumerate(EFFECTS)}
EFFECT_LABEL = {
    INFORMATIONAL: "Informational",
    REQUIRES_ACKNOWLEDGEMENT: "Requires acknowledgement",
    REQUIRES_MANUAL_REVIEW: "Requires manual review",
    BLOCKS_FILING: "Blocks filing",
}
EFFECT_MEANING = {
    INFORMATIONAL: "Shown and stored with the decision. It never stops you.",
    REQUIRES_ACKNOWLEDGEMENT: "Before you file or close, tick that you have seen it. Recorded with the decision.",
    REQUIRES_MANUAL_REVIEW: "Before you file or close, check it yourself and write what you did (at least 20 characters). Recorded with the decision.",
    BLOCKS_FILING: "A filing cannot be recorded until the underlying fact is fixed. You can still defer, or close with a reason.",
}

CATEGORIES = ("KYC", "TRANSACTION_HISTORY", "STALE_RECORD", "CONTRADICTION", "DOCUMENTS", "UNSUPPORTED_CLAIMS", "IDENTITY_ENTITY")
CATEGORY_LABEL = {
    "KYC": "KYC", "TRANSACTION_HISTORY": "Transaction history", "STALE_RECORD": "Stale records", "CONTRADICTION": "Contradictory data",
    "DOCUMENTS": "Documents", "UNSUPPORTED_CLAIMS": "Unsupported claims", "IDENTITY_ENTITY": "Identity and entity matches",
}

# ── policy thresholds (product policy; each is covered by a test) ─────────────────────────────────────────
AMOUNT_TOLERANCE_OK = 0.01          # alert amount vs recorded credits: within 1 % is reconciled (the seed invariant)
AMOUNT_TOLERANCE_REVIEW = 0.10      # above 10 % the PO must check it manually
AMOUNT_TOLERANCE_BLOCK = 0.25       # above 25 % the amount to report is ambiguous: filing blocked
BASELINE_MIN_DAYS = 30              # fewer days of history before the alert than this = no baseline in the record
STALE_RECORD_DAYS = 30              # the record ends this many days (or more) before the alert
ALERT_AGED_DAYS = 30                # an alert this old (calendar days) with no decision: confirm the record is current
REGISTRY_SOURCES = frozenset({"I4C", "MULE_HUNTER", "DPIP"})
LINKED_ENTITY_ALERT_TYPES = frozenset({"DEVICE_IDENTITY_LINKAGE", "BENEFICIARY_CONCENTRATION"})
MAX_REFS = 8
_CLIP = 90

# code → (category, title, why it matters, suggested next step). Static text only: no case data is ever interpolated into a title.
CATALOG: dict[str, tuple[str, str, str, str]] = {
    "KYC_PROFILE_MISSING": ("KYC", "No KYC profile in the record",
                            "Without a profile there is nothing to compare the activity with, and the customer cannot be described in a report.",
                            "Obtain the customer's KYC profile from your core KYC system through your normal internal process."),
    "KYC_PROFILE_SPARSE": ("KYC", "The profile states no income, turnover or occupation",
                           "Income and occupation are what the activity is compared with; without them that comparison cannot be made from this record.",
                           "Check the KYC system for declared income, occupation or business activity and add it to your working note."),
    "KYC_CURRENCY_FLAG": ("KYC", "The record says KYC is stale, expired or unconfirmed",
                          "A stale or unconfirmed KYC limits what can be said about the customer's source of funds. (Detected from text by pattern.)",
                          "Confirm the date of the last KYC refresh in your KYC system and whether the customer's details are current."),
    "TXN_NONE": ("TRANSACTION_HISTORY", "No transactions on record",
                 "A narrative cannot be checked against nothing.",
                 "Load or request the account's transactions for the alert window before deciding."),
    "TXN_UNREADABLE": ("TRANSACTION_HISTORY", "The transaction record could not be read",
                       "A read failure is not the same as 'no transactions'; the case cannot be checked until it is fixed.",
                       "Reload the case. If it persists, tell your administrator (quote the reference shown)."),
    "TXN_SUMMARY_ONLY": ("TRANSACTION_HISTORY", "Every transaction row is an aggregated summary",
                         "Individual transfers, their dates and their counterparties are not in this record; counts and timing cannot be checked.",
                         "Pull the individual transfers behind the summary from the payments system and review them."),
    "TXN_PARTIAL_SUMMARY": ("TRANSACTION_HISTORY", "Some transaction rows are aggregated summaries",
                            "Those rows stand for many transfers, so counts and timing for them cannot be checked.",
                            "Pull the individual transfers behind the summarised rows if they matter to your decision."),
    "TXN_NO_BASELINE": ("TRANSACTION_HISTORY", "No history before the alert window",
                        "Without earlier activity the record cannot show what is normal for this customer.",
                        "Retrieve a longer statement (for example the prior 6–12 months) to establish the customer's normal pattern."),
    "TXN_RECORD_STALE": ("STALE_RECORD", "The transaction record ends well before the alert",
                         "Activity after the last recorded transaction is not in this record.",
                         "Refresh the transactions up to today and re-check the pattern."),
    "ALERT_AGED": ("STALE_RECORD", "The alert is old and still open",
                   "Account activity, flags or documents may have changed since the alert was raised.",
                   "Confirm the transaction record and any flags are current before relying on them."),
    "AMOUNT_RECONCILIATION": ("CONTRADICTION", "The alert amount does not match the recorded credits",
                              "The amount you would report is ambiguous when the alert and the transactions disagree.",
                              "Reconcile the alert amount with the account statement and note which figure you rely on."),
    "FLAG_INCONSISTENT": ("CONTRADICTION", "The same counterparty is flagged on some rows and not on others",
                          "A flag that is not applied consistently cannot be relied on as a fact until it is resolved.",
                          "Check the flag's source (registry or internal list) for that counterparty and its date."),
    "TXN_INVALID": ("CONTRADICTION", "A transaction row is malformed",
                    "A row with a non-positive amount, an unknown direction or a duplicate ID makes the totals unreliable.",
                    "Correct or re-load the malformed rows from the source system."),
    "TXN_FUTURE_DATED": ("CONTRADICTION", "A transaction is dated in the future",
                         "A future date cannot be a real posting date; the record or its date is wrong.",
                         "Check the value date of that row in the source system."),
    "SIGNAL_NOT_CORROBORATED": ("CONTRADICTION", "A registry-sourced signal is not matched by any flagged counterparty",
                                "The transaction record does not show the flag the signal source implies. That may be a false positive or missing data.",
                                "Check the signal source's own record for the match, and whether the flag was applied to these counterparties."),
    "DOCUMENTS_REFERENCED": ("DOCUMENTS", "Documents are referenced but not available here",
                             "The record says documents exist; this application cannot open or check them.",
                             "Open the referenced documents yourself and note what you checked."),
    "DOCUMENTS_MISSING_STATED": ("DOCUMENTS", "The record says documents are missing or not yet produced",
                                 "A decision that depends on a document that does not exist is not supported. (Detected from text by pattern.)",
                                 "Establish through your normal process whether the documents exist, and record the outcome."),
    "DETECTOR_CLAIMS_UNCORROBORATED": ("UNSUPPORTED_CLAIMS", "The detector text states facts the transaction record does not show",
                                       "Figures, dates, channels or places in the detector's narrative are not borne out by the rows, so do not copy them into a narrative unchecked.",
                                       "Verify each such figure against source records before you rely on it."),
    "DETECTOR_CLAIMS_UNCHECKABLE": ("UNSUPPORTED_CLAIMS", "The detector text states facts that cannot be checked against an aggregated record",
                                    "Because the rows are summaries, the narrative's figures cannot be tested at all.",
                                    "Obtain the underlying transfers, then check the narrative's figures against them."),
    "TXN_OWNER_MISMATCH": ("IDENTITY_ENTITY", "Transaction rows belong to a different customer reference than the alert",
                           "Reporting activity against the wrong customer is a serious error; the match must be resolved first.",
                           "Confirm in the source system which customer or linked account each flagged row belongs to."),
    "LINKED_ENTITIES_NOT_SUPPLIED": ("IDENTITY_ENTITY", "The alert type asserts links to other customers or accounts that the record does not hold",
                                     "The linkage the detector reports cannot be inspected: the linked entities are not in this record.",
                                     "Retrieve the linked accounts or devices the detector refers to from its own case view."),
    "COUNTERPARTY_UNIDENTIFIED": ("IDENTITY_ENTITY", "Some counterparties are not identified",
                                  "Unidentified senders or recipients cannot be matched with other cases or checked against lists.",
                                  "Ask the payments or UPI provider, through official channels, to identify these counterparties."),
    "COUNTERPARTY_NEAR_DUPLICATE": ("IDENTITY_ENTITY", "Two counterparty names look like the same entity",
                                    "If they are one entity, totals and counts per counterparty are understated; if not, they must stay separate. This is unresolved.",
                                    "Confirm from the source records whether these are one counterparty or two."),
}

# findings the decision gate already enforces by another code — classified here for display, not double-counted at the gate
ENFORCED_ELSEWHERE = {"TXN_NONE": "NO_TRANSACTION_RECORD", "TXN_UNREADABLE": "NO_TRANSACTION_RECORD"}

# ── text patterns (heuristic by nature; their findings are labelled text_pattern and can never block) ────────────────
_KYC_STALE = re.compile(
    r"\b(?:stale|expired|outdated|lapsed)\s+kyc\b|\bkyc\b[^.;]{0,40}?\b(?:stale|expired|outdated|lapsed|not\s+(?:been\s+)?(?:updated|renewed))\b"
    r"|\b(?:has|have)\s+not\s+updated\s+(?:his\s+|her\s+|their\s+|the\s+)?kyc\b|\bcontact\s+(?:number\s+)?unreachable\b|\bunreachable\b"
    r"|\baddress\s+(?:is\s+)?(?:unconfirmed|not\s+confirmed)\b|\bunconfirmed\s+address\b", re.I)
_DOCS_MISSING = re.compile(
    r"\bnot\s+yet\s+produced\b|\bno\s+[\w/\-\s]{0,30}?documentation\b|\bdocumentation\s+(?:is\s+|has\s+|was\s+)?(?:not|missing|absent)\b"
    r"|\bwithout\s+(?:any\s+)?documentation\b|\bno\s+(?:supporting\s+)?documents?\b|\bdocuments?\s+(?:have\s+|has\s+)?not\s+(?:been\s+)?(?:produced|provided|received)\b", re.I)
_DOCS_STATED = re.compile(
    r"\b(?:invoice|receipt|deed|certificate|documentation|documentary|valuation\s+report|form\s+16b|itr|tax\s+return)s?\b[^.]{0,80}?"
    r"\b(?:on\s+file|produced|provided|supplied)\b", re.I)
_INCOME_OR_OCCUPATION = re.compile(
    r"(?:₹|rs\.?|inr)\s*\d|\bper\s+(?:month|year|annum)\b|/\s*(?:month|year)\b|\bturnover\b|\bsalary\b|\bpension\b|\bincome\b|\bdeclared\b"
    r"|\b(?:employee|engineer|operator|labourer|laborer|trader|teacher|consultant|designer|officer|exporter|importer|owner|proprietor|driver|worker|clerk|"
    r"professional|retired|freelance|business|ngo|society|treasurer|importer)\b", re.I)


# ── helpers ──────────────────────────────────────────────────────────────────
def _to_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _clip(value: Any, n: int = _CLIP) -> str:
    s = " ".join(str(value if value is not None else "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _inr(v: float) -> str:
    return f"₹{float(v):,.0f}"


def _amount(row: dict) -> float | None:
    try:
        v = float(row.get("amount_inr"))
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _profile_missing(profile: str) -> bool:
    return not re.sub(r"[\s\-–—.?]+", "", profile or "") or bool(re.fullmatch(
        r"\W*(?:n/?a|none|nil|unknown|not\s+(?:provided|available|supplied)|missing|tbd)\W*", (profile or "").strip(), re.I))


# ── the assessment ───────────────────────────────────────────────────────────
def assess(alert: dict | None, transactions: list[dict] | None, *, now: date | datetime | None = None, txn_owners: dict | None = None,
           transactions_error: bool = False) -> dict:
    """Findings, effects, an evidence-sufficiency percentage and the suggested next evidence for one case.

    `alert`        the ALERTS_CURRENT row (any of: ALERT_ID, CUSTOMER_REF, ALERT_DATE, ALERT_TYPE, SIGNAL_SOURCE, ALERT_AMOUNT_INR,
                   CUSTOMER_PROFILE, ALERT_NARRATIVE, ALERT_STATUS). A missing field is treated as missing, never invented.
    `transactions` the rows in the shape CoPilotSkills.load_transactions returns.
    `txn_owners`   {txn_id: customer_ref} when known (kept OUT of `transactions` so it can never reach a model prompt).
    `transactions_error` the rows could not be read: reported as TXN_UNREADABLE, not as 'no transactions'."""
    alert = alert or {}
    txns = [t for t in (transactions or []) if isinstance(t, dict)]
    today = _to_date(now) or date.today()
    alert_date = _to_date(alert.get("ALERT_DATE"))
    profile = str(alert.get("CUSTOMER_PROFILE") or "")
    narrative = str(alert.get("ALERT_NARRATIVE") or "")
    findings: list[dict] = []

    def add(code: str, effect: str, detail: str, *, refs=(), source: str = "structured") -> None:
        category, title, why, step = CATALOG[code]
        if source == "text_pattern" and effect == BLOCKS_FILING:       # a text pattern is never enough to stop a filing
            effect = REQUIRES_MANUAL_REVIEW
        findings.append({"code": code, "category": category, "effect": effect, "title": title, "why": why, "detail": detail,
                         "refs": [_clip(r, 40) for r in list(refs)[:MAX_REFS]], "source": source, "next_step": step,
                         "enforced_by": ENFORCED_ELSEWHERE.get(code)})

    # ── KYC ──────────────────────────────────────────────────────────────────
    if _profile_missing(profile):
        add("KYC_PROFILE_MISSING", BLOCKS_FILING, "The customer profile is empty or a placeholder.")
        profile_present = False
    else:
        profile_present = True
        if not _INCOME_OR_OCCUPATION.search(profile):
            add("KYC_PROFILE_SPARSE", INFORMATIONAL, "The profile line names no income, turnover or occupation.", source="text_pattern")
        stale = _KYC_STALE.search(profile) or _KYC_STALE.search(narrative)
        if stale:
            add("KYC_CURRENCY_FLAG", REQUIRES_MANUAL_REVIEW, f"The record says: “{_clip(stale.group(0), 60)}”.", source="text_pattern")

    # ── transactions: present, readable, individual ──────────────────────────
    aggregates = [t for t in txns if ev.is_aggregate_row(t)]
    explicit = [t for t in txns if not ev.is_aggregate_row(t)]
    if transactions_error:
        add("TXN_UNREADABLE", BLOCKS_FILING, "The transactions could not be read from the database.")
    elif not txns:
        add("TXN_NONE", BLOCKS_FILING, "The alert has no transaction rows.")
    elif not explicit:
        add("TXN_SUMMARY_ONLY", REQUIRES_ACKNOWLEDGEMENT,
            f"{len(aggregates)} stored row(s), all aggregated: " + ", ".join(_clip(t.get("txn_id"), 20) for t in aggregates[:4]) + ".",
            refs=[t.get("txn_id") for t in aggregates])
    elif aggregates:
        add("TXN_PARTIAL_SUMMARY", INFORMATIONAL, f"{len(aggregates)} of {len(txns)} stored rows are aggregated summaries.",
            refs=[t.get("txn_id") for t in aggregates])

    # row validity — structured, so it can block
    seen, dupes, invalid = set(), [], []
    for t in txns:
        tid = t.get("txn_id")
        amt = _amount(t)
        if tid in seen and tid is not None:
            dupes.append(tid)
        seen.add(tid)
        if t.get("type") not in ("CREDIT", "DEBIT") or amt is None or amt <= 0:
            invalid.append(tid or "unidentified row")
    if dupes or invalid:
        bits = ([f"duplicate ID(s): {', '.join(_clip(d, 20) for d in dupes[:3])}"] if dupes else []) + \
               ([f"non-positive amount or unknown direction: {', '.join(_clip(i, 20) for i in invalid[:3])}"] if invalid else [])
        add("TXN_INVALID", BLOCKS_FILING, "; ".join(bits) + ".", refs=dupes + invalid)

    valid = [t for t in txns if t.get("type") in ("CREDIT", "DEBIT") and (_amount(t) or 0) > 0]
    credits = sum(_amount(t) for t in valid if t["type"] == "CREDIT")
    debits = sum(_amount(t) for t in valid if t["type"] == "DEBIT")

    # ── dates: baseline, staleness, future dating ────────────────────────────
    dates = sorted(d for d in (_to_date(t.get("date")) for t in txns) if d)
    baseline_ok = False
    if dates and alert_date:
        history_days = (alert_date - dates[0]).days
        baseline_ok = history_days >= BASELINE_MIN_DAYS
        if not baseline_ok and not transactions_error:
            add("TXN_NO_BASELINE", INFORMATIONAL,
                f"The earliest recorded transaction is {max(history_days, 0)} day(s) before the alert; {BASELINE_MIN_DAYS} are needed to show what is normal.")
        gap = (alert_date - dates[-1]).days
        if gap >= STALE_RECORD_DAYS:
            add("TXN_RECORD_STALE", INFORMATIONAL, f"The latest recorded transaction is {gap} days before the alert date.")
    future = [t.get("txn_id") for t in txns if (d := _to_date(t.get("date"))) and d > today]
    if future:
        add("TXN_FUTURE_DATED", REQUIRES_MANUAL_REVIEW, f"{len(future)} row(s) are dated after today.", refs=future)
    if alert_date and str(alert.get("ALERT_STATUS") or "OPEN") in ("OPEN", "DEFERRED") and (today - alert_date).days >= ALERT_AGED_DAYS:
        add("ALERT_AGED", INFORMATIONAL, f"The alert is {(today - alert_date).days} calendar days old.")

    # ── contradictions between the alert and the rows, and inside the rows ────
    reconciles, amount_gap = True, None
    try:
        alert_amount = float(alert.get("ALERT_AMOUNT_INR")) if alert.get("ALERT_AMOUNT_INR") is not None else None
    except (TypeError, ValueError):
        alert_amount = None
    compare = credits if credits else debits
    if alert_amount and alert_amount > 0 and compare > 0:
        amount_gap = abs(compare - alert_amount) / alert_amount
        if amount_gap > AMOUNT_TOLERANCE_OK:
            reconciles = False
            effect = (BLOCKS_FILING if amount_gap > AMOUNT_TOLERANCE_BLOCK else REQUIRES_MANUAL_REVIEW if amount_gap > AMOUNT_TOLERANCE_REVIEW
                      else REQUIRES_ACKNOWLEDGEMENT)
            add("AMOUNT_RECONCILIATION", effect,
                f"Alert amount {_inr(alert_amount)}; recorded {'credits' if credits else 'debits'} {_inr(compare)} ({amount_gap * 100:.1f}% apart).")

    by_key: dict[str, list[dict]] = {}
    for t in explicit:
        if ev.is_linkable_counterparty(t.get("counterparty")):
            by_key.setdefault(ev.counterparty_key(t.get("counterparty")), []).append(t)
    inconsistent = [k for k, rows in by_key.items() if len({bool(r.get("is_flagged")) for r in rows}) > 1]
    if inconsistent:
        add("FLAG_INCONSISTENT", REQUIRES_MANUAL_REVIEW,
            "Flag differs between rows for: " + ", ".join(_clip(inconsistent_label(by_key[k]), 40) for k in inconsistent[:3]) + ".",
            refs=[r.get("txn_id") for k in inconsistent for r in by_key[k]])

    source = str(alert.get("SIGNAL_SOURCE") or "").upper()
    flagged_any = any(t.get("is_flagged") for t in txns)
    if source in REGISTRY_SOURCES and txns and not transactions_error and not flagged_any:
        add("SIGNAL_NOT_CORROBORATED", INFORMATIONAL, f"The signal comes from {source}, but no counterparty carries a flag in the record.")

    # ── documents ────────────────────────────────────────────────────────────
    documented = [t for t in txns if ev.documented_counterparty(t.get("counterparty"))]
    stated = _DOCS_STATED.search(narrative) or _DOCS_STATED.search(profile)
    if documented or stated:
        bits = ([f"{len(documented)} counterparty label(s) cite documentation"] if documented else []) + (["the narrative says documents were produced"] if stated else [])
        add("DOCUMENTS_REFERENCED", INFORMATIONAL, "; ".join(bits).capitalize() + ".", refs=[t.get("txn_id") for t in documented])
    missing_docs = _DOCS_MISSING.search(narrative) or _DOCS_MISSING.search(profile)
    if missing_docs:
        add("DOCUMENTS_MISSING_STATED", REQUIRES_MANUAL_REVIEW, f"The record says: “{_clip(missing_docs.group(0), 60)}”.", source="text_pattern")

    # ── unsupported claims in the DETECTOR's own text ────────────────────────
    claims_clean = True
    if narrative.strip() and txns and not transactions_error:
        res = validate_narrative(narrative, txns, profile_text=profile, alert_narrative="", context_dates=[str(alert.get("ALERT_DATE"))[:10]] if alert_date else [])
        unsupported = {k: v for k, v in res["unsupported_claims_by_type"].items() if v and k != "evidence"}
        if unsupported:
            claims_clean = False
            shown = "; ".join(f"{k.replace('_', ' ')}: {', '.join(_clip(x, 40) for x in v[:2])}" for k, v in list(unsupported.items())[:3])
            n = sum(len(v) for v in unsupported.values())
            if explicit:
                add("DETECTOR_CLAIMS_UNCORROBORATED", REQUIRES_ACKNOWLEDGEMENT, f"{n} claim(s) not in the transaction rows — {shown}.", source="text_pattern")
            else:
                add("DETECTOR_CLAIMS_UNCHECKABLE", INFORMATIONAL, f"{n} claim(s) cannot be tested — {shown}.", source="text_pattern")

    # ── identity and entity matches ──────────────────────────────────────────
    owners = txn_owners or {}
    ref = alert.get("CUSTOMER_REF")
    mismatched = [tid for tid, owner in owners.items() if owner and ref and str(owner) != str(ref)]
    if mismatched:
        add("TXN_OWNER_MISMATCH", REQUIRES_MANUAL_REVIEW, f"{len(mismatched)} row(s) are stored under a different customer reference than the alert.", refs=mismatched)
    if str(alert.get("ALERT_TYPE") or "").upper() in LINKED_ENTITY_ALERT_TYPES:
        add("LINKED_ENTITIES_NOT_SUPPLIED", REQUIRES_MANUAL_REVIEW,
            f"Alert type {_clip(alert.get('ALERT_TYPE'), 40)} reports a link across several customers or accounts; the record holds one customer reference.")
    named = [t for t in explicit if str(t.get("counterparty") or "").strip()]
    unidentified = [t for t in named if ev.is_unidentified_counterparty(t.get("counterparty"))]
    if unidentified:
        add("COUNTERPARTY_UNIDENTIFIED", INFORMATIONAL, f"{len(unidentified)} of {len(named)} counterparty row(s) are labelled unknown or unidentified.",
            refs=[t.get("txn_id") for t in unidentified])
    keys = sorted({ev.counterparty_key(t.get("counterparty")) for t in explicit if ev.is_linkable_counterparty(t.get("counterparty"))})
    near = [(a, b) for i, a in enumerate(keys) for b in keys[i + 1:] if _near_duplicate(a, b)]
    if near:
        add("COUNTERPARTY_NEAR_DUPLICATE", INFORMATIONAL, "Possible same entity: " + "; ".join(f"“{_clip(a, 30)}” / “{_clip(b, 30)}”" for a, b in near[:2]) + ".")

    findings.sort(key=lambda f: (-RANK[f["effect"]], CATEGORIES.index(f["category"]), f["code"]))

    # ── sufficiency: how much of a decision-grade record is present ──────────
    identified_share = (1 - len(unidentified) / len(named)) if named else (1.0 if explicit else 0.0)
    codes = {f["code"] for f in findings}
    consistent = not codes & {"TXN_INVALID", "FLAG_INCONSISTENT", "TXN_OWNER_MISMATCH", "TXN_FUTURE_DATED"}
    checks = [
        ("KYC profile present", 15, 1.0 if profile_present else 0.0),
        ("Transaction rows present", 25, 1.0 if txns and not transactions_error else 0.0),
        ("Individual (not aggregated) transaction rows", 15, 1.0 if explicit and not aggregates else (0.5 if explicit else 0.0)),
        ("Alert amount reconciles with the recorded flow", 10, 1.0 if (reconciles and alert_amount and compare) else 0.0),
        ("Counterparties identified", 10, round(identified_share, 3) if txns else 0.0),
        ("Rows and flags are internally consistent", 10, 1.0 if (consistent and txns) else 0.0),
        ("History before the alert window", 5, 1.0 if baseline_ok else 0.0),
        ("Detector claims corroborated by the rows", 5, 1.0 if (claims_clean and explicit) else 0.0),
        ("Supporting documentation referenced", 5, 1.0 if (documented or stated) else 0.0),
    ]
    sufficiency = int(round(sum(w * s for _, w, s in checks)))

    counts = {e: sum(1 for f in findings if f["effect"] == e) for e in EFFECTS}
    highest = max((f["effect"] for f in findings), key=RANK.get, default=None)
    steps, seen_steps = [], set()
    for f in findings:
        if f["next_step"] not in seen_steps:
            seen_steps.add(f["next_step"])
            steps.append({"finding_code": f["code"], "effect": f["effect"], "step": f["next_step"]})
    return {
        "policy_version": POLICY_VERSION, "evaluated": True, "findings": findings, "counts": counts, "highest_effect": highest,
        "blocks_filing": counts[BLOCKS_FILING] > 0, "sufficiency_pct": sufficiency,
        "sufficiency_checks": [{"check": c, "weight": w, "met": s} for c, w, s in checks],
        "next_evidence": steps[:8], "next_evidence_label": NEXT_EVIDENCE_LABEL, "limits": list(RECORD_LIMITS),
        "amount_gap_pct": None if amount_gap is None else round(amount_gap * 100, 1),
    }


NEXT_EVIDENCE_LABEL = "Suggested investigation steps — not conclusions. You decide which, if any, to take."
RECORD_LIMITS = (
    "No KYC review date is supplied, so KYC currency can only be judged from the profile text.",
    "Documents the record mentions cannot be opened or checked by this application.",
    "Device, address and document identifiers are not supplied, so shared-attribute links cannot be tested.",
    "Checks that read free text (the detector narrative, the profile line) are pattern matches and can miss or over-match.",
)


def inconsistent_label(rows: list[dict]) -> str:
    return str(rows[0].get("counterparty") or "?")


def _near_duplicate(a: str, b: str) -> bool:
    ta, tb = ev.counterparty_tokens(a), ev.counterparty_tokens(b)
    if not ta or not tb or a == b:
        return False
    if ta == tb:
        return True                       # same words once corporate suffixes (Ltd / Limited / Pvt / Private) are ignored
    return len(ta) >= 2 and len(tb) >= 2 and len(ta & tb) / len(ta | tb) >= 0.8


# ── what the decision gate and the ledger consume ────────────────────────────
def gate_summary(quality: dict | None) -> dict | None:
    """The part of an assessment the decision gate acts on (None = not evaluated). Findings the gate already enforces under another
    code (no transactions at all) are listed but not counted again. Static titles only — no case text."""
    if not isinstance(quality, dict) or not quality.get("evaluated"):
        return None
    pick = lambda eff, enforced=False: [  # noqa: E731
        {"code": f["code"], "title": f["title"]} for f in quality["findings"] if f["effect"] == eff and bool(f.get("enforced_by")) == enforced]
    return {"policy_version": quality.get("policy_version"), "blocking": pick(BLOCKS_FILING), "blocking_enforced_elsewhere": pick(BLOCKS_FILING, True),
            "manual_review": pick(REQUIRES_MANUAL_REVIEW), "acknowledgement": pick(REQUIRES_ACKNOWLEDGEMENT),
            "informational": len(pick(INFORMATIONAL)), "sufficiency_pct": quality.get("sufficiency_pct")}


def stored_snapshot(quality: dict | None) -> dict | None:
    """The bounded record kept in the ledger row's provenance: codes, effects and static titles only (never case text), so a hostile
    counterparty name cannot reach the stored copy through this object."""
    if not isinstance(quality, dict) or not quality.get("evaluated"):
        return None
    return {"schema": "evidence_quality/1", "policy_version": quality.get("policy_version"), "sufficiency_pct": quality.get("sufficiency_pct"),
            "counts": dict(quality.get("counts") or {}),
            "findings": [{"code": f["code"], "effect": f["effect"], "category": f["category"], "source": f["source"], "title": f["title"]}
                         for f in quality["findings"][:30]]}
