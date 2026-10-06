"""
Independent-review protocol — pure deterministic logic (offline, no Snowflake).

Covers: reference resolution (txn / rule / fact key, and rejection of arbitrary strings),
provisional & reconciliation completeness, the three trigger classes (including the no-AI path and
the "no AI assessment is NOT no gap" rule), near-verbatim overlap + deferral, the provenance object
builder/validator (hostile text, draft text never stored), and the ledger schema-version behaviour.
"""

import importlib

import pytest

from skills import human_review as hr
from skills.evidence import signal_brief
from skills.ledger import (
    PROVENANCE_SCHEMA_VERSION, PROVENANCE_SCHEMA_VERSION_WITH_REVIEW,
    REQUIRED_PROVENANCE_KEYS_BY_VERSION, build_provenance, missing_provenance,
)

# ── fixtures ──────────────────────────────────────────────────────────────────
TXNS = [
    {"txn_id": "T1", "type": "CREDIT", "amount_inr": 345000, "channel": "NEFT",
     "counterparty": "ACME (kyc-linked)", "is_flagged": False, "date": "2026-01-01"},
    {"txn_id": "T2", "type": "DEBIT", "amount_inr": 340000, "channel": "NEFT",
     "counterparty": "MULE-9 (I4C-flagged)", "is_flagged": True, "date": "2026-01-02"},
]
ALERT_META = {"ALERT_AMOUNT_INR": 345000, "SIGNAL_SOURCE": "I4C", "CUSTOMER_PROFILE": "Salaried, Rs 40k/mo"}


def _ctx(txn_ids=("T1", "T2"), rule_ids=("STR-001", "STR-002"), with_facts=True):
    snap = hr.fact_key_snapshot(signal_brief=signal_brief(TXNS), alert_meta=ALERT_META) if with_facts else {}
    return hr.ReferenceContext(txn_ids=txn_ids, rule_ids=rule_ids, fact_snapshot=snap)


# ── fact-key snapshot + reference resolution ───────────────────────────────────
def test_fact_key_snapshot_from_signal_brief():
    snap = hr.fact_key_snapshot(signal_brief=signal_brief(TXNS), alert_meta=ALERT_META)
    assert snap["flagged_counterparty_count"] == 1
    assert snap["transaction_count"] == 2
    assert snap["signal_source"] == "I4C"
    assert snap["alert_amount"] == 345000
    # only keys with a value are present
    assert all(v is not None for v in snap.values())


def test_reference_resolution_kinds():
    ctx = _ctx()
    assert ctx.resolve("T1")["kind"] == "txn"
    assert ctx.resolve("STR-002")["kind"] == "rule"
    fk = ctx.resolve("flagged_counterparty_count")
    assert fk["kind"] == "fact_key" and fk["resolved"] and fk["value"] == 1


def test_arbitrary_string_is_never_a_reference():
    ctx = _ctx()
    r = ctx.resolve("the transactions look dodgy")
    assert r["kind"] == "invalid" and r["resolved"] is False
    assert ctx.any_valid(["not-a-real-id", "also fake"]) is False


def test_fact_key_not_in_snapshot_is_invalid():
    ctx = _ctx(with_facts=False)                     # no fact snapshot for this case
    assert ctx.resolve("flagged_counterparty_count")["resolved"] is False


def test_reference_scope_is_per_case():
    case_a = hr.ReferenceContext(txn_ids=["T1"])
    case_b = hr.ReferenceContext(txn_ids=["TX-99"])
    assert case_a.resolve("T1")["resolved"] is True
    assert case_b.resolve("T1")["resolved"] is False   # must not migrate between cases


# ── provisional completeness ───────────────────────────────────────────────────
def test_provisional_complete():
    ctx = _ctx()
    prov = {"view": hr.VIEW_SUSPICION, "evidence_refs": ["T2"], "unanswered_question": "source of the credit?"}
    assert hr.provisional_missing(prov, ctx) == []


