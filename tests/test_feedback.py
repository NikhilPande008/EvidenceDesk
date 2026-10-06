"""
Human feedback and model-quality loop (skills/feedback.py): the monitoring metrics — AI agreement, override, unsupported-claim, false-positive PROXY, rework,
recurring evidence gaps, closure reasons, downstream outcomes — and the rule they all live under: feedback is for monitoring and future calibration, never an input to a decision.

Offline. Usage:  python3 tests/test_feedback.py     (or pytest)
"""

from __future__ import annotations

import json
import re

from _helpers import ROOT, Runner

from skills import feedback as FB  # noqa: E402


def row(disp="FILE", alert="A-1", at="2026-10-01T10:00:00", ai="FILE", override=False, gate_codes=(), assessment=None, gaps=(), findings=(), reason=None, legacy=False,
        reason_stated=None, officer="PO-SECRET-7"):
    if legacy:
        return {"DISPOSITION": disp, "ALERT_ID": alert, "DECISION_MADE_AT": at, "DECISION_MAKER_ID": officer, "META_TEXT": None, "DECISION_ID": f"d-{alert}-{at}"}
    meta = {"schema_version": "3", "ai_recommendation": ai, "human_decision": disp, "override": override,
            "defensibility_gate": {"conditions": [{"code": c} for c in gate_codes]}, "poe_assessment": assessment or [],
            "challenge": {"open_gap_factors": list(gaps)} if gaps else {}, "evidence_quality": {"findings": [{"code": c} for c in findings]} if findings else None}
    if reason is not None or reason_stated is not None:
        meta["feedback"] = {"reason_code": reason, "reason_stated": bool(reason if reason_stated is None else reason_stated), "ai_response": FB.ai_response(ai, disp)}
    return {"DISPOSITION": disp, "ALERT_ID": alert, "DECISION_MADE_AT": at, "DECISION_MAKER_ID": officer, "METADATA_JSON": json.dumps(meta), "DECISION_ID": f"d-{alert}-{at}"}


def g(rows, outcomes=None, **kw):
    return FB.summarise_feedback(rows, outcomes, **kw)["groups"]["all"]


def test_agreement_and_override_rates_count_only_decisions_where_the_ai_ran():
    rows = [row("FILE", "A1", ai="FILE"), row("NOT_FILE", "A2", ai="NOT_FILE"), row("NOT_FILE", "A3", ai="FILE", override=True), row("DEFERRED", "A4", ai="FILE"),
            row("FILE", "A5", ai=None), row("NOT_FILE", "A6", ai="REVIEW"), row("FILE", "A7", legacy=True)]
    m = g(rows)
    assert m["total_decisions"] == 7 and m["decisions_without_provenance"] == 1
    assert (m["ai_agreement_rate"]["numerator"], m["ai_agreement_rate"]["denominator"]) == (2, 4), "accepted ÷ (accepted + rejected + deferred-instead)"
    assert (m["override_rate"]["numerator"], m["override_rate"]["denominator"]) == (1, 5), "overrides ÷ decisions where the AI ran (A5 did not)"
    assert m["ai_agreement_rate"]["rate"] == 0.5 and m["override_rate"]["rate"] == 0.2
    print("  [PASS] agreement 2/4 and override 1/5: only decisions with a definite (resp. any) AI recommendation are in the denominators; a legacy row is counted separately")


