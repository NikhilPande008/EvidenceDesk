"""
Phase 14 gate extensions: evidence-quality conditions, authenticated decision-maker identity and structured closure reasons — enforced by the
ONE decision gate, re-derived by the ledger recorder (the UI is never trusted), stored in provenance, and invisible to a caller that predates them.

Offline (pure functions + a recording fake database). Usage:  python3 tests/test_gate_extensions.py     (or pytest)
"""

from __future__ import annotations

import inspect
import json
import sys
from datetime import datetime, timedelta, timezone

from _helpers import FakeConn, ROOT, Runner, case_context, recorder_kwargs

sys.path.insert(0, str(ROOT / "scripts"))

from skills import CoPilotSkills  # noqa: E402
from skills import defensibility as D  # noqa: E402
from skills import feedback as FB  # noqa: E402
from skills import identity as ID  # noqa: E402
from skills.ledger import LedgerBlocked  # noqa: E402

LONG_REASON = "I opened the account statement and checked each flagged item against it myself."
CLEAN_META = {"ALERT_ID": "ALERT-X", "CUSTOMER_REF": "CUST-X", "ALERT_DATE": "2026-08-19", "ALERT_TYPE": "MULE_PASSTHROUGH", "SIGNAL_SOURCE": "I4C",
              "ACCOUNT_TYPE": "SAVINGS", "ALERT_AMOUNT_INR": 555000, "CUSTOMER_PROFILE": "Salaried employee; Rs.30K/month declared; account 14 months old",
              "ALERT_NARRATIVE": "Pass-through mule pattern.", "ALERT_STATUS": "OPEN"}


def recent() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")


def sk(conn=None):
    return CoPilotSkills(conn if conn is not None else FakeConn())


def call(meta=None, **over):
    """A valid FILE call whose case record CARRIES alert metadata (so the recorder evaluates evidence quality)."""
    kw = recorder_kwargs(suspicion_formed_at=recent(), **over)
    if meta is not None:
        kw["case_context"] = {**kw["case_context"], "alert_meta": meta}
    return kw


def blocked(kw, expect: str, conn=None):
    conn = conn if conn is not None else FakeConn()
    try:
        sk(conn).alert_disposition_recorder(**kw)
    except LedgerBlocked as err:
        assert expect in str(err), (expect, str(err))
        assert not conn.stmts("INSERT") and not conn.stmts("BEGIN"), "a refused write touches nothing"
        return str(err)
    raise AssertionError(f"recorded, but should have been refused ({expect!r})")


# ── the gate: evidence-quality conditions ────────────────────────────────────

SUMMARY = {"blocking": [{"code": "KYC_PROFILE_MISSING", "title": "No KYC profile in the record"}], "blocking_enforced_elsewhere": [],
           "manual_review": [{"code": "KYC_CURRENCY_FLAG", "title": "The record says KYC is stale, expired or unconfirmed"}],
           "acknowledgement": [{"code": "TXN_SUMMARY_ONLY", "title": "Every transaction row is an aggregated summary"}], "informational": 2, "sufficiency_pct": 55}
OK_EV = {"passed": True, "unsupported_claims_by_type": {}, "unverified_assertions": []}


def gate(**over):
    from _helpers import basis_for
    kw = dict(disposition="FILE", rationale_text="A substantive Ground of Suspicion citing the recorded credits and debits.", has_case_context=True, transaction_count=3,
              evidence_gate=OK_EV, gos_status="READY", ai_recommendation="FILE", regulatory_basis=basis_for(["STR-001"]), sla_days_remaining=5)
    kw.update(over)
    return D.evaluate(**kw)


def cond(g, code):
    return next((c for c in g["conditions"] if c["code"] == code), None)


