"""
KPI and business-value model — what can be measured now, what is only a proxy, what is not measurable yet, and what is simulated.

Every KPI carries one STATUS, and the dashboard shows it next to the number:

    MEASURED          computed from the ledger or the case record; the definition and its caveat are stated
    PROXY             a stand-in for the thing named (the name says so); read the caveat before using it
    SYNTHETIC_LABELS  computed against the seed data's GOLD_DISPOSITION — the scenario author's labels, NOT adjudicated outcomes. Shows that the
                      computation works; says nothing about real-world accuracy
    NOT_MEASURED      the inputs do not exist yet (for example hands-on time needs interaction telemetry); `needs` says what they are
    SIMULATED         a number from the deterministic demonstration cohort below; illustrative only, never a measurement

BUSINESS VALUE is not claimed here. A claim of improvement needs a BASELINE measured the same way over a comparable period with enough cases;
`improvement()` returns `allowed=False` and a reason unless that is true, and the dashboard shows no percentage-improvement figure otherwise.
Nothing in this module reads a number from a marketing deck: every figure is computed from rows or labelled simulated.

Programme-level only — no per-officer KPIs (same stance as skills/review_monitor.py and skills/feedback.py).
Pure functions over rows; nothing here reads or writes the database.
"""

from __future__ import annotations

import json
import math
import random
import statistics
from datetime import date
from typing import Any, Iterable

from skills import feedback as fb
from skills.ledger import evidence_snapshot_sha256, to_ist_date, working_days_elapsed

MEASURED, PROXY, SYNTHETIC_LABELS, NOT_MEASURED, SIMULATED = "MEASURED", "PROXY", "SYNTHETIC_LABELS", "NOT_MEASURED", "SIMULATED"
STATUS_MEANING = {
    MEASURED: "Computed from the ledger or the case record.",
    PROXY: "A stand-in for the thing named; read the caveat.",
    SYNTHETIC_LABELS: "Computed against the seed data's scenario labels, not adjudicated outcomes.",
    NOT_MEASURED: "The inputs do not exist yet.",
    SIMULATED: "Illustrative number from a deterministic demonstration cohort. Not a measurement.",
}
MIN_CASES_FOR_A_CLAIM = 30
CLAIMS_POLICY = ("No improvement is claimed. A claim needs a baseline measured the same way over a comparable period, with at least "
                 f"{MIN_CASES_FOR_A_CLAIM} cases in each period. Until then these are definitions and, where the data exists, current values.")
_EMPTY_EVIDENCE_SHA = evidence_snapshot_sha256([])


# ── statistics (stated methods) ──────────────────────────────────────────────
def median(values: list[float]) -> float | None:
    return float(statistics.median(values)) if values else None