def test_unsupported_claims_are_measured_separately_for_officer_text_and_ai_factors():
    ungrounded = [{"assessment": "triggered", "grounded": False}, {"assessment": "triggered", "grounded": True}, {"assessment": "clear", "grounded": None}]
    rows = [row("NOT_FILE", "A1", gate_codes=["UNSUPPORTED_FACTS_IN_RATIONALE"], assessment=ungrounded), row("NOT_FILE", "A2"), row("DEFERRED", "A3"), row("FILE", "A4", assessment=ungrounded)]
    m = g(rows)
    assert (m["unsupported_claim_rate_officer"]["numerator"], m["unsupported_claim_rate_officer"]["denominator"]) == (1, 3), "non-filings only: a filing cannot be recorded with such facts"
    assert (m["unsupported_claim_rate_ai"]["numerator"], m["unsupported_claim_rate_ai"]["denominator"]) == (2, 4), "ungrounded ÷ triggered AI factors"
    assert "not an officer signal" in m["unsupported_claim_rate_ai"]["caveat"]
    print("  [PASS] unsupported-claim rate: officer text (1 of 3 non-filings) and AI factors (2 of 4 triggered) are separate metrics with their own caveats")


def test_the_false_positive_figure_is_a_proxy_and_says_so():
    m = g([row("NOT_FILE", "A1"), row("NOT_FILE", "A2"), row("FILE", "A3"), row("DEFERRED", "A4")])
    fp = m["false_positive_proxy_rate"]
    assert fp["is_proxy"] is True and (fp["numerator"], fp["denominator"]) == (2, 3) and "PROXY" in fp["caveat"] and "not a confirmed false positive" in fp["caveat"]
    assert "proxy" in FB.METRICS["false_positive_proxy_rate"][0].lower() or "PROXY" in FB.METRICS["false_positive_proxy_rate"][1]
    print("  [PASS] false-positive proxy = closures ÷ concluding decisions (2 of 3), flagged is_proxy with the caveat that a closure is not a confirmed false positive")


def test_rework_is_a_decision_after_a_concluding_one_not_a_deferral_followed_by_its_answer():
    rows = [row("DEFERRED", "A1", at="2026-10-01"), row("FILE", "A1", at="2026-10-02"),
            row("NOT_FILE", "A2", at="2026-10-01"), row("FILE", "A2", at="2026-10-03"),
            row("FILE", "A3", at="2026-10-01"), row("NOT_FILE", "A4", at="2026-10-01")]
    r = g(rows)["rework_rate"]
    assert (r["numerator"], r["denominator"]) == (1, 4), "only A2 (concluded, then decided again); A1's deferral → final is the intended path"
    print("  [PASS] rework 1 of 4 alerts: a closure later overturned counts; defer → decide does not")


def test_recurring_evidence_gaps_and_the_closure_reason_mix():
    rows = [row("NOT_FILE", "A1", gaps=["POE-012", "POE-006"], findings=["TXN_SUMMARY_ONLY", "TXN_NO_BASELINE"], reason="DOCUMENTED_LEGITIMATE_SOURCE"),
            row("NOT_FILE", "A2", gaps=["POE-012"], findings=["TXN_SUMMARY_ONLY"], reason="INSUFFICIENT_EVIDENCE_AFTER_INQUIRY"),
            row("DEFERRED", "A3", gaps=["POE-012"], reason="KYC_REFRESH_PENDING"), row("NOT_FILE", "A4"), row("FILE", "A5")]
    m = g(rows)
    gaps = m["recurring_evidence_gaps"]
    assert gaps["ai_factor_gaps"][0] == {"factor_id": "POE-012", "decisions": 3} and {"factor_id": "POE-006", "decisions": 1} in gaps["ai_factor_gaps"]
    assert gaps["record_quality_findings"][0] == {"code": "TXN_SUMMARY_ONLY", "decisions": 2}
    assert m["closure_reason_mix"] == {"NOT_STATED": 1, "DOCUMENTED_LEGITIMATE_SOURCE": 1, "INSUFFICIENT_EVIDENCE_AFTER_INQUIRY": 1, "KYC_REFRESH_PENDING": 1}
    assert (m["closure_reason_stated_rate"]["numerator"], m["closure_reason_stated_rate"]["denominator"]) == (3, 4)
    print("  [PASS] recurring gaps ranked (POE-012 in 3 decisions; TXN_SUMMARY_ONLY in 2), closure-reason mix with 'not stated' counted, stated rate 3 of 4 non-filings")