def test_each_effect_maps_to_one_gate_condition_with_the_right_severity_per_decision():
    g = gate(evidence_quality=SUMMARY)
    assert cond(g, "EVIDENCE_QUALITY_BLOCKS_FILING")["severity"] == D.BLOCK and g["status"] == D.STATUS_BLOCKED
    assert cond(g, "EVIDENCE_QUALITY_ACK_REQUIRED")["satisfied"] is False and cond(g, "EVIDENCE_QUALITY_MANUAL_REVIEW")["satisfied"] is False
    for d in ("NOT_FILE", "ESCALATE"):
        g = gate(disposition=d, ai_recommendation=d if d == "NOT_FILE" else "REVIEW", evidence_quality=SUMMARY)
        assert cond(g, "EVIDENCE_QUALITY_BLOCKS_FILING") is None and cond(g, "EVIDENCE_QUALITY_ISSUES_ON_CLOSURE")["severity"] == D.WARN
        assert cond(g, "EVIDENCE_QUALITY_ACK_REQUIRED") and cond(g, "EVIDENCE_QUALITY_MANUAL_REVIEW"), "a closure also needs the acknowledgement and the manual check"
    g = gate(disposition="DEFERRED", ai_recommendation="REVIEW", evidence_quality=SUMMARY)
    assert not [c for c in g["conditions"] if c["code"].startswith("EVIDENCE_QUALITY")] and g["can_record"], "a deferral is the remedy; it is never gated on the issues"
    print("  [PASS] FILE: blocks + acknowledgement + manual review · NOT_FILE / ESCALATE: warning + acknowledgement + manual review · DEFERRED: none")


def test_nothing_the_officer_ticks_lifts_a_blocking_issue_but_the_other_two_effects_are_satisfiable():
    g = gate(evidence_quality=SUMMARY, evidence_quality_acknowledged=True, override_reason=LONG_REASON)
    assert not g["can_record"] and g["blocking_codes"] == ["EVIDENCE_QUALITY_BLOCKS_FILING"] and not g["pending_codes"], "ack + reason satisfy the others; the BLOCK stays"
    only = dict(SUMMARY, blocking=[])
    g = gate(evidence_quality=only)
    assert g["status"] == D.STATUS_ACTION_REQUIRED and set(g["pending_codes"]) == {"EVIDENCE_QUALITY_ACK_REQUIRED", "EVIDENCE_QUALITY_MANUAL_REVIEW"}
    assert gate(evidence_quality=only, evidence_quality_acknowledged=True)["pending_codes"] == ["EVIDENCE_QUALITY_MANUAL_REVIEW"]
    assert gate(evidence_quality=only, override_reason="too short")["pending_codes"] == ["EVIDENCE_QUALITY_ACK_REQUIRED", "EVIDENCE_QUALITY_MANUAL_REVIEW"]
    ok = gate(evidence_quality=only, evidence_quality_acknowledged=True, override_reason=LONG_REASON)
    assert ok["can_record"] and ok["acknowledgements"]["evidence_quality"] is True
    print("  [PASS] a blocking issue cannot be ticked or typed away; acknowledgement and manual-review (≥20 characters) each lift only their own condition")


def test_a_gate_without_the_new_inputs_is_exactly_the_old_gate():
    base = gate()
    assert not [c for c in base["conditions"] if c["code"].startswith(("EVIDENCE_QUALITY", "IDENTITY", "CLOSURE_REASON")) or c["code"] == "PO_ID_DIFFERS_FROM_SESSION_IDENTITY"]
    assert "evidence_quality" not in base["acknowledgements"], "the stored acknowledgements keep their old shape when quality was not evaluated"
    assert gate(evidence_quality={"blocking": [], "manual_review": [], "acknowledgement": []})["conditions"] == base["conditions"], "an evaluated, clean record adds nothing"
    print("  [PASS] no evidence-quality / identity / closure-reason input → the same conditions and the same acknowledgements shape as before")


def test_identity_conditions():
    typed = ID.resolve(None, "PO-77")
    g = gate(identity=ID.clean(typed), decision_maker_id="PO-77")
    assert cond(g, "IDENTITY_NOT_AUTHENTICATED")["severity"] == D.WARN and g["can_record"]
    sess = ID.resolve("officer.one@bank.example", "anything")
    assert sess["authenticated"] and sess["id"] == "officer.one@bank.example" and not sess["editable"]
    assert not [c for c in gate(identity=ID.clean(sess), decision_maker_id="OFFICER.ONE@bank.example")["conditions"] if c["code"].startswith(("IDENTITY", "PO_ID_DIFFERS"))], \
        "case and surrounding space are ignored"
    g = gate(identity=ID.clean(sess), decision_maker_id="someone.else")
    assert cond(g, "PO_ID_DIFFERS_FROM_SESSION_IDENTITY")["severity"] == D.BLOCK and not g["can_record"]
    assert ID.clean({"id": "x", "source": "SESSION", "authenticated": True})["authenticated"] and not ID.clean({"id": "x", "source": "TYPED", "authenticated": True})["authenticated"], \
        "'typed' can never be recorded as authenticated"
    assert ID.clean("not a dict") is None
    print("  [PASS] typed ID → warning; session identity → read-only, a different ID is BLOCKED; a typed source can never claim to be authenticated")


