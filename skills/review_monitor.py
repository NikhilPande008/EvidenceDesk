"""
Phase 5 — aggregate review-monitoring, PURE (no Snowflake, no model, no clock).

A second-line / model-risk view over DECISION_LEDGER rows the caller fetches (same row shape as
skills/audit.py: a DISPOSITION and a METADATA_JSON / META_TEXT per row). It summarises the health of
the independent-review protocol at the PROGRAMME level.

NON-NEGOTIABLE (design/HUMAN_REVIEW_SPEC.md §8):
  * NO per-officer scores, NO league tables, NO disciplinary signal. This module never groups by, or
    returns, an individual decision-maker. `group_by` is a caller-supplied key function for period /
    product / alert type / risk band / cohort ONLY; passing a per-officer key is a policy violation,
    not supported here.
  * Every metric carries an interpretation caveat. Drift is a prompt to SAMPLE and review by hand,
    never an automatic conclusion. No individual decision is ever labelled "rubber-stamped".
  * The revision rate is distortion-prone (monitoring it changes it) and is never shown to an officer
    about themselves.
  * Near-verbatim adoption is reported ONLY where an AI-draft overlap was captured at record time;
    otherwise it is DEFERRED (counted, never approximated from the final text).

Pure functions over rows; nothing here reads or writes the database.
"""

from __future__ import annotations

import json
from typing import Any, Callable

CLOSURES = ("NOT_FILE", "ESCALATE")

# metric key → (human label, interpretation caveat)
METRICS: dict[str, tuple[str, str]] = {
    "with_review_rate": ("Decisions carrying an independent-review record",
                         "Pre-protocol rows legitimately have none; a low rate across NEW decisions is the signal."),
    "missing_review_provenance_rate": ("Decisions with no review provenance",
                                       "Includes legacy/pre-flag rows; read against when the protocol was turned on."),
    "differ_from_ai_rate": ("Final decisions that differ from a definite AI recommendation",
                            "Neither agreement nor disagreement is a quality signal on its own."),
    "provisional_to_final_revision_rate": ("First impression revised after AI was revealed",
                                           "Distortion-prone: monitoring it can change it. Never show an officer their own rate."),
    "reconciliation_completion_rate": ("Required reconciliations that were completed",
                                       "Denominator is decisions the recorder flagged as higher-risk; completion is a floor, not proof of depth."),
    "near_verbatim_adoption": ("Mean AI-draft overlap where captured",
                               "Descriptive only; high overlap is frequently legitimate because the facts are shared. Never a gate."),
    "unsupported_filing_rate": ("Filings citing facts not in the record",
                                "Expected ~0: the evidence gate blocks these at record time. A non-zero value warrants investigation."),
    "unsupported_closure_rate": ("Closures whose rationale cites facts not in the record",
                                 "Recorded as written, not as verified; a WARN, not a block."),
    "flagged_transaction_closure_rate": ("Closures of alerts with a flagged counterparty",
                                         "Legitimate when the onward flow is documented; a rising rate is a sampling prompt."),
    "accepted_innocent_explanation_rate": ("Closures that accept an innocent explanation",
                                           "The explanation's evidence is supplied, not independently verified."),
    "unresolved_gap_rate": ("FILE/NOT_FILE decisions with an unresolved evidence gap",
                            "A gap can be defensible; the point is whether it was acknowledged, not merely present."),
    "deferral_resolution_time": ("Time to resolve a deferral",
                                 "Not available from the ledger alone (defer→later-decision linkage is not recorded)."),
}

# Stored-provenance keys this module reads; documented so a SQL view can mirror them (see HUMAN_REVIEW_SPEC §8).
_NO_AI = ("", "NOT_RUN", "NEEDS_MANUAL_REVIEW", "NONE", None)


def _meta(row: dict) -> dict:
    m = row.get("META_TEXT") if "META_TEXT" in row else row.get("metadata", row.get("METADATA_JSON"))
    if isinstance(m, str):
        try:
            return json.loads(m)
        except ValueError:
            return {}
    return m if isinstance(m, dict) else {}


def _gate_codes(meta: dict) -> set:
    return {c.get("code") for c in ((meta.get("defensibility_gate") or {}).get("conditions") or []) if isinstance(c, dict)}


def _nonempty(v: Any) -> bool:
    return len(str(v or "").strip()) > 0


def _rate(num: int, den: int, caveat: str) -> dict:
    return {"rate": round(num / den, 3) if den else None, "numerator": num, "denominator": den, "caveat": caveat}


