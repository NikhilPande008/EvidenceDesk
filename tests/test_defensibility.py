"""
Decision-defensibility gate (skills/defensibility.py): ONE deterministic pre-recording result with every blocking / warning /
acknowledgement / override condition, each with a stable machine-readable code — used by the UI and by the ledger recorder, and
persisted in the decision's provenance.

Covers every code, and every pass / warning / blocked / acknowledgement / override path; determinism; hostile claim text;
the UI-and-ledger-use-the-same-result guarantee. Offline (pure functions + a recording fake database).
Usage:  python3 tests/test_defensibility.py     (or pytest)
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from _helpers import FakeConn, Runner, basis_for, recorder_kwargs, scan_sql

from skills import defensibility as D

OK_EVIDENCE = {"passed": True, "unsupported_claims_by_type": {}, "unverified_assertions": []}
LONG_REASON = "I reviewed the statements and every figure myself and take responsibility."
TEXT = "A substantive Ground of Suspicion citing the recorded credits and debits in detail."


def gate(**over) -> dict:
    kw = dict(disposition="FILE", rationale_text=TEXT, has_case_context=True, transaction_count=3, evidence_gate=OK_EVIDENCE,
              gos_status="READY", ai_recommendation="FILE", regulatory_basis=basis_for(["STR-001"]), override_reason=None,
              unverified_claims_acknowledged=None, assumed_basis_acknowledged=None, sla_days_remaining=5)
    kw.update(over)
    return D.evaluate(**kw)


# Phase 14 inputs (evidence quality, identity, closure reason): the shapes skills/evidence_quality.gate_summary and skills/identity.clean return
EQ_SUMMARY = {"blocking": [{"code": "KYC_PROFILE_MISSING", "title": "No KYC profile in the record"}], "blocking_enforced_elsewhere": [],
              "manual_review": [{"code": "TXN_FUTURE_DATED", "title": "A transaction is dated in the future"}],
              "acknowledgement": [{"code": "TXN_SUMMARY_ONLY", "title": "Every transaction row is an aggregated summary"}], "informational": 1, "sufficiency_pct": 40}


def codes(g: dict) -> list[str]:
    return [c["code"] for c in g["conditions"]]


def cond(g: dict, code: str) -> dict:
    return next(c for c in g["conditions"] if c["code"] == code)


# ── pass / warning ───────────────────────────────────────────────────────────

def test_clean_filing_passes():
    g = gate()
    assert g["status"] == D.STATUS_PASS and g["can_record"] and not g["blocking_codes"] and not g["pending_codes"] and not g["warning_codes"]
    assert set(codes(g)) <= {"BASIS_NOT_INDEPENDENTLY_VERIFIED", "NEEDS_VERIFICATION_RULES_AS_TAGS"}, codes(g)
    assert all(c["severity"] == D.INFO for c in g["conditions"]), "only informational notes on a clean filing"
    print("  [PASS] clean FILE (grounded text, READY GoS, AI agrees, PROVEN basis) → PASS, only INFO notes")


def test_warning_path_is_recorded_but_does_not_block():
    g = gate(disposition="NOT_FILE", ai_recommendation=None, sla_days_remaining=-3)
    assert g["status"] == D.STATUS_PASS_WITH_WARNINGS and g["can_record"]
    assert {"NO_AI_RECOMMENDATION", "SLA_OVERDUE"} <= set(g["warning_codes"]), g["warning_codes"]
    assert cond(g, "SLA_OVERDUE")["detail"] == {"sla_days_remaining": -3}
    ev = {"passed": False, "unsupported_claims_by_type": {"amount": ["₹25.00L"]}, "unverified_assertions": []}
    g = gate(disposition="NOT_FILE", evidence_gate=ev, ai_recommendation="NOT_FILE")
    assert g["can_record"] and "UNSUPPORTED_FACTS_IN_RATIONALE" in g["warning_codes"], "a closure rationale with unsupported facts is recorded WITH a warning"
    g = gate(disposition="DEFERRED", has_case_context=False, evidence_gate=None, ai_recommendation="NOT_RUN")
    assert g["can_record"] and "EVIDENCE_GATE_NOT_RUN" in g["warning_codes"]
    print("  [PASS] warning path: NO_AI_RECOMMENDATION / SLA_OVERDUE / UNSUPPORTED_FACTS_IN_RATIONALE / EVIDENCE_GATE_NOT_RUN → PASS_WITH_WARNINGS, recordable")


# ── blocked ──────────────────────────────────────────────────────────────────

BLOCK_SCENARIOS = {
    "INVALID_DISPOSITION": dict(disposition="DELETE_EVERYTHING"),
    "RATIONALE_TOO_SHORT": dict(rationale_text="too short"),
    "CASE_CONTEXT_MISSING": dict(has_case_context=False, evidence_gate=None),
    "NO_TRANSACTION_RECORD": dict(transaction_count=0),
    "EVIDENCE_GATE_FAILED": dict(evidence_gate={"passed": False, "unsupported_claims_by_type": {"amount": ["₹25.00L"], "channel": ["SWIFT"]}, "unverified_assertions": []}),
    "NO_SUPPORTED_REGULATORY_BASIS": dict(regulatory_basis=basis_for(["RFI-001"])),
    "REGULATORY_BASIS_UNAVAILABLE": dict(regulatory_basis=None),
}


def test_every_blocking_condition_blocks_and_nothing_the_po_can_tick_overrides_it():
    for code, over in BLOCK_SCENARIOS.items():
        g = gate(**over)
        assert g["status"] == D.STATUS_BLOCKED and not g["can_record"] and code in g["blocking_codes"], (code, g["status"], codes(g))
        assert cond(g, code)["severity"] == D.BLOCK and cond(g, code)["satisfied"] is False
        escalated = gate(**over, override_reason=LONG_REASON, unverified_claims_acknowledged=True, assumed_basis_acknowledged=True)
        assert not escalated["can_record"] and code in escalated["blocking_codes"], f"{code} must not be overridable"
    unavailable = gate(regulatory_basis=basis_for(["STR-001"], error="corpus unreadable: boom"))
    assert "REGULATORY_BASIS_UNAVAILABLE" in unavailable["blocking_codes"], "an unreadable corpus is fail-closed, not 'unknown'"
    print(f"  [PASS] {len(BLOCK_SCENARIOS)} BLOCK conditions each stop the write, and an override reason + every acknowledgement cannot lift them")


def test_no_transactions_reports_the_specific_reason_not_a_generic_gate_failure():
    g = gate(transaction_count=0, evidence_gate={"passed": False, "unsupported_claims_by_type": {"evidence": ["no transactions on record"]}, "unverified_assertions": []})
    assert "NO_TRANSACTION_RECORD" in g["blocking_codes"] and "EVIDENCE_GATE_FAILED" not in g["blocking_codes"]
    print("  [PASS] no transactions → NO_TRANSACTION_RECORD (specific), not a duplicate EVIDENCE_GATE_FAILED")


# ── acknowledgement + override paths ─────────────────────────────────────────

def test_assumed_basis_needs_explicit_acknowledgement_for_a_filing():
    b = basis_for(["STR-001", "POE-003"])
    assert b["requires_assumed_acknowledgement"] and b["assumed_rule_ids"] == ["POE-003"]
    pending = gate(regulatory_basis=b)
    c = cond(pending, "ASSUMED_RULES_IN_FILING_BASIS")
    assert pending["status"] == D.STATUS_ACTION_REQUIRED and not pending["can_record"] and c["satisfied"] is False
    assert c["severity"] == D.ACK_REQUIRED and c["detail"]["assumed_rule_ids"] == ["POE-003"]
    done = gate(regulatory_basis=b, assumed_basis_acknowledged=True)
    assert done["can_record"] and cond(done, "ASSUMED_RULES_IN_FILING_BASIS")["satisfied"] is True
    assert "ASSUMED_RULES_IN_FILING_BASIS" in done["satisfied_codes"] and done["acknowledgements"]["assumed_basis"] is True
    assert done["acknowledgements"]["assumed_rule_ids"] == ["POE-003"]
    print("  [PASS] ASSUMED rules in a filing basis: blocks until acknowledged (recorded with the rule IDs)")


def test_assumed_basis_needs_acknowledgement_for_a_closure_but_not_for_a_deferral():
    b = basis_for(["STR-001", "POE-003"])
    closure = gate(disposition="NOT_FILE", ai_recommendation="NOT_FILE", regulatory_basis=b)
    c = cond(closure, "ASSUMED_RULES_IN_CLOSURE_BASIS")
    assert c["severity"] == D.ACK_REQUIRED and c["satisfied"] is False and not closure["can_record"] and closure["status"] == D.STATUS_ACTION_REQUIRED
    assert "ASSUMED_RULES_IN_FILING_BASIS" not in codes(closure), "a closure gets the closure code, not the filing code"
    done = gate(disposition="NOT_FILE", ai_recommendation="NOT_FILE", regulatory_basis=b, assumed_basis_acknowledged=True)
    assert done["can_record"] and cond(done, "ASSUMED_RULES_IN_CLOSURE_BASIS")["satisfied"] is True and done["acknowledgements"]["assumed_basis"] is True
    esc = gate(disposition="ESCALATE", ai_recommendation="REVIEW", regulatory_basis=b)
    assert "ASSUMED_RULES_IN_CLOSURE_BASIS" in esc["pending_codes"], "ESCALATE concludes something too"
    deferral = gate(disposition="DEFERRED", ai_recommendation="REVIEW", regulatory_basis=b)
    assert deferral["can_record"] and "ASSUMED_RULES_IN_BASIS" in deferral["info_codes"] and not deferral["pending_codes"], "a deferral concludes nothing: INFO only"
    print("  [PASS] ASSUMED rules: FILE and closure/escalation need the acknowledgement (distinct codes); a deferral gets an INFO note only")


def test_a_missing_principal_officer_id_blocks_every_decision_but_none_means_not_evaluated():
    for disp in ("FILE", "NOT_FILE", "DEFERRED", "ESCALATE"):
        for blank in ("", "   "):
            g = gate(disposition=disp, ai_recommendation="REVIEW" if disp != "FILE" else "FILE", decision_maker_id=blank,
                     regulatory_basis=basis_for(["STR-001"]))
            assert "PO_ID_MISSING" in g["blocking_codes"] and not g["can_record"], (disp, repr(blank))
    ok = gate(decision_maker_id="PO-7")
    assert "PO_ID_MISSING" not in codes(ok) and ok["can_record"]
    assert "PO_ID_MISSING" not in codes(gate()), "None = a caller that does not evaluate it (older code paths)"
    assert cond(gate(decision_maker_id=""), "PO_ID_MISSING")["severity"] == D.BLOCK
    print("  [PASS] blank Principal Officer ID → BLOCK for FILE / NOT_FILE / DEFERRED / ESCALATE; None means 'not evaluated'")


def test_unverified_assertions_need_acknowledgement():
    ev = {"passed": True, "unsupported_claims_by_type": {}, "unverified_assertions": [{"text": "known links to hawala operators", "why": "third-party claim"}]}
    pending = gate(evidence_gate=ev)
    assert cond(pending, "UNVERIFIED_ASSERTIONS_IN_NARRATIVE")["satisfied"] is False and pending["status"] == D.STATUS_ACTION_REQUIRED
    done = gate(evidence_gate=ev, unverified_claims_acknowledged=True)
    assert done["can_record"] and done["acknowledgements"]["unverified_claims"] is True and done["acknowledgements"]["unverified_assertion_count"] == 1
    print("  [PASS] UNVERIFIED assertions: ACTION_REQUIRED until acknowledged; the acknowledgement and the count are recorded")


def test_override_paths_need_a_written_reason_of_the_minimum_length():
    for label, over, code in (("GoS not READY", dict(gos_status="NEEDS_REVISION"), "GOS_NOT_READY"),
                              ("never checked", dict(gos_status=None), "GOS_NOT_READY"),
                              ("contradicts the AI", dict(disposition="NOT_FILE", ai_recommendation="FILE"), "DECISION_DIFFERS_FROM_AI"),
                              ("AI cannot support filing", dict(ai_recommendation="INSUFFICIENT_EVIDENCE"), "DECISION_DIFFERS_FROM_AI")):
        none = gate(**over)
        short = gate(**over, override_reason="because")
        enough = gate(**over, override_reason=LONG_REASON)
        assert cond(none, code)["severity"] == D.OVERRIDE_REQUIRED and not none["can_record"], label
        assert not short["can_record"] and cond(short, code)["satisfied"] is False, f"{label}: a short reason must not count"
        assert enough["can_record"] and cond(enough, code)["satisfied"] is True and enough["acknowledgements"]["override_reason_recorded"] is True, label
    assert gate(disposition="DEFERRED", ai_recommendation="FILE")["can_record"], "DEFERRED is never an override"
    assert gate(ai_recommendation="REVIEW")["can_record"], "REVIEW is not a contradiction"
    print("  [PASS] override paths (GoS not READY / never checked / contradicts AI / AI cannot support): blocked until ≥20 chars; recorded")


# ── informational + warning basis conditions ─────────────────────────────────

def test_basis_conditions_superseded_nv_stale_unverified():
    sup = basis_for(["STR-001", "POE-003"], overrides={"POE-003": {"SUPERSEDED_BY": "POE-099"}})
    g = gate(regulatory_basis=sup)
    assert "SUPERSEDED_RULE_CITED" in g["warning_codes"] and g["can_record"], "a superseded rule beside a current one is a WARNING"
    assert cond(g, "SUPERSEDED_RULE_CITED")["detail"]["superseded"] == [{"rule_id": "POE-003", "superseded_by": "POE-099"}]
    only = gate(regulatory_basis=basis_for(["POE-003"], overrides={"POE-003": {"SUPERSEDED_BY": "POE-099"}}))
    assert "NO_SUPPORTED_REGULATORY_BASIS" in only["blocking_codes"], "a superseded rule cannot be the ONLY basis of a filing"
    g = gate(regulatory_basis=basis_for(["STR-001", "RFI-001"]))
    assert "NEEDS_VERIFICATION_RULES_AS_TAGS" in g["info_codes"] and cond(g, "NEEDS_VERIFICATION_RULES_AS_TAGS")["detail"]["rule_ids"] == ["RFI-001"]
    stale = basis_for(["STR-001"], overrides={"STR-001": {"REVIEW_STATUS": "VERIFIED", "LAST_VERIFIED": "2020-01-01", "VERIFIED_BY": "reviewer"}})
    assert "BASIS_REVIEW_STALE" in gate(regulatory_basis=stale)["warning_codes"]
    fresh = basis_for(["STR-001"], overrides={"STR-001": {"REVIEW_STATUS": "VERIFIED", "LAST_VERIFIED": datetime.now(timezone.utc).date().isoformat(), "VERIFIED_BY": "reviewer"}})
    assert "BASIS_NOT_INDEPENDENTLY_VERIFIED" not in codes(gate(regulatory_basis=fresh)), "a genuinely verified rule needs no 'unverified' note"
    assert "BASIS_NOT_INDEPENDENTLY_VERIFIED" in codes(gate())
    print("  [PASS] basis: superseded → WARN (or BLOCK when it is the only basis) · NV → INFO tag note · stale review → WARN · verified rule → no 'unverified' note")


def test_non_file_decisions_with_no_basis_are_recorded_with_a_warning():
    g = gate(disposition="NOT_FILE", ai_recommendation="NOT_FILE", regulatory_basis=basis_for(["RFI-001"]))
    assert g["can_record"] and "NO_SUPPORTED_BASIS_FOR_CLOSURE" in g["warning_codes"]
    g = gate(disposition="NOT_FILE", ai_recommendation="NOT_FILE", regulatory_basis=None)
    assert g["can_record"] and "REGULATORY_BASIS_UNAVAILABLE_FOR_CLOSURE" in g["warning_codes"]
    print("  [PASS] a closure without a supported basis is recorded WITH a warning; only a FILING is blocked")


# ── registry, determinism, consistency ───────────────────────────────────────

def test_every_registered_code_is_reachable_and_has_one_stable_severity():
    seen: dict[str, str] = {}
    scenarios = [gate(**o) for o in BLOCK_SCENARIOS.values()]
    scenarios += [
        gate(regulatory_basis=basis_for(["STR-001", "POE-003"])),
        gate(evidence_gate={"passed": True, "unsupported_claims_by_type": {}, "unverified_assertions": [{"text": "x", "why": "y"}]}),
        gate(gos_status="NEEDS_REVISION"), gate(disposition="NOT_FILE", ai_recommendation="FILE"),
        gate(disposition="NOT_FILE", ai_recommendation=None, sla_days_remaining=-1, regulatory_basis=basis_for(["RFI-001"]),
             evidence_gate={"passed": False, "unsupported_claims_by_type": {"date": ["2020-01-01"]}, "unverified_assertions": []}),
        gate(disposition="NOT_FILE", has_case_context=False, evidence_gate=None, regulatory_basis=None),
        gate(disposition="NOT_FILE", ai_recommendation="NOT_FILE", regulatory_basis=basis_for(["STR-001", "POE-003"])),
        gate(disposition="DEFERRED", ai_recommendation="REVIEW", regulatory_basis=basis_for(["STR-001", "POE-003"])),
        gate(decision_maker_id=""),
        gate(evidence_quality=EQ_SUMMARY),                                                                  # FILE: blocks + acknowledgement + manual review
        gate(disposition="NOT_FILE", ai_recommendation="NOT_FILE", evidence_quality=EQ_SUMMARY, closure_reason_stated=False),
        gate(identity={"id": "typed-id", "source": "TYPED", "authenticated": False}),
        gate(identity={"id": "officer.one", "source": "SESSION", "authenticated": True}, decision_maker_id="someone.else"),
        gate(regulatory_basis=basis_for(["STR-001", "POE-003", "RFI-001"], overrides={"POE-003": {"SUPERSEDED_BY": "POE-099"}})),
        gate(regulatory_basis=basis_for(["STR-001"], overrides={"STR-001": {"REVIEW_STATUS": "VERIFIED", "LAST_VERIFIED": "2020-01-01", "VERIFIED_BY": "r"}})),
        gate(prior_decisions=[{"decision_id": "d-1", "disposition": "FILE"}]),                              # a further decision on an already-decided alert
        gate(ai_draft_adopted_verbatim=True),                                                              # the AI's draft recorded unchanged
    ]
    for g in scenarios:
        for c in g["conditions"]:
            assert seen.setdefault(c["code"], c["severity"]) == c["severity"], f"{c['code']} appeared with two severities"
            assert D.CONDITIONS[c["code"]][0] == c["severity"], "a code's severity comes from the registry only"
    unreached = set(D.CONDITIONS) - set(seen)
    assert not unreached, f"registry codes no scenario triggers (add one): {sorted(unreached)}"
    assert set(seen) <= set(D.CONDITIONS)
    print(f"  [PASS] all {len(D.CONDITIONS)} registered condition codes are reachable; each has exactly one severity")


def test_gate_is_deterministic_and_a_stored_copy_cannot_be_quietly_edited():
    a, b = gate(regulatory_basis=basis_for(["STR-001", "POE-003"])), gate(regulatory_basis=basis_for(["STR-001", "POE-003"]))
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True), "same inputs → byte-identical result"
    assert D.gate_consistent(a) and D.gate_consistent(gate())
    forged = json.loads(json.dumps(a)); forged["status"] = "PASS"; forged["can_record"] = True
    assert not D.gate_consistent(forged), "status edited without the conditions"
    dropped = json.loads(json.dumps(a)); dropped["conditions"] = [c for c in dropped["conditions"] if c["severity"] != D.ACK_REQUIRED]
    assert not D.gate_consistent(dropped), "a condition removed from the stored copy"
    relabelled = json.loads(json.dumps(a)); relabelled["conditions"][0]["severity"] = "INFO"
    assert not D.gate_consistent(relabelled)
    assert not D.gate_consistent(None) and not D.gate_consistent({"conditions": "x"})
    print("  [PASS] deterministic (byte-identical for identical inputs); an edited / thinned / relabelled stored gate is detected")


def test_hostile_claim_text_is_bounded_in_the_gate():
    hostile = "'; DROP TABLE FIU_COPILOT.AML.DECISION_LEDGER; -- " + "A" * 20_000
    ev = {"passed": False, "unsupported_claims_by_type": {"amount": [hostile] * 40, "entity": [hostile, "ok"]},
          "unverified_assertions": [{"text": hostile, "why": "w"}] * 9}
    g = gate(evidence_gate=ev)
    size = len(json.dumps(g))
    assert size < 8_000, f"a hostile 20 000-character claim must not bloat the stored gate ({size} bytes)"
    c = cond(g, "EVIDENCE_GATE_FAILED")
    assert len(c["detail"]["unsupported_claims_by_type"]["amount"]) <= 6 and all(len(x) <= 160 for x in c["detail"]["unsupported_claims_by_type"]["amount"])
    assert len(c["message"]) < 1_200
    print(f"  [PASS] 20 000-character hostile claims ×40 → stored gate {size} bytes, every quoted claim ≤ 160 characters")


# ── the UI and the ledger use the SAME gate, and the ledger stores it ────────

def _sk(conn):
    from skills import CoPilotSkills
    return CoPilotSkills(conn)


def _recent() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_the_ui_gate_and_the_stored_gate_are_the_same_object():
    conn = FakeConn()
    sk = _sk(conn)
    kw = recorder_kwargs(suspicion_formed_at=_recent())
    basis = sk.rule_basis(kw["rules_cited"])
    ui_gate = sk.decision_gate(
        disposition=kw["disposition"], rationale_text=kw["rationale_text"], case_context=kw["case_context"], gos_quality=kw["gos_quality"],
        ai_recommendation=kw["ai_recommendation"], regulatory_basis=basis, suspicion_formed_at=kw["suspicion_formed_at"])
    out = sk.alert_disposition_recorder(**kw)
    stored = out["provenance"]["defensibility_gate"]
    assert json.dumps(ui_gate, sort_keys=True) == json.dumps(stored, sort_keys=True), "UI gate ≠ stored gate for identical inputs"
    assert out["provenance"]["acknowledgements"] == stored["acknowledgements"] == ui_gate["acknowledgements"]
    assert out["gate"] == stored
    # the stored copy is what was written to the database row
    meta = next(lit for lit in scan_sql(conn.stmts("INSERT")[0])[1] if lit.startswith("{") and "defensibility_gate" in lit)
    assert json.loads(meta)["defensibility_gate"] == stored
    print("  [PASS] gate computed for the UI == gate stored in the ledger row's provenance (same function, same inputs, identical bytes)")


def test_recorder_refuses_exactly_what_the_gate_refuses_and_writes_nothing():
    for label, over in (("fabricated facts", dict(rationale_text="Credits of ₹25,00,000 were wired by SWIFT to Dubai on 2026-08-27. " * 3)),
                        ("no case context", dict(case_context=None)),
                        ("AI contradicts, no reason", dict(disposition="NOT_FILE", ai_recommendation="FILE")),
                        ("GoS not READY, no reason", dict(gos_quality={"status": "NEEDS_REVISION", "quality_score": 6, "hard_gate_passed": True, "ai_output_valid": True}))):
        conn = FakeConn()
        kw = recorder_kwargs(**over)
        try:
            _sk(conn).alert_disposition_recorder(**kw)
            raise AssertionError(f"{label}: recorded!")
        except Exception as err:  # noqa: BLE001
            assert type(err).__name__ == "LedgerBlocked", (label, repr(err))
        assert not conn.stmts("INSERT") and not conn.stmts("BEGIN") and not conn.stmts("COMMIT"), f"{label}: nothing may be written"
    print("  [PASS] recorder refuses fabricated facts / missing context / unexplained AI contradiction / non-READY GoS — no INSERT, no transaction")


def test_recorded_decisions_store_the_gate_and_the_acknowledgements_on_every_path():
    # pass
    out = _sk(FakeConn()).alert_disposition_recorder(**recorder_kwargs(suspicion_formed_at=_recent()))
    g = out["provenance"]["defensibility_gate"]
    assert g["status"] == D.STATUS_PASS and out["provenance"]["schema_version"] == "3" and g["gate_version"] == D.GATE_VERSION
    # warning (closure, overdue SLA, no AI recommendation)
    old = (datetime.now(timezone.utc) - timedelta(days=40)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = _sk(FakeConn()).alert_disposition_recorder(**recorder_kwargs(
        disposition="NOT_FILE", ai_recommendation=None, suspicion_formed_at=old, rationale_text="Closed: documented family remittances explain the credits; no onward flow to flagged parties."))
    g = out["provenance"]["defensibility_gate"]
    assert g["status"] == D.STATUS_PASS_WITH_WARNINGS and {"SLA_OVERDUE", "NO_AI_RECOMMENDATION"} <= set(g["warning_codes"])
    # override (GoS not READY + reason) — the override and its reason are both persisted
    q = {"status": "NEEDS_REVISION", "quality_score": 6, "hard_gate_passed": True, "ai_output_valid": True}
    out = _sk(FakeConn()).alert_disposition_recorder(**recorder_kwargs(gos_quality=q, override_reason=LONG_REASON, suspicion_formed_at=_recent()))
    g, meta = out["provenance"]["defensibility_gate"], out["provenance"]
    assert cond(g, "GOS_NOT_READY")["satisfied"] is True and meta["override_reason"] == LONG_REASON and g["acknowledgements"]["override_reason_recorded"] is True
    # ASSUMED basis acknowledgement persisted next to the basis object
    conn = FakeConn()
    kw = recorder_kwargs(rules_cited=["STR-001", "POE-003"], assumed_basis_acknowledged=True, suspicion_formed_at=_recent())
    out = _sk(conn).alert_disposition_recorder(**kw)
    meta = out["provenance"]
    assert meta["acknowledgements"]["assumed_basis"] is True and meta["acknowledgements"]["assumed_rule_ids"] == ["POE-003"]
    assert meta["regulatory_basis"]["assumed_rule_ids"] == ["POE-003"] and meta["regulatory_basis"]["requires_assumed_acknowledgement"] is True
    # unverified acknowledgement persisted
    text = "I formed suspicion after the recorded credits. The beneficiary has known links to organised crime networks."
    out = _sk(FakeConn()).alert_disposition_recorder(**recorder_kwargs(rationale_text=text + " " + "Further detail on the pattern. " * 3, unverified_claims_acknowledged=True, suspicion_formed_at=_recent()))
    assert out["provenance"]["acknowledgements"]["unverified_claims"] is True and out["provenance"]["acknowledgements"]["unverified_assertion_count"] >= 1
    print("  [PASS] recorded rows carry the gate on every path: PASS · PASS_WITH_WARNINGS · override (reason) · ASSUMED acknowledgement · UNVERIFIED acknowledgement")


def test_an_assumed_filing_without_the_acknowledgement_is_refused_at_the_recorder():
    conn = FakeConn()
    try:
        _sk(conn).alert_disposition_recorder(**recorder_kwargs(rules_cited=["STR-001", "POE-003"], suspicion_formed_at=_recent()))
        raise AssertionError("an ASSUMED-basis filing was recorded without acknowledgement")
    except Exception as err:  # noqa: BLE001
        assert type(err).__name__ == "LedgerBlocked" and "ASSUMED" in str(err), repr(err)
    assert not conn.stmts("INSERT")
    print("  [PASS] FILE resting on ASSUMED rules is refused at the write layer until acknowledged")

PRIOR = [{"decision_id": "d-2", "disposition": "NOT_FILE"}, {"decision_id": "d-1", "disposition": "FILE"}]


def test_a_repeat_decision_needs_its_own_written_reason_and_a_first_decision_does_not():
    for not_looked_up in (None, []):
        g = gate(prior_decisions=not_looked_up)
        assert "REPEAT_DECISION_NEEDS_REASON" not in codes(g) and "supersede_reason_recorded" not in g["acknowledgements"], "a first decision is exactly as before"
    g = gate(prior_decisions=PRIOR)
    cond = next(c for c in g["conditions"] if c["code"] == "REPEAT_DECISION_NEEDS_REASON")
    assert cond["severity"] == D.OVERRIDE_REQUIRED and cond["satisfied"] is False and not g["can_record"] and g["status"] == D.STATUS_ACTION_REQUIRED
    assert "already has 2 recorded decision" in D.blocking_message(g) and cond["detail"]["latest_disposition"] == "NOT_FILE"
    # its own field: the override reason does not stand in for it, and it does not stand in for the override reason
    assert not gate(prior_decisions=PRIOR, override_reason="x" * 40)["can_record"], "an override reason is not a reason for superseding"
    assert not gate(prior_decisions=PRIOR, supersede_reason="too short")["can_record"]
    ok = gate(prior_decisions=PRIOR, supersede_reason="The hospital invoice was verified after the first decision.")
    assert ok["can_record"] and ok["acknowledgements"]["supersede_reason_recorded"] is True
    still = gate(prior_decisions=PRIOR, supersede_reason="The hospital invoice was verified after the first decision.", gos_status="NEEDS_REVISION")
    assert not still["can_record"] and "GOS_NOT_READY" in still["pending_codes"], "a supersede reason does not satisfy the AI-quality override"
    assert D.gate_consistent(ok) and D.gate_consistent(g)
    print("  [PASS] repeat decision: needs its own reason (>=20 chars); an override reason does not stand in for it; a first decision is unchanged")


def test_the_checkpoint_shows_the_earlier_decision_row_only_when_there_is_one():
    kw = dict(disposition="FILE", ai_state=D.AI_VALID, ai_recommendation="FILE", transaction_count=3)
    first = D.checkpoint(gate(), **kw)
    assert [r["id"] for r in first["rows"]] == ["C1", "C2", "C3", "C4", "C5", "C6", "C7"], "a first decision keeps exactly the seven rows"
    needs = D.checkpoint(gate(prior_decisions=PRIOR), **kw)
    ids = [r["id"] for r in needs["rows"]]
    assert ids == ["C1", "C2", "C3", "C4", "C5", "C6", "CR", "C7"], ids
    row = needs["rows"][ids.index("CR")]
    assert row["status"] == D.CP_NEEDS and "2 recorded decision" in row["detail"] and not needs["ready"]
    done = D.checkpoint(gate(prior_decisions=PRIOR, supersede_reason="The hospital invoice was verified after the first decision."), **kw)
    assert done["rows"][[r["id"] for r in done["rows"]].index("CR")]["status"] == D.CP_PASS and done["ready"]
    print("  [PASS] checkpoint: seven rows for a first decision; an 'Earlier decision on this alert' row appears (NEEDS YOU, then PASS) for a repeat")

def test_an_unedited_ai_draft_needs_the_officers_explicit_adoption():
    for none in (None, False):
        g = gate(ai_draft_adopted_verbatim=none)
        assert "AI_DRAFT_ADOPTED_VERBATIM" not in codes(g) and "ai_draft_adoption" not in g["acknowledgements"], "no draft, or an edited one: exactly as before"
    g = gate(ai_draft_adopted_verbatim=True)
    cond = next(c for c in g["conditions"] if c["code"] == "AI_DRAFT_ADOPTED_VERBATIM")
    assert cond["severity"] == D.ACK_REQUIRED and cond["satisfied"] is False and not g["can_record"] and "AI_DRAFT_ADOPTED_VERBATIM" in g["pending_codes"]
    assert not gate(ai_draft_adopted_verbatim=True, override_reason="x" * 40, supersede_reason="y" * 40)["can_record"], "no other reason stands in for the adoption"
    ok = gate(ai_draft_adopted_verbatim=True, ai_draft_adoption_acknowledged=True)
    assert ok["can_record"] and ok["acknowledgements"]["ai_draft_adoption"] is True and D.gate_consistent(ok)
    assert not gate(ai_draft_adopted_verbatim=True, ai_draft_adoption_acknowledged=True, gos_status="NEEDS_REVISION")["can_record"], "adoption does not satisfy the AI-quality override"
    kw = dict(disposition="FILE", ai_state=D.AI_VALID, ai_recommendation="FILE", transaction_count=3)
    rows = lambda gt: {r["id"]: r for r in D.checkpoint(gt, **kw)["rows"]}   # noqa: E731
    assert "CD" not in rows(gate()), "no such row on an edited text"
    assert rows(g)["CD"]["status"] == D.CP_NEEDS and rows(ok)["CD"]["status"] == D.CP_PASS
    print("  [PASS] AI draft recorded unchanged: needs the officer's explicit adoption (its own tick); an edited text is exactly as before")


TESTS = [
    test_clean_filing_passes, test_warning_path_is_recorded_but_does_not_block,
    test_every_blocking_condition_blocks_and_nothing_the_po_can_tick_overrides_it,
    test_no_transactions_reports_the_specific_reason_not_a_generic_gate_failure,
    test_assumed_basis_needs_explicit_acknowledgement_for_a_filing, test_assumed_basis_needs_acknowledgement_for_a_closure_but_not_for_a_deferral,
    test_a_missing_principal_officer_id_blocks_every_decision_but_none_means_not_evaluated, test_unverified_assertions_need_acknowledgement,
    test_override_paths_need_a_written_reason_of_the_minimum_length, test_basis_conditions_superseded_nv_stale_unverified,
    test_non_file_decisions_with_no_basis_are_recorded_with_a_warning,
    test_every_registered_code_is_reachable_and_has_one_stable_severity,
    test_gate_is_deterministic_and_a_stored_copy_cannot_be_quietly_edited, test_hostile_claim_text_is_bounded_in_the_gate,
    test_the_ui_gate_and_the_stored_gate_are_the_same_object, test_recorder_refuses_exactly_what_the_gate_refuses_and_writes_nothing,
    test_recorded_decisions_store_the_gate_and_the_acknowledgements_on_every_path,
    test_an_assumed_filing_without_the_acknowledgement_is_refused_at_the_recorder,
    test_a_repeat_decision_needs_its_own_written_reason_and_a_first_decision_does_not, test_the_checkpoint_shows_the_earlier_decision_row_only_when_there_is_one,
    test_an_unedited_ai_draft_needs_the_officers_explicit_adoption,
]

if __name__ == "__main__":
    raise SystemExit(Runner("Decision-defensibility gate (offline)").run(TESTS))