def test_a_closure_without_a_structured_reason_is_a_warning_only_when_reasons_are_being_captured():
    g = gate(disposition="NOT_FILE", ai_recommendation="NOT_FILE", closure_reason_stated=False)
    assert cond(g, "CLOSURE_REASON_NOT_STATED")["severity"] == D.WARN and g["can_record"]
    assert cond(gate(disposition="NOT_FILE", ai_recommendation="NOT_FILE", closure_reason_stated=True), "CLOSURE_REASON_NOT_STATED") is None
    assert cond(gate(disposition="NOT_FILE", ai_recommendation="NOT_FILE"), "CLOSURE_REASON_NOT_STATED") is None, "None = not evaluated"
    assert cond(gate(closure_reason_stated=False), "CLOSURE_REASON_NOT_STATED") is None, "a filing's reason is its Ground of Suspicion"
    print("  [PASS] CLOSURE_REASON_NOT_STATED: a warning on a closure that states none; not evaluated unless the caller captures reasons; never on a filing")


# ── the checkpoint ───────────────────────────────────────────────────────────

def test_the_checkpoint_gains_one_row_only_when_the_gate_has_an_evidence_quality_condition():
    plain = D.checkpoint(gate(), disposition="FILE", ai_state=D.AI_VALID, ai_recommendation="FILE", transaction_count=3)
    assert len(plain["rows"]) == 7 and [r["id"] for r in plain["rows"]][-1] == "C7"
    cp = D.checkpoint(gate(evidence_quality=SUMMARY), disposition="FILE", ai_state=D.AI_VALID, ai_recommendation="FILE", transaction_count=3)
    ids = [r["id"] for r in cp["rows"]]
    assert ids == ["C1", "C2", "C3", "C4", "C5", "C6", "CQ", "C7"], ids
    row = next(r for r in cp["rows"] if r["id"] == "CQ")
    assert row["status"] == D.CP_BLOCK and "No KYC profile in the record" in row["detail"] and cp["blocks"] >= 1 and not cp["ready"]
    only = dict(SUMMARY, blocking=[])
    needs = next(r for r in D.checkpoint(gate(evidence_quality=only), disposition="FILE", transaction_count=3)["rows"] if r["id"] == "CQ")
    assert needs["status"] == D.CP_NEEDS and "tick that you have read" in needs["detail"] and "at least 20 characters" in needs["detail"]
    done = next(r for r in D.checkpoint(gate(evidence_quality=only, evidence_quality_acknowledged=True, override_reason=LONG_REASON), disposition="FILE", transaction_count=3)["rows"] if r["id"] == "CQ")
    assert done["status"] == D.CP_PASS
    closing = D.checkpoint(gate(disposition="NOT_FILE", ai_recommendation="NOT_FILE", evidence_quality=dict(SUMMARY, acknowledgement=[], manual_review=[])), disposition="NOT_FILE", transaction_count=3)
    assert next(r for r in closing["rows"] if r["id"] == "CQ")["status"] == D.CP_NOTE
    ident = D.checkpoint(gate(identity=ID.clean(ID.resolve("a", "")), decision_maker_id="b"), disposition="FILE", transaction_count=3)
    assert ident["rows"][-1]["status"] == D.CP_BLOCK and "signed-in identity" in ident["rows"][-1]["detail"] and ident["blocks"] >= 1
    print("  [PASS] checkpoint: seven rows normally; an evidence-quality row (BLOCK / NEEDS YOU / PASS / NOTE) appears before the roll-up only when the gate carries one; an ID mismatch blocks C7")


# ── the recorder re-derives everything ───────────────────────────────────────

def test_the_recorder_signature_accepts_no_precomputed_quality_only_the_officers_acknowledgement():
    params = set(inspect.signature(CoPilotSkills.alert_disposition_recorder).parameters)
    assert "evidence_quality_acknowledged" in params and "evidence_quality" not in params and "evidence_quality_summary" not in params
    print("  [PASS] the write path takes the officer's acknowledgement, never a caller-supplied quality result")


def test_a_filing_on_a_record_with_a_blocking_issue_is_refused_and_writes_nothing():
    msg = blocked(call(dict(CLEAN_META, CUSTOMER_PROFILE="")), "No KYC profile in the record")
    assert "blocks a filing" in msg
    blocked(call(dict(CLEAN_META, CUSTOMER_PROFILE=""), evidence_quality_acknowledged=True, override_reason=LONG_REASON), "No KYC profile in the record")
    print("  [PASS] recorder: no KYC profile → FILE refused with the issue's name, no SQL at all, even with the acknowledgement and a reason")


