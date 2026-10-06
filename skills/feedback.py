"""
Human feedback and model-quality loop — CAPTURE at decision time, MONITOR afterwards. Never self-modifying.

CAPTURE (`capture`, called by the ledger recorder and stored in the row's provenance as `feedback`):
  * whether the officer ACCEPTED or REJECTED the AI recommendation — derived from the decision itself, never typed;
  * the override reason (already stored as `override_reason`) and a STRUCTURED closure / deferral reason code (optional);
  * whether an AI draft was generated and whether it was adopted verbatim (a hash comparison; the draft text is not stored).

MONITOR (`summarise_feedback`, read-only, programme level, used by a dashboard page and a CLI):
  AI agreement · override · unsupported-claim (officer text, and AI factors) · false-positive PROXY · investigation rework · recurring
  evidence gaps · closure-reason mix · downstream outcomes (only where an outcome feed exists).

THE RULE THIS MODULE EXISTS TO KEEP
  Feedback is used for MONITORING and for a human-led, documented FUTURE CALIBRATION. Nothing here retrains a model, edits a prompt, moves
  a weight or changes a gate. The only function other modules may call is `capture` (to write); `summarise_feedback` is read by the
  dashboard and the CLI only — tests/test_feedback.py reads the source of every decision-path module to prove it. A change to the
  priority weights, a gate condition or a prompt is a reviewed code change with its own version bump, never an automatic consequence.

NON-NEGOTIABLE (same stance as skills/review_monitor.py): no per-officer scores, no league tables. `group_by` is for period / alert type /
cohort only. Every metric carries a caveat; a "proxy" says it is one.

Pure functions over rows; nothing here reads or writes the database.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any, Callable, Iterable

from skills.ledger import is_override

SCHEMA = "decision_feedback/1"
USE = "monitoring_and_future_calibration_only"
CALIBRATION_POLICY = ("Feedback figures are for monitoring and for a human-led, documented calibration review. They never retrain a model, "
                      "change a prompt, move a priority weight or alter a gate condition automatically.")

# ── structured reasons (product taxonomy, not a regulatory classification) ────────────────────────────
CLOSURE_REASONS = {
    "DOCUMENTED_LEGITIMATE_SOURCE": "Source of funds documented and consistent with the profile",
    "DOCUMENTED_LEGITIMATE_PURPOSE": "Purpose of the transfers documented",
    "DETECTOR_SIGNAL_NOT_CORROBORATED": "Detector signal not corroborated by the record after review",
    "PATTERN_EXPLAINED_BY_PROFILE": "Pattern explained by the customer's known activity",
    "INSUFFICIENT_EVIDENCE_AFTER_INQUIRY": "Insufficient evidence after inquiry",
    "DUPLICATE_OR_ALREADY_COVERED": "Duplicate of, or already covered by, another case",
    "OTHER": "Other (explain in the rationale)",
}
DEFERRAL_REASONS = {
    "AWAITING_INTERNAL_RECORDS": "Awaiting internal records",
    "AWAITING_THIRD_PARTY_INFORMATION": "Awaiting third-party information",
    "KYC_REFRESH_PENDING": "KYC refresh pending",
    "OTHER": "Other (explain in the rationale)",
}
REASONS_BY_DISPOSITION = {"NOT_FILE": CLOSURE_REASONS, "ESCALATE": CLOSURE_REASONS, "DEFERRED": DEFERRAL_REASONS}

AI_ACCEPTED, AI_REJECTED, AI_DEFERRED_INSTEAD, AI_NO_DEFINITE, AI_NOT_USED = (
    "ACCEPTED", "REJECTED", "DEFERRED_INSTEAD", "NO_DEFINITE_RECOMMENDATION", "AI_NOT_USED")
_DEFINITE = ("FILE", "NOT_FILE")
_NO_AI = ("", "NOT_RUN", "NEEDS_MANUAL_REVIEW", "NONE")

# downstream outcomes (only where an outcome feed exists — deploy/07_decision_outcomes.sql); product taxonomy
OUTCOME_TYPES = ("STR_SUBMITTED", "STR_ACKNOWLEDGED", "STR_RETURNED_FOR_REWORK", "FIU_QUERY_RECEIVED", "LEA_REQUEST_RECEIVED",
                 "CLOSURE_CONFIRMED_BY_QA", "CLOSURE_OVERTURNED_BY_QA", "CASE_REOPENED", "NO_FURTHER_ACTION")
REWORK_OUTCOMES = frozenset({"STR_RETURNED_FOR_REWORK", "CLOSURE_OVERTURNED_BY_QA", "CASE_REOPENED"})

OUTCOMES_TABLE = "FIU_COPILOT.AUDIT.DECISION_OUTCOMES"
OUTCOMES_SQL = f"""SELECT DECISION_ID, ALERT_ID, OUTCOME_TYPE, TO_VARCHAR(OUTCOME_AT) AS OUTCOME_AT, SOURCE_SYSTEM
FROM {OUTCOMES_TABLE} ORDER BY OUTCOME_AT"""


def reasons_for(disposition: str) -> dict:
    return dict(REASONS_BY_DISPOSITION.get(disposition, {}))


def ai_response(ai_recommendation: str | None, disposition: str) -> str:
    """How the decision relates to the AI recommendation — derived, never typed."""
    rec = (ai_recommendation or "").upper()
    if rec in _NO_AI:
        return AI_NOT_USED
    if is_override(ai_recommendation, disposition):
        return AI_REJECTED
    if rec in _DEFINITE:
        return AI_ACCEPTED if rec == disposition else AI_DEFERRED_INSTEAD
    return AI_NO_DEFINITE


def capture(*, disposition: str, ai_recommendation: str | None, closure_reason_code: str | None = None, ai_draft_generated: bool = False,
            ai_draft_sha256: str | None = None, final_text_sha256: str | None = None) -> dict:
    """The bounded `feedback` object stored in provenance. An unknown reason code is stored as None (never as free text)."""
    code = closure_reason_code if closure_reason_code in reasons_for(disposition) else None
    adopted = None
    if ai_draft_generated and ai_draft_sha256 and final_text_sha256:
        adopted = ai_draft_sha256 == final_text_sha256
    rec = " ".join(str(ai_recommendation or "NOT_RUN").split())[:40]
    return {"schema": SCHEMA, "use": USE, "ai_recommendation": rec, "ai_response": ai_response(ai_recommendation, disposition),
            "reason_code": code, "reason_stated": code is not None,
            "ai_draft": {"generated": bool(ai_draft_generated), "adopted_verbatim": adopted}}


# ── monitoring ───────────────────────────────────────────────────────────────
METRICS: dict[str, tuple[str, str]] = {
    "ai_agreement_rate": ("Decisions that follow a definite AI recommendation",
                          "Agreement is not accuracy. A high rate can mean good recommendations or anchoring; a low rate can mean either. Never a quality score."),
    "override_rate": ("Decisions that override the AI recommendation",
                      "An override is a recorded, reasoned disagreement and is the system working. A very low rate warrants sampling for anchoring."),
    "unsupported_claim_rate_officer": ("Closures or deferrals whose rationale states facts not in the record",
                                       "Recorded as written, not as verified. A filing cannot be recorded with such facts, so this is measured on non-filings only."),
    "unsupported_claim_rate_ai": ("Triggered AI factors whose evidence could not be grounded in the record",
                                  "Ungrounded factors do not count toward a FILE recommendation. This rate is a model-quality signal, not an officer signal."),
    "false_positive_proxy_rate": ("Decided alerts closed without a filing",
                                  "A PROXY. A closure is not a confirmed false positive; it is the officer's documented decision. It becomes a measurement only with a QA outcome feed."),
    "rework_rate": ("Alerts decided again after a concluding decision",
                    "A deferral followed by a final decision is the intended path and is not rework. Outcome-based rework needs the outcome feed."),
    "closure_reason_stated_rate": ("Closures and deferrals with a structured reason",
                                   "Rows recorded before the reason field existed count as not stated. Read against the date the field was introduced."),
}
DISCLAIMER = ("Programme-level monitoring for second-line and model-risk review. It is not an officer scorecard, not proof of model accuracy, and not "
              "an input to any decision, priority score or gate. " + CALIBRATION_POLICY)


def _meta(row: dict) -> dict:
    m = row.get("META_TEXT") if "META_TEXT" in row else row.get("metadata", row.get("METADATA_JSON"))
    if isinstance(m, str):
        try:
            m = json.loads(m)
        except ValueError:
            return {}
    return m if isinstance(m, dict) else {}


def _rate(num: int, den: int, caveat: str, **extra) -> dict:
    return {"rate": round(num / den, 3) if den else None, "numerator": num, "denominator": den, "caveat": caveat, **extra}


def _day(value: Any) -> str:
    return str(value or "")[:10]


def summarise_feedback(ledger_rows: Iterable[dict], outcomes: list[dict] | None = None, *, group_by: Callable[[dict], str] | None = None) -> dict:
    """Aggregate feedback metrics over ledger rows ({DISPOSITION, ALERT_ID, DECISION_MADE_AT, META_TEXT|METADATA_JSON}).

    `outcomes` = rows of OUTCOMES_SQL, or None when no outcome feed is provisioned (reported, never inferred).
    `group_by(row)` groups by period / alert type / cohort ONLY — never by an individual officer. Returns {groups, metric_labels, outcomes, disclaimer}."""
    rows = list(ledger_rows)
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault("all" if group_by is None else str(group_by(r)), []).append(r)
    out_by_decision = {}
    for o in outcomes or []:
        out_by_decision.setdefault(str(o.get("DECISION_ID")), []).append(o)
    return {"groups": {k: _group(v, outcomes, out_by_decision) for k, v in groups.items()},
            "metric_labels": {k: v[0] for k, v in METRICS.items()}, "outcomes_available": outcomes is not None,
            "disclaimer": DISCLAIMER, "calibration_policy": CALIBRATION_POLICY}


def _group(rows: list[dict], outcomes: list[dict] | None, out_by_decision: dict) -> dict:
    c = Counter()
    gaps_factor, gaps_quality, reasons = Counter(), Counter(), Counter()
    by_alert: dict[str, list[tuple[str, str]]] = {}
    legacy = 0
    for r in rows:
        meta = _meta(r)
        disp = (r.get("DISPOSITION") or r.get("disposition") or "").upper()
        aid = str(r.get("ALERT_ID") or r.get("alert_id") or "")
        by_alert.setdefault(aid, []).append((_day(r.get("DECISION_MADE_AT")), disp))
        c["decisions"] += 1
        if not meta.get("schema_version"):
            legacy += 1
            continue
        c["with_provenance"] += 1
        fb = meta.get("feedback") if isinstance(meta.get("feedback"), dict) else {}
        resp = fb.get("ai_response") or ai_response(meta.get("ai_recommendation"), meta.get("human_decision") or disp)
        c[f"ai_{resp}"] += 1
        if resp != AI_NOT_USED:
            c["ai_ran"] += 1
            if meta.get("override") is True:
                c["overrides"] += 1
        codes = {x.get("code") for x in ((meta.get("defensibility_gate") or {}).get("conditions") or []) if isinstance(x, dict)}
        if disp in ("NOT_FILE", "ESCALATE", "DEFERRED"):
            c["non_file"] += 1
            if "UNSUPPORTED_FACTS_IN_RATIONALE" in codes:
                c["non_file_unsupported"] += 1
            if fb.get("reason_stated"):
                c["reason_stated"] += 1
                reasons[str(fb.get("reason_code"))] += 1
            else:
                reasons["NOT_STATED"] += 1
        for f in meta.get("poe_assessment") or []:
            if isinstance(f, dict) and f.get("assessment") == "triggered":
                c["ai_triggered"] += 1
                if f.get("grounded") is False:
                    c["ai_ungrounded"] += 1
        for fid in (meta.get("challenge") or {}).get("open_gap_factors") or []:
            gaps_factor[str(fid)[:20]] += 1
        for fnd in (meta.get("evidence_quality") or {}).get("findings") or []:
            if isinstance(fnd, dict) and fnd.get("code"):
                gaps_quality[str(fnd["code"])[:60]] += 1
        if disp in ("FILE", "NOT_FILE", "ESCALATE"):
            c["concluding"] += 1
            if disp == "NOT_FILE":
                c["closures"] += 1
    # rework: an alert with a concluding decision followed by ANY later decision
    concluded = reworked = 0
    for aid, seq in by_alert.items():
        seq.sort()
        first = next((i for i, (_, d) in enumerate(seq) if d in ("FILE", "NOT_FILE", "ESCALATE")), None)
        if first is not None:
            concluded += 1
            reworked += 1 if len(seq) > first + 1 else 0
    definite = c["ai_ACCEPTED"] + c["ai_REJECTED"] + c["ai_DEFERRED_INSTEAD"]
    res = {
        "total_decisions": c["decisions"], "decisions_without_provenance": legacy,
        "ai_agreement_rate": _rate(c["ai_ACCEPTED"], definite, METRICS["ai_agreement_rate"][1]),
        "override_rate": _rate(c["overrides"], c["ai_ran"], METRICS["override_rate"][1]),
        "unsupported_claim_rate_officer": _rate(c["non_file_unsupported"], c["non_file"], METRICS["unsupported_claim_rate_officer"][1]),
        "unsupported_claim_rate_ai": _rate(c["ai_ungrounded"], c["ai_triggered"], METRICS["unsupported_claim_rate_ai"][1]),
        "false_positive_proxy_rate": _rate(c["closures"], c["concluding"], METRICS["false_positive_proxy_rate"][1], is_proxy=True),
        "rework_rate": _rate(reworked, concluded, METRICS["rework_rate"][1]),
        "closure_reason_stated_rate": _rate(c["reason_stated"], c["non_file"], METRICS["closure_reason_stated_rate"][1]),
        "closure_reason_mix": dict(reasons.most_common()),
        "recurring_evidence_gaps": {
            "ai_factor_gaps": [{"factor_id": k, "decisions": n} for k, n in gaps_factor.most_common(10)],
            "record_quality_findings": [{"code": k, "decisions": n} for k, n in gaps_quality.most_common(10)],
            "caveat": "Counts of decisions that carried the gap. A gap can be defensible; the point is whether it recurs and whether it was addressed.",
        },
    }
    if outcomes is None:
        res["outcomes"] = {"available": False, "reason": "No outcome feed is provisioned (deploy/07_decision_outcomes.sql is opt-in); downstream outcomes are not inferred."}
    else:
        ids = {str(r.get("DECISION_ID")) for r in rows}
        mine = [o for d, os_ in out_by_decision.items() if d in ids for o in os_]
        types = Counter(str(o.get("OUTCOME_TYPE")) for o in mine)
        qa = [o for o in mine if o.get("OUTCOME_TYPE") in ("CLOSURE_CONFIRMED_BY_QA", "CLOSURE_OVERTURNED_BY_QA")]
        res["outcomes"] = {
            "available": True, "by_type": dict(types), "decisions_with_outcome": len({str(o.get("DECISION_ID")) for o in mine}),
            "outcome_rework": _rate(sum(1 for o in mine if o.get("OUTCOME_TYPE") in REWORK_OUTCOMES), len({str(o.get("DECISION_ID")) for o in mine}),
                                    "Decisions with at least one rework outcome ÷ decisions with any outcome."),
            "qa_confirmed_closure_rate": _rate(sum(1 for o in qa if o["OUTCOME_TYPE"] == "CLOSURE_CONFIRMED_BY_QA"), len(qa),
                                               "Closures a QA reviewer confirmed ÷ closures a QA reviewer reviewed. The only adjudicated false-positive signal."),
        }
    return res