def test_downstream_outcomes_appear_only_when_a_feed_exists_and_are_never_inferred():
    rows = [row("NOT_FILE", "A1"), row("FILE", "A2"), row("NOT_FILE", "A3")]
    none = g(rows)["outcomes"]
    assert none["available"] is False and "not inferred" in none["reason"]
    out = [{"DECISION_ID": "d-A1-2026-10-01T10:00:00", "OUTCOME_TYPE": "CLOSURE_CONFIRMED_BY_QA"}, {"DECISION_ID": "d-A3-2026-10-01T10:00:00", "OUTCOME_TYPE": "CLOSURE_OVERTURNED_BY_QA"},
           {"DECISION_ID": "d-A2-2026-10-01T10:00:00", "OUTCOME_TYPE": "STR_ACKNOWLEDGED"}, {"DECISION_ID": "unrelated", "OUTCOME_TYPE": "CASE_REOPENED"}]
    o = g(rows, out)["outcomes"]
    assert o["available"] and o["by_type"] == {"CLOSURE_CONFIRMED_BY_QA": 1, "CLOSURE_OVERTURNED_BY_QA": 1, "STR_ACKNOWLEDGED": 1}, o
    assert (o["outcome_rework"]["numerator"], o["outcome_rework"]["denominator"]) == (1, 3) and (o["qa_confirmed_closure_rate"]["numerator"], o["qa_confirmed_closure_rate"]["denominator"]) == (1, 2)
    assert set(FB.REWORK_OUTCOMES) <= set(FB.OUTCOME_TYPES)
    print("  [PASS] outcomes: 'not provisioned' when there is no feed; with one, outcomes of THESE decisions only, rework 1 of 3, QA-confirmed closures 1 of 2")


def test_no_officer_identity_leaves_this_module_and_grouping_is_by_period_or_type_only():
    rows = [row("NOT_FILE", "A1", at="2026-09-30T10:00:00"), row("FILE", "A2", at="2026-10-02T10:00:00")]
    out = FB.summarise_feedback(rows, group_by=lambda r: str(r["DECISION_MADE_AT"])[:7])
    assert set(out["groups"]) == {"2026-09", "2026-10"}
    blob = json.dumps(out)
    assert "PO-SECRET-7" not in blob and "DECISION_MAKER_ID" not in blob
    assert "not an officer scorecard" in out["disclaimer"] and "never retrain" in out["calibration_policy"]
    print("  [PASS] grouped by month with no officer identity anywhere in the output; the disclaimer says 'not an officer scorecard', the policy says 'never retrain'")


def test_feedback_never_reaches_a_decision_path_it_is_read_only_by_dashboards_and_scripts():
    """Nothing silently retrains or retunes: the monitoring functions are read by pages and scripts, and by nothing that decides."""
    skills_dir = ROOT / "skills"
    deciders = ["prioritisation", "defensibility", "evidence_quality", "governance", "grounding", "ledger", "llm_output", "human_review", "relationships", "corpus_lifecycle", "identity", "errors", "evidence"]
    for name in deciders:
        src = (skills_dir / f"{name}.py").read_text()
        assert not re.search(r"^\s*(?:from|import)\s+skills(?:\.feedback\b|\.kpis\b|\s+import\s+[^\n]*\b(?:feedback|kpis)\b)", src, re.M), f"{name} must not import feedback / kpis"
        assert "summarise_feedback" not in src and "compute_kpis" not in src, name
    core = (skills_dir / "core.py").read_text()
    used = set(re.findall(r"\bfb\.(\w+)", core))
    assert used <= {"capture", "ai_response"}, f"core.py may only WRITE feedback (capture); it uses fb.{sorted(used)}"
    for py in skills_dir.glob("*.py"):
        if py.name in ("feedback.py", "kpis.py"):
            continue
        assert "summarise_feedback" not in py.read_text(), f"{py.name} reads the monitoring summary"
    assert "CALIBRATION_POLICY" in (skills_dir / "feedback.py").read_text() and "never retrain" in FB.CALIBRATION_POLICY.lower().replace("never retrain", "never retrain")
    print(f"  [PASS] {len(deciders)} decision-path modules do not import feedback or kpis; core.py only calls fb.{'/'.join(sorted(used))}; summarise_feedback is read by no skill")