def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile: the smallest value such that at least p % of the values are ≤ it. (Median uses the usual midpoint rule.)"""
    if not values:
        return None
    ordered = sorted(values)
    return float(ordered[max(1, math.ceil(p / 100 * len(ordered))) - 1])


def confusion(pairs: Iterable[tuple[str, str]]) -> dict:
    """pairs = (decision, label), each FILE or NOT_FILE. Positive class = FILE."""
    tp = fp = fn = tn = 0
    for d, label in pairs:
        if d == "FILE" and label == "FILE":
            tp += 1
        elif d == "FILE":
            fp += 1
        elif label == "FILE":
            fn += 1
        else:
            tn += 1
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    f1 = (2 * prec * rec / (prec + rec)) if prec is not None and rec is not None and (prec + rec) else None
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "n": tp + fp + fn + tn, "precision": prec, "recall": rec, "f1": f1}


def improvement(baseline: dict | None, current: dict | None, *, higher_is_better: bool, min_n: int = MIN_CASES_FOR_A_CLAIM) -> dict:
    """May an improvement be stated? baseline/current = {"value", "n", "definition"} measured the same way. Returns {allowed, reason, delta, pct}.
    Refuses without a baseline, with a different definition, or with fewer than `min_n` cases in either period."""
    def bad(reason: str) -> dict:
        return {"allowed": False, "reason": reason, "delta": None, "pct": None}
    if not baseline or baseline.get("value") is None:
        return bad("No baseline has been captured, so no improvement can be claimed.")
    if not current or current.get("value") is None:
        return bad("There is no current measurement.")
    if baseline.get("definition") != current.get("definition"):
        return bad("The baseline and the current value are not defined the same way.")
    if int(baseline.get("n") or 0) < min_n or int(current.get("n") or 0) < min_n:
        return bad(f"Fewer than {min_n} cases in the baseline or the current period; the difference could be noise.")
    delta = float(current["value"]) - float(baseline["value"])
    pct = (delta / float(baseline["value"]) * 100) if float(baseline["value"]) else None
    better = delta > 0 if higher_is_better else delta < 0
    return {"allowed": True, "reason": "Baseline and current are defined alike and each has enough cases. This is a difference, not proof of cause.",
            "delta": delta, "pct": pct, "direction": "better" if better else ("worse" if delta else "unchanged")}


# ── helpers over ledger rows ─────────────────────────────────────────────────
def _meta(row: dict) -> dict:
    m = row.get("META_TEXT") if "META_TEXT" in row else row.get("metadata", row.get("METADATA_JSON"))
    if isinstance(m, str):
        try:
            m = json.loads(m)
        except ValueError:
            return {}
    return m if isinstance(m, dict) else {}


def _date(value: Any) -> date | None:
    try:
        return to_ist_date(value)
    except (ValueError, TypeError):
        return None


def _kpi(kid: str, name: str, status: str, *, value=None, display: str = "—", n: int | None = None, definition: str, source: str, caveat: str,
         needs: str | None = None, extra: dict | None = None) -> dict:
    return {"id": kid, "name": name, "status": status, "status_meaning": STATUS_MEANING[status], "value": value, "display": display, "n": n,
            "definition": definition, "source": source, "caveat": caveat, "needs": needs, **(extra or {})}


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:.0f}%"


def compute_kpis(ledger_rows: list[dict], alert_rows: list[dict] | None = None, *, outcomes: list[dict] | None = None,
                 open_case_quality: list[dict] | None = None) -> dict:
    """The KPI set for the programme. `ledger_rows` = {DISPOSITION, ALERT_ID, DECISION_MADE_AT, SUSPICION_FORMED_AT, SLA_DAYS_REMAINING, META_TEXT};
    `alert_rows` = {ALERT_ID, ALERT_DATE, GOLD_DISPOSITION}; `open_case_quality` = evidence_quality.assess() results for open alerts."""
    rows = list(ledger_rows)
    alerts = {str(a.get("ALERT_ID")): a for a in (alert_rows or [])}
    feedback = fb.summarise_feedback(rows, outcomes)["groups"].get("all") or fb.summarise_feedback([], outcomes)["groups"].get("all") or {}
    concl = [r for r in rows if (r.get("DISPOSITION") or "").upper() in ("FILE", "NOT_FILE", "ESCALATE")]
    last_by_alert: dict[str, dict] = {}
    for r in sorted(concl, key=lambda r: str(r.get("DECISION_MADE_AT"))):
        last_by_alert[str(r.get("ALERT_ID"))] = r
    out: list[dict] = []

    # 1 — alert-to-decision elapsed time (calendar days)
    elapsed = []
    for aid, r in last_by_alert.items():
        a, d = _date(alerts.get(aid, {}).get("ALERT_DATE")), _date(r.get("DECISION_MADE_AT"))
        if a and d and d >= a:
            elapsed.append((d - a).days)
    out.append(_kpi("alert_to_decision_median_days", "Alert-to-decision elapsed time — median (calendar days)", MEASURED if elapsed else NOT_MEASURED,
                    value=median(elapsed), display=f"{median(elapsed):.1f} d" if elapsed else "—", n=len(elapsed),
                    definition="Calendar days from the alert date to the latest concluding decision, per decided alert.", source="ALERTS_CURRENT.ALERT_DATE, DECISION_LEDGER.DECISION_MADE_AT",
                    caveat="This is ELAPSED time including queue wait and weekends. It is not investigation time and not analyst working time. Alert dates in the demo are synthetic.",
                    needs=None if elapsed else "At least one decided alert with an alert date."))
    out.append(_kpi("alert_to_decision_p95_days", "Alert-to-decision elapsed time — p95 (calendar days)", MEASURED if elapsed else NOT_MEASURED,
                    value=percentile(elapsed, 95), display=f"{percentile(elapsed, 95):.0f} d" if elapsed else "—", n=len(elapsed),
                    definition="Nearest-rank 95th percentile of the same distribution.", source="as above",
                    caveat="With few decided alerts the p95 is just the largest value; read it with n.", needs=None if elapsed else "At least one decided alert."))

    # 2/3 — time on the desk: a browser-session proxy where the decision carries one, otherwise not measurable
    desk = [int(d["hands_on_upper_bound_seconds"]) for d in (_meta(r).get("desk_session") for r in rows)
            if isinstance(d, dict) and isinstance(d.get("hands_on_upper_bound_seconds"), (int, float))]
    if desk:
        med, p90 = median(desk), percentile(desk, 90)
        fmt = lambda sec: f"{sec / 60:.1f} min"  # noqa: E731
        out.append(_kpi("investigation_time", "Time on the desk per decision — median and p90 (session proxy)", PROXY, value=med, display=f"{fmt(med)} (p90 {fmt(p90)})", n=len(desk),
                        definition="Seconds from first opening the case on the Investigation desk to the click that recorded the decision, minus the time spent waiting for a model.",
                        source="DECISION_LEDGER.METADATA_JSON.desk_session",
                        caveat=(f"{len(rows) - len(desk)} decision(s) carry no desk-session measurement (recorded before it existed, or by another client) and are excluded. "
                                "A browser session includes idle time and a tab left open and excludes any work outside the application, so it is an UPPER BOUND on hands-on "
                                "time, not a time-and-motion study. No baseline exists, so no improvement is claimed from it."),
                        needs="A baseline period measured the same way (at least 30 decisions), and server-side events with idle-time handling, before this can carry a claim."))
    else:
        out.append(_kpi("investigation_time", "Investigation time — median and p95 (hands-on)", NOT_MEASURED,
                        definition="Time an officer actively works a case, from first opening it to recording the decision, excluding idle time.", source="(none yet)",
                        caveat="No decision in the ledger carries a desk-session measurement: the ledger records when the decision was made, not when work began or how long it took.",
                        needs="Server-side case-open and decision timestamps per session, or case-management events, with idle-time handling. (Decisions recorded by this version "
                              "of the application carry a desk-session proxy; none is in the ledger yet.)"))
    out.append(_kpi("analyst_touch_time", "Analyst touch time", NOT_MEASURED,
                    definition="Active minutes an analyst spends on a case across sessions.", source="(none yet)",
                    caveat="Client-supplied interaction timings (skills/human_review.py) are optional, unverified and not stored for every decision.",
                    needs="Server-side interaction telemetry or case-management time tracking."))

    # 3 — alert-to-STR ratio
    filed = sum(1 for r in rows if (r.get("DISPOSITION") or "").upper() == "FILE")
    closed = sum(1 for r in rows if (r.get("DISPOSITION") or "").upper() == "NOT_FILE")
    ratio = (filed / (filed + closed)) if filed + closed else None
    out.append(_kpi("alert_to_str_ratio", "Alert-to-STR ratio", MEASURED if ratio is not None else NOT_MEASURED, value=ratio, display=_pct(ratio), n=filed + closed,
                    definition="FILE decisions ÷ (FILE + NOT_FILE decisions).", source="DECISION_LEDGER.DISPOSITION",
                    caveat="An internal governance metric: no FIU-IND benchmark is published (DG-04). It counts decisions, so a re-decided alert counts twice, and it includes any test rows in the ledger.",
                    needs=None if ratio is not None else "At least one FILE or NOT_FILE decision."))

    # 4 — false positive
    fp = feedback.get("false_positive_proxy_rate") or {}
    out.append(_kpi("false_positive_proxy_rate", "False-positive rate (proxy)", PROXY if fp.get("rate") is not None else NOT_MEASURED, value=fp.get("rate"), display=_pct(fp.get("rate")),
                    n=fp.get("denominator"), definition="NOT_FILE decisions ÷ concluding decisions. A closure is not a confirmed false positive.", source="DECISION_LEDGER",
                    caveat=fp.get("caveat", ""), needs="A QA / second-line adjudication feed (CLOSURE_CONFIRMED_BY_QA) turns this into a measurement."))
    qa = ((feedback.get("outcomes") or {}).get("qa_confirmed_closure_rate") or {}) if (feedback.get("outcomes") or {}).get("available") else {}
    out.append(_kpi("qa_confirmed_closure_rate", "Closures confirmed by QA review", MEASURED if qa.get("rate") is not None else NOT_MEASURED, value=qa.get("rate"), display=_pct(qa.get("rate")),
                    n=qa.get("denominator"), definition="Closures a QA reviewer confirmed ÷ closures a QA reviewer reviewed.", source="DECISION_OUTCOMES (opt-in feed)",
                    caveat=qa.get("caveat") or "No outcome feed is provisioned.", needs=None if qa.get("rate") is not None else "deploy/07_decision_outcomes.sql and a QA process that writes to it."))

    # 5 — precision / recall / F1 against labels
    pairs = []
    for aid, r in last_by_alert.items():
        gold = (alerts.get(aid, {}).get("GOLD_DISPOSITION") or "").upper()
        d = (r.get("DISPOSITION") or "").upper()
        if gold in ("FILE", "NOT_FILE") and d in ("FILE", "NOT_FILE"):
            pairs.append((d, gold))
    cm = confusion(pairs)
    for key, label in (("precision", "Precision"), ("recall", "Recall"), ("f1", "F1")):
        out.append(_kpi(f"{key}_vs_labels", f"{label} of filing decisions vs labels", SYNTHETIC_LABELS if cm[key] is not None else NOT_MEASURED, value=cm[key], display=_pct(cm[key]), n=cm["n"],
                        definition={"precision": "TP ÷ (TP + FP): of the alerts the officer filed, the share the label also says FILE.", "recall": "TP ÷ (TP + FN): of the alerts the label says FILE, the share the officer filed.",
                                    "f1": "Harmonic mean of precision and recall."}[key] + " Latest concluding decision per alert; CONTESTED labels and escalations excluded.",
                        source="DECISION_LEDGER × ALERT_GOLD_LABELS (admin role only; the application cannot read it)",
                        caveat="The label is the synthetic scenario author's, not an adjudicated outcome. This shows the computation; it says nothing about real-world accuracy.",
                        needs=None if cm[key] is not None else ("Decided alerts that carry a FILE / NOT_FILE label. The application role cannot read the answer key, by design: run "
                                                                "scripts/eval_label_agreement.py under an admin role, or supply adjudicated outcomes (deploy/07_decision_outcomes.sql)."),
                        extra={"confusion": cm}))

    # 6 — filing timeliness
    file_rows = [r for r in rows if (r.get("DISPOSITION") or "").upper() == "FILE" and r.get("SLA_DAYS_REMAINING") is not None]
    on_time = sum(1 for r in file_rows if int(r["SLA_DAYS_REMAINING"]) >= 0)
    out.append(_kpi("filing_timeliness", "Filing decisions made within the 7-working-day window", MEASURED if file_rows else NOT_MEASURED, value=(on_time / len(file_rows)) if file_rows else None,
                    display=_pct(on_time / len(file_rows)) if file_rows else "—", n=len(file_rows),
                    definition="FILE decisions recorded with SLA_DAYS_REMAINING ≥ 0 ÷ FILE decisions.", source="DECISION_LEDGER.SLA_DAYS_REMAINING",
                    caveat="The suspicion time is entered by the officer, Mon–Fri only, no holiday calendar. It measures when the decision was RECORDED, not when an STR reached FINGate (this application submits nothing).",
                    needs=None if file_rows else "At least one FILE decision."))

    # 7 — throughput (programme level)
    days = sorted({d for d in (_date(r.get("DECISION_MADE_AT")) for r in rows) if d})
    if len(days) >= 2:
        span = working_days_elapsed(days[0], days[-1]) + 1
        tp = len(rows) / span
    else:
        span, tp = (1, float(len(rows))) if days else (0, None)
    out.append(_kpi("analyst_throughput", "Decisions recorded per working day (programme)", MEASURED if tp is not None else NOT_MEASURED, value=tp, display=f"{tp:.1f}" if tp is not None else "—", n=len(rows),
                    definition="Decisions ÷ working days (Mon–Fri) between the first and last decision, inclusive.", source="DECISION_LEDGER.DECISION_MADE_AT",
                    caveat="Programme level, not per officer. Throughput says nothing about quality, and a short window makes it unstable.", needs=None if tp is not None else "At least one decision."))

    # 8 — override rate
    ov = feedback.get("override_rate") or {}
    out.append(_kpi("override_rate", "Override rate", MEASURED if ov.get("rate") is not None else NOT_MEASURED, value=ov.get("rate"), display=_pct(ov.get("rate")), n=ov.get("denominator"),
                    definition="Decisions that override a definite AI recommendation ÷ decisions where the AI ran.", source="DECISION_LEDGER.METADATA_JSON.override", caveat=ov.get("caveat", ""),
                    needs=None if ov.get("rate") is not None else "Decisions made after running the AI assessment."))

    # 9 — audit rework
    rw, orw = feedback.get("rework_rate") or {}, ((feedback.get("outcomes") or {}).get("outcome_rework") or {})
    use_outcome = bool((feedback.get("outcomes") or {}).get("available")) and orw.get("rate") is not None
    src = orw if use_outcome else rw
    out.append(_kpi("audit_rework_rate", "Audit / investigation rework rate", MEASURED if use_outcome else (PROXY if rw.get("rate") is not None else NOT_MEASURED), value=src.get("rate"), display=_pct(src.get("rate")),
                    n=src.get("denominator"), definition=("Decisions with a rework outcome ÷ decisions with any outcome." if use_outcome else "Alerts decided again after a concluding decision ÷ alerts with a concluding decision."),
                    source="DECISION_OUTCOMES" if use_outcome else "DECISION_LEDGER", caveat=src.get("caveat", ""),
                    needs=None if use_outcome else "An outcome feed (STR returned for rework, closure overturned by QA) turns this proxy into a measurement."))

    # 10 — complete evidence and regulatory basis
    prov = [(r, _meta(r)) for r in rows]
    withprov = [(r, m) for r, m in prov if m.get("schema_version")]
    ev_ok = [m for r, m in withprov if m.get("evidence_snapshot_sha256") and m.get("evidence_snapshot_sha256") != _EMPTY_EVIDENCE_SHA]
    basis_ok = [m for r, m in withprov if isinstance(m.get("regulatory_basis"), dict) and m["regulatory_basis"].get("legal_conclusion_permitted") is True]
    both = [m for r, m in withprov if m in ev_ok and m in basis_ok]
    n = len(withprov)
    out.append(_kpi("complete_evidence_and_basis", "Decisions with a transaction record AND a supported regulatory basis", MEASURED if n else NOT_MEASURED, value=(len(both) / n) if n else None,
                    display=_pct(len(both) / n) if n else "—", n=n, definition="Decisions whose provenance holds a non-empty evidence fingerprint and a regulatory basis that permits a legal conclusion ÷ decisions with provenance.",
                    source="DECISION_LEDGER.METADATA_JSON (evidence_snapshot_sha256, regulatory_basis)",
                    caveat=f"{len(rows) - n} older decision(s) without provenance are excluded. 'Supported' means PROVEN or ASSUMED and current — not independently verified.",
                    extra={"with_transaction_evidence": len(ev_ok), "with_supported_basis": len(basis_ok)}, needs=None if n else "Decisions recorded with provenance."))
    if open_case_quality is not None:
        ready = sum(1 for q in open_case_quality if q.get("evaluated") and not q.get("blocks_filing") and not q["counts"].get("REQUIRES_MANUAL_REVIEW") and (q.get("sufficiency_pct") or 0) >= 80)
        out.append(_kpi("open_cases_decision_ready", "Open cases with a decision-grade record", MEASURED if open_case_quality else NOT_MEASURED,
                        value=(ready / len(open_case_quality)) if open_case_quality else None, display=_pct(ready / len(open_case_quality)) if open_case_quality else "—", n=len(open_case_quality),
                        definition="Open cases with evidence sufficiency ≥ 80 % and no blocking or manual-review evidence issue ÷ open cases.", source="skills/evidence_quality.py over the current queue",
                        caveat="Deterministic checks of the record, not of the case merits. The 80 % threshold is a product choice.", needs=None if open_case_quality else "Open alerts."))
    return {"kpis": out, "claims_policy": CLAIMS_POLICY, "baseline": {"captured": False, "note": "No baseline has been captured; improvement() refuses to state one."},
            "decisions": len(rows), "statuses": STATUS_MEANING}


# ── the simulated demonstration cohort ───────────────────────────────────────
SIM_NOTICE = ("SIMULATED — drawn from a seeded random generator to show what the dashboard would look like. These are not measurements of this "
              "application, of any customer or of any institution, and they support no claim of improvement.")


def simulated_cohort(n: int = 240, seed: int = 14) -> dict:
    """A deterministic synthetic cohort of n decided cases and the KPIs computed from it (every figure status SIMULATED)."""
    rng = random.Random(seed)
    cases = []
    for _ in range(n):
        label = "FILE" if rng.random() < 0.3 else "NOT_FILE"
        decision = label if rng.random() < 0.86 else ("NOT_FILE" if label == "FILE" else "FILE")
        hours = max(0.4, rng.lognormvariate(1.2, 0.6))
        touch = max(8.0, rng.gauss(34, 12))
        cases.append({"label": label, "decision": decision, "investigation_hours": hours, "touch_minutes": touch,
                      "within_window": rng.random() < 0.93, "override": rng.random() < 0.18, "rework": rng.random() < 0.07})
    cm = confusion((c["decision"], c["label"]) for c in cases)
    hrs = [c["investigation_hours"] for c in cases]
    sim = lambda kid, name, value, display, defn: {"id": kid, "name": name, "status": SIMULATED, "status_meaning": STATUS_MEANING[SIMULATED], "value": value,  # noqa: E731
                                                  "display": display + " (simulated)", "n": n, "definition": defn, "source": "simulated cohort", "caveat": SIM_NOTICE, "needs": None}
    kpis = [
        sim("sim_median_hours", "Investigation time — median", median(hrs), f"{median(hrs):.1f} h", "Median of the simulated hands-on hours."),
        sim("sim_p95_hours", "Investigation time — p95", percentile(hrs, 95), f"{percentile(hrs, 95):.1f} h", "Nearest-rank p95 of the simulated hands-on hours."),
        sim("sim_touch_minutes", "Analyst touch time — median", median([c['touch_minutes'] for c in cases]), f"{median([c['touch_minutes'] for c in cases]):.0f} min", "Median simulated active minutes."),
        sim("sim_precision", "Precision vs labels", cm["precision"], _pct(cm["precision"]), "Simulated decisions against simulated labels."),
        sim("sim_recall", "Recall vs labels", cm["recall"], _pct(cm["recall"]), "Simulated decisions against simulated labels."),
        sim("sim_f1", "F1 vs labels", cm["f1"], _pct(cm["f1"]), "Harmonic mean of the simulated precision and recall."),
        sim("sim_timeliness", "Within the filing window", sum(c["within_window"] for c in cases) / n, _pct(sum(c["within_window"] for c in cases) / n), "Share of simulated cases within the window."),
        sim("sim_override", "Override rate", sum(c["override"] for c in cases) / n, _pct(sum(c["override"] for c in cases) / n), "Share of simulated cases that overrode the AI."),
        sim("sim_rework", "Rework rate", sum(c["rework"] for c in cases) / n, _pct(sum(c["rework"] for c in cases) / n), "Share of simulated cases sent back."),
    ]
    return {"simulated": True, "notice": SIM_NOTICE, "seed": seed, "n": n, "kpis": kpis, "confusion": cm}