def test_provisional_missing_each_field():
    ctx = _ctx()
    assert "view" in hr.provisional_missing({"evidence_refs": ["T1"], "unanswered_question": "x"}, ctx)
    assert "evidence_refs" in hr.provisional_missing(
        {"view": hr.VIEW_SUSPICION, "evidence_refs": ["bogus"], "unanswered_question": "x"}, ctx)
    assert "unanswered_question" in hr.provisional_missing(
        {"view": hr.VIEW_SUSPICION, "evidence_refs": ["T1"], "unanswered_question": "  "}, ctx)
    assert set(hr.provisional_missing(None, ctx)) == {"view", "evidence_refs", "unanswered_question"}


# ── reconciliation completeness ────────────────────────────────────────────────
def test_reconciliation_file_requires_counter_and_justification():
    ctx = _ctx()
    good = {"material_counter_evidence": "the 4 documented credits argue against",
            "counter_evidence_refs": ["T1"], "change_reason": "the flagged onward debit still dominates"}
    assert hr.reconciliation_missing(good, disposition="FILE", ctx=ctx) == []
    bad = {"material_counter_evidence": "", "counter_evidence_refs": [], "change_reason": ""}
    miss = hr.reconciliation_missing(bad, disposition="FILE", ctx=ctx)
    assert "material_counter_evidence" in miss and "counter_evidence_refs" in miss and "why_file_despite_counter" in miss


def test_reconciliation_closure_innocent_explanation():
    ctx = _ctx()
    good = {"material_counter_evidence": "none of the triggered factors is grounded", "none_material": True,
            "accepted_innocent_explanation": "documented property sale", "accepted_explanation_refs": ["T1"],
            "remaining_uncertainty": "deed not independently verified"}
    assert hr.reconciliation_missing(good, disposition="NOT_FILE", ctx=ctx) == []
    miss = hr.reconciliation_missing({"material_counter_evidence": "x", "none_material": True}, disposition="NOT_FILE", ctx=ctx)
    assert "accepted_innocent_explanation" in miss


def test_reconciliation_deferred_needs_next_evidence():
    ctx = _ctx()
    miss = hr.reconciliation_missing({"material_counter_evidence": "x", "none_material": True}, disposition="DEFERRED", ctx=ctx)
    assert miss == ["next_evidence_needed"]


def test_none_material_waives_ref_but_not_response():
    ctx = _ctx()
    # none_material=True: no counter_evidence_ref demanded, but the reason (material_counter_evidence) is still required
    miss = hr.reconciliation_missing({"none_material": True, "next_evidence_needed": "bank statement"},
                                     disposition="DEFERRED", ctx=ctx)
    assert miss == ["material_counter_evidence"]


# ── trigger classes ─────────────────────────────────────────────────────────────
def test_no_ai_flagged_closure_requires_review_via_always_class():
    r = hr.independent_review_required(
        disposition="NOT_FILE", transactions=TXNS, has_supported_basis=True, ai_ran=False)
    assert r["required"] is True
    codes = {t["code"] for t in r["triggers"]}
    assert "CLOSE_WITH_FLAGGED_TXN" in codes
    assert r["classes_present"] == ["always"]          # no AI classes evaluated on the no-AI path


def test_no_assessment_is_not_no_gap():
    # A no-AI, otherwise-clean FILE: no always-available trigger fires, and the missing assessment is NOT
    # interpreted as "no gap" (no ai_derived trigger is fabricated as 'clear').
    clean = [{"txn_id": "T1", "type": "CREDIT", "amount_inr": 1, "is_flagged": False}]
    r = hr.independent_review_required(
        disposition="FILE", transactions=clean, has_supported_basis=True, ai_ran=False,
        ai_recommendation="FILE", sufficiency=None, challenge=None)
    assert r["required"] is False
    assert "ai_derived" not in r["classes_present"] and "ai_comparison" not in r["classes_present"]


def test_no_ai_path_ignores_ai_comparison_triggers():
    # ai_recommendation present but ai_ran False → DECISION_CONTRADICTS_AI must NOT fire.
    r = hr.independent_review_required(
        disposition="NOT_FILE", transactions=[{"txn_id": "T1", "is_flagged": False}],
        has_supported_basis=True, ai_ran=False, ai_recommendation="FILE")
    assert {t["code"] for t in r["triggers"]} == set()
    assert r["required"] is False


