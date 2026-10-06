"""
Phase 5 aggregate review-monitoring — pure, offline. Builds synthetic ledger rows and checks the
programme-level metrics, the deferral of the near-verbatim metric, the right denominators, grouping
by a non-officer key, and that nothing per-officer or decision-quality is emitted.
"""

import json

from skills import review_monitor as rm


def _hr(*, view="SUSPICION_SUPPORTED", required=False, triggers=(), ai_used=True, changed=None,
        counter="", overlap=None, innocent=""):
    return {
        "schema_version": 1, "enforcement_scope": "normal_ui_path",
        "review_requirement": {"required": required, "triggers": list(triggers), "classes_present": []},
        "provisional": {"view": view, "evidence_refs": [], "unanswered_question": "q", "saved_at": "t"},
        "ai_reveal": {"assessment_used": ai_used, "recommendation": None, "revealed_at": "t"},
        "final_reconciliation": {"changed_since_provisional": changed, "material_counter_evidence": counter,
                                 "accepted_innocent_explanation": innocent, "ai_draft_overlap_pct": overlap},
    }


def _row(disposition, *, hr=None, override=None, gate_codes=(), gaps=(), ai_rec=None, period="2026-10"):
    meta = {"ai_recommendation": ai_rec, "override": override,
            "defensibility_gate": {"conditions": [{"code": c} for c in gate_codes]},
            "challenge": {"open_gap_factors": list(gaps)}}
    if hr is not None:
        meta["human_review"] = hr
    return {"DISPOSITION": disposition, "META_TEXT": json.dumps(meta), "PERIOD": period}


def test_counts_and_missing_provenance():
    rows = [_row("FILE", hr=_hr()), _row("NOT_FILE", hr=_hr(view="INNOCENT_EXPLANATION_SUPPORTED")), _row("FILE", hr=None)]
    g = rm.summarise_reviews(rows)["groups"]["all"]
    assert g["total_decisions"] == 3
    assert g["with_review_rate"]["numerator"] == 2 and g["with_review_rate"]["denominator"] == 3
    assert g["missing_review_provenance_rate"]["numerator"] == 1          # the legacy/no-review row


def test_differ_from_ai_only_counts_ai_used():
    rows = [_row("NOT_FILE", hr=_hr(ai_used=True), override=True, ai_rec="FILE"),
            _row("FILE", hr=_hr(ai_used=True), override=False, ai_rec="FILE"),
            _row("NOT_FILE", hr=_hr(ai_used=False), override=None)]      # no AI → not in denominator
    g = rm.summarise_reviews(rows)["groups"]["all"]
    assert g["differ_from_ai_rate"]["numerator"] == 1 and g["differ_from_ai_rate"]["denominator"] == 2


def test_reconciliation_completion_uses_required_denominator():
    rows = [_row("NOT_FILE", hr=_hr(required=True, counter="addressed")),    # required + done
            _row("NOT_FILE", hr=_hr(required=True, counter="")),             # required + not done
            _row("FILE", hr=_hr(required=False, counter=""))]               # not required → excluded
    g = rm.summarise_reviews(rows)["groups"]["all"]
    r = g["reconciliation_completion_rate"]
    assert r["numerator"] == 1 and r["denominator"] == 2


def test_near_verbatim_measured_and_deferred():
    rows = [_row("FILE", hr=_hr(overlap=80.0)), _row("FILE", hr=_hr(overlap=40.0)), _row("FILE", hr=_hr(overlap=None))]
    nv = rm.summarise_reviews(rows)["groups"]["all"]["near_verbatim_adoption"]
    assert nv["measured"] == 2 and nv["deferred"] == 1 and nv["mean_overlap_pct"] == 60.0


def test_revision_rate_denominator_is_provisional_present():
    rows = [_row("FILE", hr=_hr(view="SUSPICION_SUPPORTED", changed=True)),
            _row("FILE", hr=_hr(view="SUSPICION_SUPPORTED", changed=False)),
            _row("FILE", hr=_hr(view=None, changed=True))]              # no provisional view → excluded
    r = rm.summarise_reviews(rows)["groups"]["all"]["provisional_to_final_revision_rate"]
    assert r["numerator"] == 1 and r["denominator"] == 2


def test_flagged_closure_and_innocent_and_unsupported():
    rows = [_row("NOT_FILE", hr=_hr(triggers=["CLOSE_WITH_FLAGGED_TXN"], innocent="documented sale"),
                 gate_codes=["UNSUPPORTED_FACTS_IN_RATIONALE"]),
            _row("NOT_FILE", hr=_hr(triggers=[], innocent=""))]
    g = rm.summarise_reviews(rows)["groups"]["all"]
    assert g["flagged_transaction_closure_rate"]["numerator"] == 1 and g["flagged_transaction_closure_rate"]["denominator"] == 2
    assert g["accepted_innocent_explanation_rate"]["numerator"] == 1
    assert g["unsupported_closure_rate"]["numerator"] == 1


def test_unresolved_gap_rate_over_file_and_notfile():
    rows = [_row("FILE", hr=_hr(), gaps=["POE-006"]), _row("NOT_FILE", hr=_hr(), gaps=[]),
            _row("DEFERRED", hr=_hr(), gaps=["POE-007"])]                 # DEFERRED excluded from this metric
    g = rm.summarise_reviews(rows)["groups"]["all"]
    assert g["unresolved_gap_rate"]["numerator"] == 1 and g["unresolved_gap_rate"]["denominator"] == 2


def test_grouping_by_non_officer_key():
    rows = [_row("FILE", hr=_hr(), period="2026-09"), _row("FILE", hr=_hr(), period="2026-10"),
            _row("NOT_FILE", hr=_hr(), period="2026-10")]
    out = rm.summarise_reviews(rows, group_by=lambda r: r["PERIOD"])
    assert set(out["groups"]) == {"2026-09", "2026-10"}
    assert out["groups"]["2026-10"]["total_decisions"] == 2


def test_disclaimer_and_no_decision_quality_or_officer_fields():
    out = rm.summarise_reviews([_row("FILE", hr=_hr())])
    assert "NOT an officer scorecard" in out["disclaimer"]
    blob = json.dumps(out)
    assert "decision_maker" not in blob and "rubber" not in blob.lower() and "quality_score" not in blob


def test_deferral_resolution_time_is_unavailable():
    g = rm.summarise_reviews([_row("DEFERRED", hr=_hr())])["groups"]["all"]
    assert g["deferral_resolution_time"]["value"] is None