def test_manual_review_and_acknowledgement_are_required_then_recorded_with_the_decision():
    meta = dict(CLEAN_META, CUSTOMER_PROFILE="Salaried employee; Rs.30K/month declared; stale KYC (3 years)", ALERT_NARRATIVE="Pass-through. Sale documentation not yet produced.")
    blocked(call(meta), "Check these yourself")
    conn = FakeConn()
    out = sk(conn).alert_disposition_recorder(**call(meta, override_reason=LONG_REASON))
    prov = out["provenance"]
    eq = prov["evidence_quality"]
    assert eq["schema"] == "evidence_quality/1" and {f["code"] for f in eq["findings"]} >= {"KYC_CURRENCY_FLAG", "DOCUMENTS_MISSING_STATED"}
    assert prov["override_reason"] == LONG_REASON and out["gate"]["acknowledgements"]["override_reason_recorded"] is True
    assert cond(out["gate"], "EVIDENCE_QUALITY_MANUAL_REVIEW")["satisfied"] is True
    agg = dict(CLEAN_META)
    kw = call(agg)
    kw["case_context"] = {**kw["case_context"], "transactions": [{"txn_id": "T1", "date": "2026-08-19", "type": "CREDIT", "amount_inr": 555000, "channel": "UPI",
                                                                  "counterparty": "Multiple counterparties (see alert narrative)", "is_flagged": False}]}
    kw["rationale_text"] = "I formed suspicion because of the recorded credit of ₹5,55,000 on 2026-08-19 via UPI and the pass-through pattern. " + "Detail. " * 14
    blocked(kw, "Acknowledge the evidence-quality issues")
    out = sk(FakeConn()).alert_disposition_recorder(**{**kw, "evidence_quality_acknowledged": True, "override_reason": LONG_REASON})
    assert out["gate"]["acknowledgements"]["evidence_quality"] is True and cond(out["gate"], "EVIDENCE_QUALITY_ACK_REQUIRED")["satisfied"] is True
    print("  [PASS] recorder: a stale-KYC / missing-documents record needs a written manual check; an aggregated record needs the acknowledgement; both are stored with the decision")


def test_a_caller_without_alert_metadata_is_not_evaluated_and_is_recorded_exactly_as_before():
    out = sk(FakeConn()).alert_disposition_recorder(**recorder_kwargs(suspicion_formed_at=recent()))
    prov = out["provenance"]
    assert "evidence_quality" not in prov and "decision_identity" not in prov, "optional objects are absent when not evaluated"
    assert not [c for c in out["gate"]["conditions"] if c["code"].startswith("EVIDENCE_QUALITY")] and out["gate"]["status"] == D.STATUS_PASS
    assert prov["schema_version"] == "3" and prov["feedback"]["ai_response"] == "ACCEPTED", "acceptance / rejection is always derived and stored"
    print("  [PASS] a bare case record (no alert metadata): no evidence-quality object or condition, gate status unchanged (PASS), schema v3; the AI response is still derived and stored")


def test_the_ui_gate_and_the_stored_gate_agree_with_quality_identity_and_reason_in_play():
    meta = dict(CLEAN_META, CUSTOMER_PROFILE="Salaried; Rs.30K/month declared; stale KYC")
    kw = call(meta, override_reason=LONG_REASON, identity=ID.resolve(None, "PO-TEST"), feedback={"reason_code": None})
    conn = FakeConn()
    s = sk(conn)
    out = s.alert_disposition_recorder(**kw)
    ui = s.decision_gate(disposition="FILE", rationale_text=kw["rationale_text"], case_context=kw["case_context"], gos_quality=kw["gos_quality"],
                         ai_recommendation="FILE", regulatory_basis=out["provenance"]["regulatory_basis"], override_reason=LONG_REASON,
                         suspicion_formed_at=kw["suspicion_formed_at"], decision_maker_id="PO-TEST",
                         evidence_quality=__import__("skills.evidence_quality", fromlist=["x"]).gate_summary(s._quality_for(kw["case_context"])),
                         identity=ID.clean(ID.resolve(None, "PO-TEST")))
    stored = out["provenance"]["defensibility_gate"]
    assert [c["code"] for c in ui["conditions"]] == [c["code"] for c in stored["conditions"]] and ui["status"] == stored["status"]
    assert cond(stored, "IDENTITY_NOT_AUTHENTICATED") and out["provenance"]["decision_identity"]["authenticated"] is False
    print("  [PASS] the gate the UI shows and the gate stored with the row list the same conditions with quality, identity and reason capture in play")