def test_ai_derived_and_comparison_triggers_fire_only_when_ai_ran():
    r = hr.independent_review_required(
        disposition="FILE", transactions=[{"txn_id": "T1", "is_flagged": False}], has_supported_basis=True,
        ai_ran=True, ai_recommendation="INSUFFICIENT_EVIDENCE",
        sufficiency={"gaps": [{"factor_id": "POE-006"}]}, challenge={"strength": "strong"})
    codes = {t["code"] for t in r["triggers"]}
    assert {"AI_EVIDENCE_GAPS", "AI_CHALLENGE_STRONG", "AI_WEAK_BUT_FILES"} <= codes


def test_decision_contradicts_ai_fires():
    r = hr.independent_review_required(
        disposition="NOT_FILE", transactions=[{"txn_id": "T1", "is_flagged": False}], has_supported_basis=True,
        ai_ran=True, ai_recommendation="FILE")
    assert "DECISION_CONTRADICTS_AI" in {t["code"] for t in r["triggers"]}


def test_no_supported_basis_and_unreadable_txns_always_fire():
    r1 = hr.independent_review_required(disposition="FILE", transactions=TXNS, has_supported_basis=False, ai_ran=False)
    assert "NO_SUPPORTED_REGULATORY_BASIS" in {t["code"] for t in r1["triggers"]}
    r2 = hr.independent_review_required(disposition="NOT_FILE", transactions=None,
                                        transactions_readable=False, has_supported_basis=True, ai_ran=False)
    assert "TXN_RECORD_UNREADABLE" in {t["code"] for t in r2["triggers"]}


def test_source_of_funds_and_rfi_triggers():
    r = hr.independent_review_required(
        disposition="NOT_FILE", transactions=[{"txn_id": "T1", "is_flagged": False}], has_supported_basis=True,
        ai_ran=False, source_of_funds_required=True, source_of_funds_documented=False, unresolved_required_rfi=True)
    codes = {t["code"] for t in r["triggers"]}
    assert {"SOURCE_OF_FUNDS_UNDOCUMENTED", "UNRESOLVED_REQUIRED_RFI"} <= codes


# ── near-verbatim overlap + deferral ────────────────────────────────────────────
def test_near_verbatim_overlap():
    assert hr.near_verbatim_overlap("the customer moved 345000 onward", "the customer moved 345000 onward") == 100.0
    assert hr.near_verbatim_overlap("alpha beta gamma delta", "zeta eta theta iota") == 0.0
    assert hr.near_verbatim_overlap("", "something") is None


def test_ai_draft_fingerprint_deferred_without_draft():
    fp = hr.ai_draft_fingerprint(None, "final narrative")
    assert fp == {"ai_draft_hash": None, "ai_draft_overlap_pct": None}
    fp2 = hr.ai_draft_fingerprint("final narrative text", "final narrative text")
    assert fp2["ai_draft_hash"] and fp2["ai_draft_overlap_pct"] == 100.0


# ── build + validate the provenance object ──────────────────────────────────────
def test_build_human_review_shape_and_draft_not_stored():
    obj = hr.build_human_review(
        provisional={"view": hr.VIEW_SUSPICION, "evidence_refs": ["T2"], "unanswered_question": "src?", "saved_at": "2026-01-01T00:00:00Z"},
        ai_reveal={"assessment_used": True, "recommendation": "FILE", "revealed_at": "2026-01-01T00:05:00Z"},
        final_reconciliation={"final_decision": "FILE", "material_counter_evidence": "x", "counter_evidence_refs": ["T1"],
                              "change_reason": "y", "finalized_at": "2026-01-01T00:10:00Z"},
        interaction_observations={"opened_transaction_detail": True},
        ai_draft="draft narrative text", final_text="final narrative text")
    assert obj["schema_version"] == hr.HUMAN_REVIEW_SCHEMA_VERSION
    assert obj["enforcement_scope"] == "normal_ui_path"
    assert obj["final_reconciliation"]["ai_draft_hash"]
    assert obj["interaction_observations"]["opened_regulatory_basis"] is False   # missing stays False, never inferred
    # the draft TEXT itself is never stored anywhere in the object
    import json
    assert "draft narrative text" not in json.dumps(obj)