class _Acc:
    __slots__ = ("total", "with_review", "ai_used", "ai_differ", "prov_present", "prov_revised", "required",
                 "required_done", "nv_pcts", "nv_deferred", "file_n", "file_unsupported", "closure_n",
                 "closure_unsupported", "closure_flagged", "closure_innocent", "file_notfile_n", "unresolved_gap")

    def __init__(self):
        for s in self.__slots__:
            setattr(self, s, [] if s == "nv_pcts" else 0)

    def add(self, disposition: str, meta: dict):
        self.total += 1
        hr = meta.get("human_review")
        has_hr = isinstance(hr, dict)
        if not has_hr:
            return                                   # only decisions with a review contribute to review metrics
        self.with_review += 1
        rr = hr.get("review_requirement") or {}
        prov = hr.get("provisional") or {}
        air = hr.get("ai_reveal") or {}
        fr = hr.get("final_reconciliation") or {}
        codes = _gate_codes(meta)
        d = (disposition or "").upper()

        ai_used = bool(air.get("assessment_used")) or (meta.get("ai_recommendation") or "").upper() not in _NO_AI
        if ai_used:
            self.ai_used += 1
            if meta.get("override") is True:
                self.ai_differ += 1
        if prov.get("view"):
            self.prov_present += 1
            if fr.get("changed_since_provisional") is True:
                self.prov_revised += 1
        if rr.get("required"):
            self.required += 1
            if _nonempty(fr.get("material_counter_evidence")):
                self.required_done += 1
        pct = fr.get("ai_draft_overlap_pct")
        if isinstance(pct, (int, float)):
            self.nv_pcts.append(float(pct))
        else:
            self.nv_deferred += 1
        if d == "FILE":
            self.file_n += 1
            if "EVIDENCE_GATE_FAILED" in codes:
                self.file_unsupported += 1
        if d in CLOSURES:
            self.closure_n += 1
            if "UNSUPPORTED_FACTS_IN_RATIONALE" in codes:
                self.closure_unsupported += 1
            if "CLOSE_WITH_FLAGGED_TXN" in (rr.get("triggers") or []):
                self.closure_flagged += 1
            if _nonempty(fr.get("accepted_innocent_explanation")):
                self.closure_innocent += 1
        if d in ("FILE", "NOT_FILE"):
            self.file_notfile_n += 1
            if (meta.get("challenge") or {}).get("open_gap_factors"):
                self.unresolved_gap += 1

    def metrics(self) -> dict:
        c = lambda k: METRICS[k][1]  # noqa: E731
        nv_mean = round(sum(self.nv_pcts) / len(self.nv_pcts), 1) if self.nv_pcts else None
        return {
            "total_decisions": self.total,
            "with_review_rate": _rate(self.with_review, self.total, c("with_review_rate")),
            "missing_review_provenance_rate": _rate(self.total - self.with_review, self.total, c("missing_review_provenance_rate")),
            "differ_from_ai_rate": _rate(self.ai_differ, self.ai_used, c("differ_from_ai_rate")),
            "provisional_to_final_revision_rate": _rate(self.prov_revised, self.prov_present, c("provisional_to_final_revision_rate")),
            "reconciliation_completion_rate": _rate(self.required_done, self.required, c("reconciliation_completion_rate")),
            "near_verbatim_adoption": {"mean_overlap_pct": nv_mean, "measured": len(self.nv_pcts),
                                       "deferred": self.nv_deferred, "caveat": c("near_verbatim_adoption")},
            "unsupported_filing_rate": _rate(self.file_unsupported, self.file_n, c("unsupported_filing_rate")),
            "unsupported_closure_rate": _rate(self.closure_unsupported, self.closure_n, c("unsupported_closure_rate")),
            "flagged_transaction_closure_rate": _rate(self.closure_flagged, self.closure_n, c("flagged_transaction_closure_rate")),
            "accepted_innocent_explanation_rate": _rate(self.closure_innocent, self.closure_n, c("accepted_innocent_explanation_rate")),
            "unresolved_gap_rate": _rate(self.unresolved_gap, self.file_notfile_n, c("unresolved_gap_rate")),
            "deferral_resolution_time": {"value": None, "caveat": c("deferral_resolution_time")},
        }


DISCLAIMER = ("Programme-level signal for second-line / model-risk review. It is NOT an officer scorecard and NOT a measure of "
              "decision quality. Agreement or disagreement with the AI is not a quality signal. Drift should lead to human "
              "sampling and qualitative review, never to an automatic conclusion about any individual or decision.")


def summarise_reviews(rows: list[dict], *, group_by: Callable[[dict], str] | None = None) -> dict:
    """Aggregate review-health metrics over ledger `rows`. `group_by(row)->key` groups by period / product / alert type /
    risk band / cohort ONLY — never by an individual officer. Returns {groups, metric_labels, disclaimer}."""
    groups: dict[str, _Acc] = {}
    for row in rows:
        key = "all" if group_by is None else str(group_by(row))
        acc = groups.setdefault(key, _Acc())
        acc.add(row.get("DISPOSITION") or row.get("disposition"), _meta(row))
    return {
        "groups": {k: acc.metrics() for k, acc in groups.items()},
        "metric_labels": {k: v[0] for k, v in METRICS.items()},
        "disclaimer": DISCLAIMER,
    }