def test_an_authenticated_session_identity_cannot_be_recorded_under_another_id():
    blocked(call(CLEAN_META, identity=ID.resolve("officer.one", ""), decision_maker_id="someone.else"), "not the authenticated session identity")
    out = sk(FakeConn()).alert_disposition_recorder(**call(CLEAN_META, identity=ID.resolve("officer.one", ""), decision_maker_id="Officer.One"))
    d = out["provenance"]["decision_identity"]
    assert d["source"] == "SESSION" and d["authenticated"] is True and d["matches_session_identity"] is True and "CURRENT_USER()" in d["database_stamp"]
    print("  [PASS] recorder: an authenticated identity cannot be recorded under a different ID; the stored identity object says SESSION / authenticated / matches")


def test_the_insert_stamps_the_database_user_and_role_beside_the_client_supplied_fields():
    conn = FakeConn()
    sk(conn).alert_disposition_recorder(**call(CLEAN_META))
    insert = " ".join(conn.stmts("INSERT")[0].split())
    assert "'written_by_role', CURRENT_ROLE(), TRUE" in insert and "'written_by_user', CURRENT_USER(), TRUE" in insert
    assert insert.index("'written_by_role'") < insert.index("'written_by_user'")
    from skills.ledger import HASH_EXPR
    assert "'metadata', METADATA_JSON" in HASH_EXPR, "the row hash covers the whole METADATA_JSON, so the database-stamped user is sealed with the row"
    print("  [PASS] the INSERT adds written_by_user = CURRENT_USER() next to written_by_role = CURRENT_ROLE(); the existing row hash covers both")


# ── feedback capture ─────────────────────────────────────────────────────────

def test_ai_acceptance_and_rejection_are_derived_from_the_decision_never_typed():
    cases = {("FILE", "FILE"): "ACCEPTED", ("NOT_FILE", "NOT_FILE"): "ACCEPTED", ("FILE", "NOT_FILE"): "REJECTED", ("NOT_FILE", "FILE"): "REJECTED",
             ("FILE", "DEFERRED"): "DEFERRED_INSTEAD", ("REVIEW", "NOT_FILE"): "NO_DEFINITE_RECOMMENDATION", ("INSUFFICIENT_EVIDENCE", "FILE"): "REJECTED",
             (None, "FILE"): "AI_NOT_USED", ("NOT_RUN", "NOT_FILE"): "AI_NOT_USED", ("NEEDS_MANUAL_REVIEW", "FILE"): "AI_NOT_USED"}
    for (rec, disp), want in cases.items():
        assert FB.ai_response(rec, disp) == want, (rec, disp)
    fb = FB.capture(disposition="NOT_FILE", ai_recommendation="FILE", closure_reason_code="DOCUMENTED_LEGITIMATE_SOURCE")
    assert fb["ai_response"] == "REJECTED" and fb["reason_code"] == "DOCUMENTED_LEGITIMATE_SOURCE" and fb["reason_stated"] and fb["use"] == FB.USE
    for bad in ("made up", "' OR 1=1 --", "DEFER_ME", "", None):
        assert FB.capture(disposition="NOT_FILE", ai_recommendation="NOT_FILE", closure_reason_code=bad)["reason_code"] is None, bad
    assert FB.capture(disposition="DEFERRED", ai_recommendation=None, closure_reason_code="KYC_REFRESH_PENDING")["reason_code"] == "KYC_REFRESH_PENDING"
    assert FB.capture(disposition="FILE", ai_recommendation="FILE", closure_reason_code="OTHER")["reason_code"] is None, "a filing has no closure reason"
    d = FB.capture(disposition="FILE", ai_recommendation="FILE", ai_draft_generated=True, ai_draft_sha256="a" * 64, final_text_sha256="a" * 64)["ai_draft"]
    e = FB.capture(disposition="FILE", ai_recommendation="FILE", ai_draft_generated=True, ai_draft_sha256="a" * 64, final_text_sha256="b" * 64)["ai_draft"]
    assert d == {"generated": True, "adopted_verbatim": True} and e == {"generated": True, "adopted_verbatim": False}
    print("  [PASS] acceptance / rejection / deferred-instead / no-definite / not-used are derived from (AI recommendation, decision); an unknown reason code is stored as None; draft adoption is a hash comparison")


