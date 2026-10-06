"""
Case prioritisation — a transparent, deterministic WORKLOAD-ORDERING score for the alert queue.

  priority  ≠  decision.
  The score says "look at this case sooner". It is NOT a risk rating of the customer, NOT a probability that suspicion is justified,
  and NOT a recommendation to file or not to file. The FILE / NOT_FILE decision is made by the Principal Officer, through the
  decision-defensibility gate, from the evidence and the regulatory basis — nothing in this module is an input to that gate, and
  nothing in the gate is an input to this module. (tests/test_prioritisation.py checks both directions by reading the imports.)

HOW THE SCORE IS BUILT — nine factors, weights summing to 100, every one a fixed table or band below:

    signal severity         15   the signal source and type, from the SEVERITY policy table (product policy, not a regulatory ranking)
    alert amount            14   banded
    flagged counterparties  12   how many counterparties carry a flag in the record
    suspicious flow         14   share of credits that went to flagged counterparties
    pass-through ratio       6   share of credits sent onward
    reporting deadline      15   working days left on the 7-WD clock — ONLY where a suspicion time was recorded; otherwise 0 and said so
    case age                 8   calendar days since the alert date (a reference, not the legal clock)
    evidence sufficiency     8   how decision-ready the record is (skills/evidence_quality.py): ready work is surfaced
    missing-data risk        8   gaps that block or delay a defensible decision: they take time, so those cases should start early

Every factor returns its points, its maximum, the inputs it used and one plain sentence. The explanation is assembled from those
sentences with fixed templates — no model is involved. Nothing is inferred when an input is absent: the factor scores 0 and the
sentence says what was missing.

No learning: the weights and bands are constants in this file. Feedback data (skills/feedback.py) is monitoring only and is not read here.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from skills.evidence_quality import BLOCKS_FILING, INFORMATIONAL, REQUIRES_ACKNOWLEDGEMENT, REQUIRES_MANUAL_REVIEW

POLICY_VERSION = "1"

WEIGHTS = {
    "severity": 15, "amount": 14, "flagged_counterparties": 12, "suspicious_flow": 14, "pass_through": 6,
    "deadline": 15, "case_age": 8, "evidence_sufficiency": 8, "missing_data": 8,
}
assert sum(WEIGHTS.values()) == 100

BANDS = (("Critical", 65), ("High", 45), ("Medium", 25), ("Low", 0))     # score ≥ threshold

DISCLAIMER = ("Priority orders the work; it is not a risk rating, not a probability of suspicion and not a recommendation to file. "
              "The decision to file or not is yours and is recorded separately.")

# Signal severity is PRODUCT POLICY (a configurable table), not a regulatory ranking. Source tiers and type tiers are added.
SOURCE_POINTS = {"I4C": 7, "MULE_HUNTER": 7, "DPIP": 7, "INTERNAL_RULE": 3}
SOURCE_UNKNOWN_POINTS = 2
TYPE_TIER_1 = frozenset({"MULE_PASSTHROUGH", "DEVICE_IDENTITY_LINKAGE", "BENEFICIARY_CONCENTRATION", "ATTEMPTED_SWIFT", "CROSS_BORDER_FATF", "PEP_INCONSISTENCY"})
TYPE_TIER_2 = frozenset({"STRUCTURING", "NPO_MISUSE", "FIDUCIARY_DIVERSION", "MF_LAYERING", "DORMANT_REACTIVATION"})
TYPE_POINTS = {1: 8, 2: 5, 3: 2}          # tier 3 = any other type (e.g. a large-value or income-inconsistency rule)

AMOUNT_BANDS = ((10_000_000, 14), (2_500_000, 11), (500_000, 8), (100_000, 5), (0, 2))   # (≥ rupees, points)
FLAGGED_COUNT_POINTS = {0: 0, 1: 8, 2: 11}          # 3 or more → 12
FLOW_BANDS = ((75, 14), (50, 10), (25, 6), (0.0001, 3))        # (≥ percent of credits, points)
PASS_THROUGH_BANDS = ((90, 6), (70, 4), (50, 2))
DEADLINE_POINTS = ((0, 15), (1, 13), (3, 10), (5, 6))          # (≤ working days left, points); more than 5 left = 3
DEADLINE_FAR_POINTS = 3
AGE_BANDS = ((45, 8), (30, 7), (21, 5), (14, 4), (7, 2), (3, 1))        # (≥ calendar days, points)
MISSING_DATA_POINTS = {BLOCKS_FILING: 4, REQUIRES_MANUAL_REVIEW: 3, REQUIRES_ACKNOWLEDGEMENT: 2, INFORMATIONAL: 0}


def _to_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _inr(v: float) -> str:
    return f"₹{float(v):,.0f}"


def _title(s: Any) -> str:
    return str(s or "").replace("_", " ").title()


def _band(points_table, value):
    for threshold, pts in points_table:
        if value >= threshold:
            return pts
    return 0


def _factor(fid: str, label: str, points: int, detail: str, note: str | None = None, **inputs) -> dict:
    mx = WEIGHTS[fid]
    return {"id": fid, "label": label, "points": min(int(points), mx), "max_points": mx, "detail": detail, "note": note, "inputs": inputs}


def band_for(score: int) -> str:
    return next(name for name, threshold in BANDS if score >= threshold)


def prioritise(alert: dict, brief: dict | None, quality: dict | None, *, sla_days_remaining: int | None = None,
               now: date | datetime | None = None) -> dict:
    """Score one case.

    alert     the ALERTS_CURRENT row            brief   skills.evidence.signal_brief(transactions), or None if there are none
    quality   skills.evidence_quality.assess()   sla_days_remaining   working days left, or None where no suspicion time was recorded
    Returns {score, band, factors[], drivers[], explanation, data_gaps[], policy_version, disclaimer}. Deterministic."""
    alert = alert or {}
    today = _to_date(now) or date.today()
    factors: list[dict] = []
    gaps: list[str] = []

    # 1 — signal severity (policy table)
    source, atype = str(alert.get("SIGNAL_SOURCE") or "").upper(), str(alert.get("ALERT_TYPE") or "").upper()
    tier = 1 if atype in TYPE_TIER_1 else 2 if atype in TYPE_TIER_2 else 3
    s_pts = SOURCE_POINTS.get(source, SOURCE_UNKNOWN_POINTS) + TYPE_POINTS[tier]
    registry = source in ("I4C", "MULE_HUNTER", "DPIP")
    factors.append(_factor("severity", "Signal severity", s_pts,
                           f"{'Registry-sourced' if registry else 'Internal-rule' if source == 'INTERNAL_RULE' else 'Unclassified-source'} signal "
                           f"({_title(source) if source else 'source not stated'}), type {_title(atype) or 'not stated'} — tier {tier} in this product's severity table.",
                           note="The severity table is a configurable ordering rule of this product, not a regulatory ranking.", source=source or None, alert_type=atype or None, tier=tier))

    # 2 — alert amount
    try:
        amount = float(alert.get("ALERT_AMOUNT_INR"))
    except (TypeError, ValueError):
        amount = None
        gaps.append("The alert amount is not recorded.")
    a_pts = _band(AMOUNT_BANDS, amount) if amount is not None else 0
    factors.append(_factor("amount", "Alert amount", a_pts, f"Alert amount {_inr(amount)}." if amount is not None else "No alert amount is recorded, so it adds nothing.",
                           amount_inr=amount))

    # 3–5 — what the transaction record shows
    if not brief or not brief.get("txn_count"):
        gaps.append("No transaction record, so counterparty and flow factors score 0.")
        factors.append(_factor("flagged_counterparties", "Flagged counterparties", 0, "No transactions are on record, so no flag can be counted."))
        factors.append(_factor("suspicious_flow", "Suspicious flow", 0, "No transactions are on record, so the flagged share of credits is unknown."))
        factors.append(_factor("pass_through", "Pass-through ratio", 0, "No transactions are on record, so the onward share is unknown."))
    else:
        n_flag = len(brief.get("flagged_counterparties") or [])
        f_pts = FLAGGED_COUNT_POINTS.get(n_flag, WEIGHTS["flagged_counterparties"])
        factors.append(_factor("flagged_counterparties", "Flagged counterparties", f_pts,
                               (f"{n_flag} counterpart{'y carries' if n_flag == 1 else 'ies carry'} a flag in the record." if n_flag else
                                "No counterparty carries a flag in the record (this is not a clearance: a flag may simply not have been applied)."),
                               flagged=n_flag))
        credit = float(brief.get("total_credit") or 0)
        share = brief.get("flagged_debit_share_pct")
        if share is None:
            gaps.append("No credits on record, so the flagged share of credits cannot be computed.")
            factors.append(_factor("suspicious_flow", "Suspicious flow", 0, "There are no credit rows, so a share of credits cannot be computed."))
        else:
            if share:
                flow_detail = f"{share:.1f}% of credits received ({_inr(brief.get('flagged_debit_total') or 0)} of {_inr(credit)}) went to flagged counterparties."
            elif int(brief.get("flagged_txn_count") or 0):
                flow_detail = "A flag is recorded on a row, but no debit to a flagged counterparty is recorded, so no flagged onward flow is scored."
            else:
                flow_detail = "None of the credits went on to a flagged counterparty."
            factors.append(_factor("suspicious_flow", "Suspicious flow", _band(FLOW_BANDS, share), flow_detail, flagged_debit_share_pct=share))
        onward = brief.get("onward_ratio_pct")
        if onward is None:
            factors.append(_factor("pass_through", "Pass-through ratio", 0, "There are no credit rows, so the onward share cannot be computed."))
        else:
            factors.append(_factor("pass_through", "Pass-through ratio", _band(PASS_THROUGH_BANDS, onward),
                                   f"{onward:.1f}% of credits received were sent onward ({_inr(brief.get('total_debit') or 0)} of {_inr(credit)}).", onward_ratio_pct=onward))

    # 6 — reporting deadline: only a RECORDED suspicion time starts a clock
    if sla_days_remaining is None:
        d_pts, d_detail = 0, ("No suspicion time is recorded, so no reporting deadline is scored. Record when suspicion formed to start the 7-working-day clock; "
                              "case age below is a reference only.")
        gaps.append("No suspicion time is recorded, so the reporting deadline is not scored.")
    elif sla_days_remaining < 0:
        d_pts, d_detail = DEADLINE_POINTS[0][1], f"The 7-working-day window is overdue by {-sla_days_remaining} working day(s)."
    else:
        d_pts = next((pts for limit, pts in DEADLINE_POINTS if sla_days_remaining <= limit), DEADLINE_FAR_POINTS)
        d_detail = ("The 7-working-day window ends today." if sla_days_remaining == 0 else f"{sla_days_remaining} working day(s) left on the 7-working-day window.")
    factors.append(_factor("deadline", "Reporting deadline", d_pts, d_detail, sla_days_remaining=sla_days_remaining))

    # 7 — case age (calendar days since the alert date)
    alert_date = _to_date(alert.get("ALERT_DATE"))
    if alert_date is None:
        age, ag_pts = None, 0
        gaps.append("The alert date is not recorded, so case age is not scored.")
        ag_detail = "The alert date is not recorded, so age adds nothing."
    else:
        age = max(0, (today - alert_date).days)
        ag_pts = _band(AGE_BANDS, age)
        ag_detail = f"The alert is {age} calendar day(s) old (a reference; the legal clock starts at the recorded suspicion time)."
    factors.append(_factor("case_age", "Case age", ag_pts, ag_detail, age_days=age))

    # 8–9 — what the record is ready for, and what is missing
    if not isinstance(quality, dict) or not quality.get("evaluated"):
        gaps.append("Evidence quality was not assessed, so sufficiency and missing-data risk score 0.")
        factors.append(_factor("evidence_sufficiency", "Evidence sufficiency", 0, "Evidence quality was not assessed."))
        factors.append(_factor("missing_data", "Missing-data risk", 0, "Evidence quality was not assessed."))
    else:
        pct = int(quality.get("sufficiency_pct") or 0)
        factors.append(_factor("evidence_sufficiency", "Evidence sufficiency", round(WEIGHTS["evidence_sufficiency"] * pct / 100),
                               f"The record is {pct}% decision-ready, so this case can be worked now." if pct >= 75 else
                               f"The record is {pct}% decision-ready; the sufficiency factor adds little until gaps are closed.", sufficiency_pct=pct))
        counts = quality.get("counts") or {}
        m_pts = sum(MISSING_DATA_POINTS[e] * int(counts.get(e, 0)) for e in MISSING_DATA_POINTS)
        needs = int(counts.get(BLOCKS_FILING, 0)) + int(counts.get(REQUIRES_MANUAL_REVIEW, 0)) + int(counts.get(REQUIRES_ACKNOWLEDGEMENT, 0))
        factors.append(_factor("missing_data", "Missing-data risk", min(m_pts, WEIGHTS["missing_data"]),
                               (f"{needs} evidence issue(s) must be resolved or acknowledged before a defensible decision; they take time, so work starts early." if needs
                                else "No evidence issue gates a decision."), blocking=int(counts.get(BLOCKS_FILING, 0)),
                               manual_review=int(counts.get(REQUIRES_MANUAL_REVIEW, 0)), acknowledgement=int(counts.get(REQUIRES_ACKNOWLEDGEMENT, 0))))

    score = sum(f["points"] for f in factors)
    ranked = sorted((f for f in factors if f["points"] > 0), key=lambda f: (-f["points"], list(WEIGHTS).index(f["id"])))
    drivers = [{"id": f["id"], "label": f["label"], "points": f["points"], "detail": f["detail"]} for f in ranked[:3]]
    band = band_for(score)
    if drivers:
        lines = "; ".join(f"{d['detail'].rstrip('.')} (+{d['points']})" for d in drivers)
        explanation = f"Priority {score}/100 ({band}). Main drivers: {lines}."
    else:
        explanation = f"Priority {score}/100 ({band}). No factor adds points on the data available."
    return {"score": score, "band": band, "factors": factors, "drivers": drivers, "explanation": explanation, "data_gaps": gaps,
            "policy_version": POLICY_VERSION, "disclaimer": DISCLAIMER}


def sort_key(item: dict) -> tuple:
    """Highest score first; ties by earlier alert date, then larger amount, then alert id (stable and explainable).
    `item` = {"alert": row, "priority": prioritise(...)}"""
    alert = item.get("alert") or {}
    try:
        amount = float(alert.get("ALERT_AMOUNT_INR") or 0)
    except (TypeError, ValueError):
        amount = 0.0
    return (-item["priority"]["score"], str(_to_date(alert.get("ALERT_DATE")) or "9999-12-31"), -amount, str(alert.get("ALERT_ID") or ""))