def test_build_human_review_clips_hostile_text():
    obj = hr.build_human_review(
        provisional={"view": hr.VIEW_SUSPICION, "evidence_refs": ["T1"], "unanswered_question": "Q" * 20000},
        ai_reveal={}, final_reconciliation={"final_decision": "NOT_FILE"})
    assert len(obj["provisional"]["unanswered_question"]) <= hr._CLIP


def test_build_human_review_stores_the_recorder_requirement():
    obj = hr.build_human_review(
        provisional={"view": hr.VIEW_SUSPICION, "evidence_refs": ["T1"], "unanswered_question": "q"},
        ai_reveal={}, final_reconciliation={"final_decision": "NOT_FILE"},
        review_requirement={"required": True, "triggers": [{"code": "CLOSE_WITH_FLAGGED_TXN"}], "classes_present": ["always"]})
    rr = obj["review_requirement"]
    assert rr["required"] is True and rr["triggers"] == ["CLOSE_WITH_FLAGGED_TXN"] and rr["classes_present"] == ["always"]
    # absent requirement → a well-formed, empty default (not missing)
    empty = hr.build_human_review(provisional={}, ai_reveal={}, final_reconciliation={})
    assert empty["review_requirement"] == {"required": False, "triggers": [], "classes_present": []}


def test_validate_human_review():
    good = hr.build_human_review(
        provisional={"view": hr.VIEW_INSUFFICIENT, "evidence_refs": ["T1"], "unanswered_question": "q"},
        ai_reveal={}, final_reconciliation={"final_decision": "DEFERRED"})
    assert hr.validate_human_review(good) == []
    assert hr.validate_human_review("not a dict") == ["not an object"]
    bad = dict(good)
    bad["provisional"] = {"view": "NONSENSE", "evidence_refs": "not-a-list"}
    probs = hr.validate_human_review(bad)
    assert "provisional.view" in probs and "provisional.evidence_refs" in probs


# ── ledger schema-version behaviour (backward compatible) ───────────────────────
def test_provenance_without_review_stays_v3():
    p = build_provenance(
        disposition="NOT_FILE", ai_recommendation=None, override_reason=None, corpus_version="1.1.0",
        regulatory_basis={}, model_name=None, prompt_version="p", skill_version="s", evidence_txn_ids=[],
        transactions=[], poe_assessment=[], gos_narrative="n", gos_quality=None,
        unverified_claims_acknowledged=None)
    assert p["schema_version"] == PROVENANCE_SCHEMA_VERSION == "3"
    assert "human_review" not in p


def test_provenance_with_review_is_v4_and_carries_it():
    review = hr.build_human_review(
        provisional={"view": hr.VIEW_SUSPICION, "evidence_refs": ["T1"], "unanswered_question": "q"},
        ai_reveal={}, final_reconciliation={"final_decision": "FILE"})
    p = build_provenance(
        disposition="FILE", ai_recommendation="FILE", override_reason=None, corpus_version="1.1.0",
        regulatory_basis={}, model_name="m", prompt_version="p", skill_version="s", evidence_txn_ids=[],
        transactions=[], poe_assessment=[], gos_narrative="n", gos_quality=None,
        unverified_claims_acknowledged=None, human_review=review)
    assert p["schema_version"] == PROVENANCE_SCHEMA_VERSION_WITH_REVIEW == "4"
    assert p["human_review"] == review
    # version-scoped completeness: human_review is NOT reported missing when present (written_by_role is
    # injected later at INSERT time, so it is expected absent here), and IS reported missing when null.
    assert "human_review" not in missing_provenance(p)
    incomplete = dict(p); incomplete["human_review"] = None
    assert "human_review" in missing_provenance(incomplete)


def test_v3_required_keys_do_not_include_human_review():
    assert "human_review" not in REQUIRED_PROVENANCE_KEYS_BY_VERSION["3"]
    assert "human_review" in REQUIRED_PROVENANCE_KEYS_BY_VERSION["4"]


def test_feature_flag(monkeypatch):
    monkeypatch.delenv("FIU_HUMAN_REVIEW", raising=False)
    importlib.reload(hr)
    assert hr.enabled() is False
    monkeypatch.setenv("FIU_HUMAN_REVIEW", "1")
    assert hr.enabled() is True