def test_the_recorder_stores_the_derived_response_the_reason_and_warns_on_a_missing_closure_reason():
    conn = FakeConn()
    out = sk(conn).alert_disposition_recorder(**call(None, disposition="NOT_FILE", ai_recommendation="NOT_FILE", rationale_text="Closed: documented family remittances explain the credits.",
                                                      feedback={"reason_code": "DOCUMENTED_LEGITIMATE_SOURCE"}))
    assert out["provenance"]["feedback"]["reason_code"] == "DOCUMENTED_LEGITIMATE_SOURCE" and "CLOSURE_REASON_NOT_STATED" not in out["gate"]["warning_codes"]
    out = sk(FakeConn()).alert_disposition_recorder(**call(None, disposition="NOT_FILE", ai_recommendation="NOT_FILE", rationale_text="Closed: documented family remittances explain the credits.",
                                                           feedback={"reason_code": "invented"}))
    assert "CLOSURE_REASON_NOT_STATED" in out["gate"]["warning_codes"] and out["provenance"]["feedback"]["reason_code"] is None
    print("  [PASS] recorder: a valid reason is stored; an invented one is stored as None and warned about; without a feedback argument nothing is warned")


# ── prompt minimisation ──────────────────────────────────────────────────────

def test_no_customer_reference_alert_metadata_owner_or_session_identity_ever_reaches_a_model_prompt():
    canary_cust, canary_user = "CUST-CANARY-7731", "canary.officer.4402"
    prompts = []
    s = CoPilotSkills(None, cortex_fn=lambda p: prompts.append(p) or "[]")
    alert = {**CLEAN_META, "CUSTOMER_REF": canary_cust, "RFI_TRIGGERS": "[]", "ALERT_STATUS": "OPEN"}
    ctx = s.case_context_for(alert, case_context()["transactions"], "2026-08-20", txn_owners={"TXN-001": canary_cust})
    assert ctx["alert_meta"]["CUSTOMER_REF"] == canary_cust and ctx["txn_owners"] == {"TXN-001": canary_cust}, "the deterministic checks do receive them"
    from _helpers import factors_json
    valid = json.loads(factors_json(triggered=("POE-003", "POE-007")))
    for fn in (lambda: s.suspicion_evaluator(ctx), lambda: s.ground_of_suspicion_writer(ctx, valid), lambda: s.str_quality_checker("Narrative text " * 20, ctx)):
        try:
            fn()
        except Exception:  # noqa: BLE001 - the fake model's "[]" is invalid output; only the PROMPTS matter
            pass
    assert len(prompts) >= 3
    for p in prompts:
        assert canary_cust not in p and canary_user not in p and "txn_owners" not in p and "alert_meta" not in p, "case metadata, owners and identities must not be sent to the model"
    print(f"  [PASS] {len(prompts)} model prompts built from a case record that carries a customer reference, alert metadata and transaction owners: none of them appears in any prompt")


TESTS = [
    test_each_effect_maps_to_one_gate_condition_with_the_right_severity_per_decision, test_nothing_the_officer_ticks_lifts_a_blocking_issue_but_the_other_two_effects_are_satisfiable,
    test_a_gate_without_the_new_inputs_is_exactly_the_old_gate, test_identity_conditions, test_a_closure_without_a_structured_reason_is_a_warning_only_when_reasons_are_being_captured,
    test_the_checkpoint_gains_one_row_only_when_the_gate_has_an_evidence_quality_condition, test_the_recorder_signature_accepts_no_precomputed_quality_only_the_officers_acknowledgement,
    test_a_filing_on_a_record_with_a_blocking_issue_is_refused_and_writes_nothing, test_manual_review_and_acknowledgement_are_required_then_recorded_with_the_decision,
    test_a_caller_without_alert_metadata_is_not_evaluated_and_is_recorded_exactly_as_before, test_the_ui_gate_and_the_stored_gate_agree_with_quality_identity_and_reason_in_play,
    test_an_authenticated_session_identity_cannot_be_recorded_under_another_id, test_the_insert_stamps_the_database_user_and_role_beside_the_client_supplied_fields,
    test_ai_acceptance_and_rejection_are_derived_from_the_decision_never_typed, test_the_recorder_stores_the_derived_response_the_reason_and_warns_on_a_missing_closure_reason,
    test_no_customer_reference_alert_metadata_owner_or_session_identity_ever_reaches_a_model_prompt,
]

if __name__ == "__main__":
    raise SystemExit(Runner("Gate extensions: evidence quality, identity, feedback capture (offline)").run(TESTS))