def test_capture_is_bounded_and_the_stored_object_holds_no_free_text():
    hostile = "![x](https://attacker.example/p.png) " + "Z" * 10000
    f = FB.capture(disposition="NOT_FILE", ai_recommendation=hostile, closure_reason_code=hostile, ai_draft_generated=True, ai_draft_sha256=hostile, final_text_sha256=hostile)
    assert f["reason_code"] is None and f["reason_stated"] is False and len(f["ai_recommendation"]) <= 40 and len(json.dumps(f)) < 600, json.dumps(f)[:200]
    assert f["ai_draft"] == {"generated": True, "adopted_verbatim": True}, "equal (even hostile) hashes compare equal; nothing from the draft text is stored"
    f2 = FB.capture(disposition="NOT_FILE", ai_recommendation="FILE", closure_reason_code="OTHER")
    assert set(f2) == {"schema", "use", "ai_recommendation", "ai_response", "reason_code", "reason_stated", "ai_draft"} and f2["use"] == "monitoring_and_future_calibration_only"
    print("  [PASS] the stored feedback object has a fixed shape; an invalid reason is dropped; its `use` field records 'monitoring and future calibration only'")


TESTS = [
    test_agreement_and_override_rates_count_only_decisions_where_the_ai_ran, test_unsupported_claims_are_measured_separately_for_officer_text_and_ai_factors,
    test_the_false_positive_figure_is_a_proxy_and_says_so, test_rework_is_a_decision_after_a_concluding_one_not_a_deferral_followed_by_its_answer,
    test_recurring_evidence_gaps_and_the_closure_reason_mix, test_downstream_outcomes_appear_only_when_a_feed_exists_and_are_never_inferred,
    test_no_officer_identity_leaves_this_module_and_grouping_is_by_period_or_type_only, test_feedback_never_reaches_a_decision_path_it_is_read_only_by_dashboards_and_scripts,
    test_capture_is_bounded_and_the_stored_object_holds_no_free_text,
]



def test_the_outcome_feed_ddl_matches_the_taxonomy_and_gives_the_app_role_select_only():
    sql = (ROOT / "deploy/07_decision_outcomes.sql").read_text()
    in_ddl = set(re.findall(r"'([A-Z_]+)'", sql.split("CONSTRAINT CHK_OUTCOME_TYPE CHECK")[1].split(")")[0]))
    assert in_ddl == set(FB.OUTCOME_TYPES), (in_ddl ^ set(FB.OUTCOME_TYPES))
    grants = re.findall(r"GRANT\s+(.+?)\s+ON\s+(\S+\s+\S+)\s+TO\s+ROLE\s+(\w+)", sql)
    assert grants == [("SELECT", "TABLE FIU_COPILOT.AUDIT.DECISION_OUTCOMES", "FIU_APP_ROLE")], grants
    assert not re.search(r"\b(UPDATE|DELETE|TRUNCATE|DROP)\b", re.sub(r"--.*", "", sql), re.I), "the feed script writes no destructive statement"
    assert "NOTE" not in FB.OUTCOMES_SQL and FB.OUTCOMES_TABLE in sql and "future calibration only" in sql
    print("  [PASS] deploy/07_decision_outcomes.sql: the CHECK list equals feedback.OUTCOME_TYPES; the app role gets SELECT only; no destructive statement; the free-text NOTE is never selected by the app")


TESTS.append(test_the_outcome_feed_ddl_matches_the_taxonomy_and_gives_the_app_role_select_only)


if __name__ == "__main__":
    raise SystemExit(Runner("Feedback loop (offline)").run(TESTS))
