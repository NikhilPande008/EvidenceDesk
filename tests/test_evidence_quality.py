"""
Evidence quality — the deterministic data-quality / ambiguity / contradiction checks (skills/evidence_quality.py).

Each finding class is exercised on a small synthetic case, and the seeded demo alerts are pinned so the effect policy cannot drift
silently. Pure functions: no Snowflake, no model, no clock (`now` is passed in).

Offline. Usage:  python3 tests/test_evidence_quality.py     (or pytest)
"""

from __future__ import annotations

import json
import sys
from datetime import date

from _helpers import ROOT, Runner

sys.path.insert(0, str(ROOT / "scripts"))
import setup_alerts as seed  # noqa: E402

from skills import evidence_quality as Q  # noqa: E402

NOW = date(2026, 10, 3)


def txn(tid, typ, amt, cp, d="2026-08-10", flagged=False, channel="UPI"):
    return {"txn_id": tid, "date": d, "type": typ, "amount_inr": amt, "channel": channel, "counterparty": cp, "is_flagged": flagged}


def alert(**kw):
    base = {"ALERT_ID": "A-1", "CUSTOMER_REF": "CUST-X", "ALERT_DATE": "2026-08-12", "ALERT_TYPE": "MULE_PASSTHROUGH", "SIGNAL_SOURCE": "INTERNAL_RULE",
            "CUSTOMER_PROFILE": "Salaried employee; Rs.40K/month declared; account 3 years old", "ALERT_AMOUNT_INR": 100000, "ALERT_NARRATIVE": "Pass-through pattern.",
            "ALERT_STATUS": "OPEN"}
    base.update(kw)
    return base


def clean_txns():
    return [txn("T1", "CREDIT", 60000, "Alice Traders", "2026-06-01"), txn("T2", "CREDIT", 40000, "Bob Stores", "2026-07-01"),
            txn("T3", "DEBIT", 90000, "Carol Services", "2026-08-10")]


def by_code(q):
    return {f["code"]: f for f in q["findings"]}


def seeded(aid):
    a = next(x for x in seed.ALERTS if x["ALERT_ID"] == aid)
    tx = [{"txn_id": t["TXN_ID"], "date": t["TXN_DATE"], "type": t["TXN_TYPE"], "amount_inr": t["AMOUNT_INR"], "channel": t["CHANNEL"],
           "counterparty": t["COUNTERPARTY"], "is_flagged": t["IS_FLAGGED"]} for t in seed.TRANSACTIONS if t["ALERT_ID"] == aid]
    return a, tx


# ── the four effects, each reachable ─────────────────────────────────────────

def test_a_clean_record_has_no_issue_that_gates_a_decision():
    q = Q.assess(alert(), clean_txns(), now=NOW)
    assert q["evaluated"] and q["policy_version"] == Q.POLICY_VERSION
    assert q["counts"][Q.BLOCKS_FILING] == q["counts"][Q.REQUIRES_MANUAL_REVIEW] == q["counts"][Q.REQUIRES_ACKNOWLEDGEMENT] == 0, q["findings"]
    assert q["sufficiency_pct"] >= 85 and not q["blocks_filing"]
    print(f"  [PASS] a complete, consistent record: no blocking / manual-review / acknowledgement issue; sufficiency {q['sufficiency_pct']}%")


def test_each_of_the_four_effects_is_produced_by_a_named_condition():
    got = {}
    got[Q.BLOCKS_FILING] = by_code(Q.assess(alert(CUSTOMER_PROFILE=""), clean_txns(), now=NOW))["KYC_PROFILE_MISSING"]["effect"]
    got[Q.REQUIRES_MANUAL_REVIEW] = by_code(Q.assess(alert(CUSTOMER_PROFILE="Salaried employee; Rs.40K/month; stale KYC (3 years)"), clean_txns(), now=NOW))["KYC_CURRENCY_FLAG"]["effect"]
    agg = [txn("T1", "CREDIT", 100000, "Multiple counterparties (see alert narrative)", "2026-08-12")]
    got[Q.REQUIRES_ACKNOWLEDGEMENT] = by_code(Q.assess(alert(), agg, now=NOW))["TXN_SUMMARY_ONLY"]["effect"]
    got[Q.INFORMATIONAL] = by_code(Q.assess(alert(), agg, now=NOW))["TXN_NO_BASELINE"]["effect"]
    assert set(got) == set(Q.EFFECTS) and all(got[e] == e for e in Q.EFFECTS), got
    assert Q.EFFECTS == (Q.INFORMATIONAL, Q.REQUIRES_ACKNOWLEDGEMENT, Q.REQUIRES_MANUAL_REVIEW, Q.BLOCKS_FILING)
    print("  [PASS] informational · requires acknowledgement · requires manual review · blocks filing: each produced by a named, structured condition")


def test_missing_kyc_missing_history_and_the_unreadable_record_are_distinguished():
    q = Q.assess(alert(), [], now=NOW)
    assert by_code(q)["TXN_NONE"]["effect"] == Q.BLOCKS_FILING and by_code(q)["TXN_NONE"]["enforced_by"] == "NO_TRANSACTION_RECORD"
    q = Q.assess(alert(), [], now=NOW, transactions_error=True)
    assert "TXN_UNREADABLE" in by_code(q) and "TXN_NONE" not in by_code(q), "a read failure is never reported as 'no transactions'"
    for placeholder in ("", "   ", "N/A", "unknown", "Not provided", "-"):
        assert "KYC_PROFILE_MISSING" in by_code(Q.assess(alert(CUSTOMER_PROFILE=placeholder), clean_txns(), now=NOW)), repr(placeholder)
    assert "KYC_PROFILE_SPARSE" in by_code(Q.assess(alert(CUSTOMER_PROFILE="Customer record"), clean_txns(), now=NOW))
    print("  [PASS] missing KYC (empty / placeholder), no transactions and an unreadable record are three different findings")


def test_stale_records_are_surfaced_with_the_policy_thresholds():
    q = Q.assess(alert(ALERT_DATE="2026-09-30"), [txn("T1", "CREDIT", 100000, "Alice Traders", "2026-08-01")], now=NOW)
    assert "TXN_RECORD_STALE" in by_code(q) and by_code(q)["TXN_RECORD_STALE"]["effect"] == Q.INFORMATIONAL
    q = Q.assess(alert(ALERT_DATE="2026-08-12"), [txn("T1", "CREDIT", 100000, "Alice Traders", "2026-08-12")], now=NOW)
    assert "ALERT_AGED" in by_code(q) and "TXN_NO_BASELINE" in by_code(q)
    q = Q.assess(alert(ALERT_DATE="2026-09-30"), [txn("T1", "CREDIT", 100000, "Alice Traders", "2026-09-29")], now=NOW)
    assert "ALERT_AGED" not in by_code(q), "a three-day-old alert is not aged"
    q = Q.assess(alert(ALERT_STATUS="REVIEWED"), clean_txns(), now=NOW)
    assert "ALERT_AGED" not in by_code(q), "a decided alert is not reported as an old open one"
    print(f"  [PASS] stale transaction record (≥{Q.STALE_RECORD_DAYS} d before the alert), aged open alert (≥{Q.ALERT_AGED_DAYS} d) and no-baseline history are reported at the stated thresholds")


def test_contradictions_amount_flags_future_dates_and_malformed_rows():
    for gap, expect in ((0.005, None), (0.05, Q.REQUIRES_ACKNOWLEDGEMENT), (0.18, Q.REQUIRES_MANUAL_REVIEW), (0.40, Q.BLOCKS_FILING)):
        q = Q.assess(alert(ALERT_AMOUNT_INR=100000), [txn("T1", "CREDIT", 100000 * (1 + gap), "Alice Traders", "2026-06-01")], now=NOW)
        got = by_code(q).get("AMOUNT_RECONCILIATION")
        assert (got["effect"] if got else None) == expect, (gap, got)
    flagged = [txn("T1", "CREDIT", 50000, "Alice Traders", "2026-06-01"), txn("T2", "DEBIT", 20000, "Carol Services (I4C-flagged)", flagged=True),
               txn("T3", "DEBIT", 20000, "Carol Services", flagged=False)]
    assert by_code(Q.assess(alert(ALERT_AMOUNT_INR=50000), flagged, now=NOW))["FLAG_INCONSISTENT"]["effect"] == Q.REQUIRES_MANUAL_REVIEW
    assert by_code(Q.assess(alert(), [txn("T1", "CREDIT", 100000, "A", "2026-12-01")], now=NOW))["TXN_FUTURE_DATED"]["effect"] == Q.REQUIRES_MANUAL_REVIEW
    bad = [txn("T1", "CREDIT", 100000, "A"), txn("T1", "DEBIT", -5, "B"), txn("T3", "TRANSFER", 10, "C")]
    q = by_code(Q.assess(alert(), bad, now=NOW))
    assert q["TXN_INVALID"]["effect"] == Q.BLOCKS_FILING and "T1" in q["TXN_INVALID"]["detail"]
    print("  [PASS] amount mismatch ≤1 % ok · 1–10 % acknowledge · 10–25 % manual review · >25 % blocks; inconsistent flags, future dates and malformed rows are caught")


def test_documents_referenced_versus_documents_stated_missing():
    cp = [txn("T1", "CREDIT", 100000, "Brother (KYC-linked family)", "2026-06-01")]
    q = by_code(Q.assess(alert(), cp, now=NOW))
    assert q["DOCUMENTS_REFERENCED"]["effect"] == Q.INFORMATIONAL and "DOCUMENTS_MISSING_STATED" not in q
    q = by_code(Q.assess(alert(ALERT_NARRATIVE="Customer claims property sale proceeds. Sale documentation not yet produced."), clean_txns(), now=NOW))
    assert q["DOCUMENTS_MISSING_STATED"]["effect"] == Q.REQUIRES_MANUAL_REVIEW and q["DOCUMENTS_MISSING_STATED"]["source"] == "text_pattern"
    q = by_code(Q.assess(alert(ALERT_NARRATIVE="All documentary evidence produced within 3 days."), clean_txns(), now=NOW))
    assert "DOCUMENTS_MISSING_STATED" not in q, "'produced' is not 'not produced'"
    print("  [PASS] documents the record cites (informational, not openable here) are separate from documents it says are missing (manual review)")


def test_unsupported_claims_in_the_detector_text_and_unresolved_identity():
    a = alert(ALERT_NARRATIVE="Credits of Rs.9,500 daily via NEFT to Dubai.")
    q = by_code(Q.assess(a, clean_txns(), now=NOW))
    assert q["DETECTOR_CLAIMS_UNCORROBORATED"]["effect"] == Q.REQUIRES_ACKNOWLEDGEMENT and q["DETECTOR_CLAIMS_UNCORROBORATED"]["source"] == "text_pattern"
    agg = [txn("T1", "CREDIT", 100000, "Multiple counterparties (see alert narrative)", "2026-08-12")]
    assert by_code(Q.assess(a, agg, now=NOW))["DETECTOR_CLAIMS_UNCHECKABLE"]["effect"] == Q.INFORMATIONAL, "an aggregated record cannot test the claims at all"
    owners = {"T1": "CUST-X", "T2": "CUST-OTHER", "T3": "CUST-X"}
    assert by_code(Q.assess(alert(), clean_txns(), now=NOW, txn_owners=owners))["TXN_OWNER_MISMATCH"]["effect"] == Q.REQUIRES_MANUAL_REVIEW
    assert "TXN_OWNER_MISMATCH" not in by_code(Q.assess(alert(), clean_txns(), now=NOW, txn_owners={"T1": "CUST-X"}))
    assert by_code(Q.assess(alert(ALERT_TYPE="DEVICE_IDENTITY_LINKAGE"), clean_txns(), now=NOW))["LINKED_ENTITIES_NOT_SUPPLIED"]["effect"] == Q.REQUIRES_MANUAL_REVIEW
    near = [txn("T1", "CREDIT", 50000, "ABC Infrastructure Ltd", "2026-06-01"), txn("T2", "CREDIT", 50000, "ABC Infrastructure Limited", "2026-07-01"),
            txn("T3", "DEBIT", 90000, "Carol Services", "2026-08-10")]
    assert "COUNTERPARTY_NEAR_DUPLICATE" in by_code(Q.assess(alert(), near, now=NOW))
    unk = [txn("T1", "CREDIT", 50000, "Unknown UPI handle A", "2026-06-01"), txn("T2", "CREDIT", 50000, "Unknown UPI handle B", "2026-07-01")]
    assert by_code(Q.assess(alert(), unk, now=NOW))["COUNTERPARTY_UNIDENTIFIED"]["effect"] == Q.INFORMATIONAL
    print("  [PASS] unsupported detector claims (acknowledge when checkable, informational when not), other-customer rows, un-supplied linked entities, near-duplicate and unidentified counterparties")


def test_a_free_text_pattern_can_never_block_filing():
    """The policy rule: only structured fields may stop a filing. A text pattern asks for a manual review at most."""
    worst = {}
    for aid in [a["ALERT_ID"] for a in seed.ALERTS]:
        a, tx = seeded(aid)
        for f in Q.assess(a, tx, now=NOW)["findings"]:
            if f["source"] == "text_pattern":
                worst[f["code"]] = max(worst.get(f["code"], 0), Q.RANK[f["effect"]])
    assert worst and max(worst.values()) <= Q.RANK[Q.REQUIRES_MANUAL_REVIEW], worst
    # even if a rule asked for it, `add` downgrades a text-pattern BLOCK
    import inspect
    assert "source == \"text_pattern\" and effect == BLOCKS_FILING" in inspect.getsource(Q.assess)
    print(f"  [PASS] {len(worst)} text-pattern finding codes across the 16 seeded alerts: none above 'requires manual review'; the downgrade rule is in the code")


# ── the seeded demo alerts ───────────────────────────────────────────────────

def test_the_demo_pair_gets_informational_findings_only_so_the_demo_flow_is_unchanged():
    for aid in ("ALERT-01", "ALERT-16"):
        a, tx = seeded(aid)
        q = Q.assess(a, tx, now=NOW)
        gating = {e: n for e, n in q["counts"].items() if e != Q.INFORMATIONAL and n}
        assert not gating, (aid, gating)
    a1, t1 = seeded("ALERT-01")
    a16, t16 = seeded("ALERT-16")
    q16 = by_code(Q.assess(a16, t16, now=NOW))
    assert "SIGNAL_NOT_CORROBORATED" in q16 and "DOCUMENTS_REFERENCED" in q16, "the legitimate twin: registry signal without a flag, documented counterparties"
    assert "COUNTERPARTY_UNIDENTIFIED" in by_code(Q.assess(a1, t1, now=NOW))
    print("  [PASS] ALERT-01 and ALERT-16: informational findings only (so the PO's decision gate is unchanged for the demo); the twin's uncorroborated signal and documents are named")


def test_seeded_aggregated_alerts_need_an_acknowledgement_and_the_policy_is_pinned():
    expect_ack = {a["ALERT_ID"] for a in seed.ALERTS if a["ALERT_ID"] not in seed.EXPLICIT_TXNS}      # the alerts that still carry only a summary row: 06, 09, 10, 13
    assert expect_ack == {"ALERT-06", "ALERT-09", "ALERT-10", "ALERT-13"}, expect_ack
    for aid in sorted(expect_ack):
        a, tx = seeded(aid)
        assert "TXN_SUMMARY_ONLY" in by_code(Q.assess(a, tx, now=NOW)), aid
    for aid, code in (("ALERT-11", "KYC_CURRENCY_FLAG"), ("ALERT-14", "KYC_CURRENCY_FLAG"), ("ALERT-03", "DOCUMENTS_MISSING_STATED"),
                      ("ALERT-06", "DOCUMENTS_MISSING_STATED"), ("ALERT-09", "LINKED_ENTITIES_NOT_SUPPLIED"), ("ALERT-10", "LINKED_ENTITIES_NOT_SUPPLIED"),
                      ("ALERT-04", "DETECTOR_CLAIMS_UNCORROBORATED"), ("ALERT-02", "DETECTOR_CLAIMS_UNCORROBORATED")):
        a, tx = seeded(aid)
        assert code in by_code(Q.assess(a, tx, now=NOW)), (aid, code)
    for a in seed.ALERTS:
        _, tx = seeded(a["ALERT_ID"])
        assert not Q.assess(a, tx, now=NOW)["blocks_filing"], f"{a['ALERT_ID']}: no seeded alert may be un-fileable by this policy"
    print("  [PASS] the 4 aggregate-only seed alerts need an acknowledgement; KYC / documents / linked-entity / detector-claim findings sit on the alerts whose text says so; none is blocked outright")


# ── the output contract ──────────────────────────────────────────────────────

def test_next_evidence_is_labelled_a_suggestion_and_is_built_from_fixed_templates():
    a, tx = seeded("ALERT-03")
    q = Q.assess(a, tx, now=NOW)
    assert q["next_evidence"] and "not conclusions" in q["next_evidence_label"].lower() and "suggested" in q["next_evidence_label"].lower()
    templates = {v[3] for v in Q.CATALOG.values()}
    assert all(s["step"] in templates for s in q["next_evidence"]), "a next-evidence step must be a catalogue template"
    steps = [s["step"] for s in q["next_evidence"]]
    assert len(steps) == len(set(steps)) and len(steps) <= 8
    assert [Q.RANK[s["effect"]] for s in q["next_evidence"]] == sorted((Q.RANK[s["effect"]] for s in q["next_evidence"]), reverse=True), "most serious first"
    print("  [PASS] recommended next evidence: labelled 'Suggested investigation steps — not conclusions', fixed templates only, de-duplicated, most serious first")


def test_assess_is_deterministic_and_never_reads_the_clock_or_a_model():
    a, tx = seeded("ALERT-02")
    assert json.dumps(Q.assess(a, tx, now=NOW), sort_keys=True, default=str) == json.dumps(Q.assess(a, tx, now=NOW), sort_keys=True, default=str)
    assert Q.assess(a, tx, now=date(2026, 8, 25))["findings"] != Q.assess(a, tx, now=date(2026, 12, 25))["findings"], "the date only enters through `now`"
    src = open(ROOT / "skills/evidence_quality.py").read()
    for banned in ("snowflake", "cortex", "_cortex_complete", "datetime.now", "random"):
        assert banned not in src.replace("date.today()", ""), banned
    print("  [PASS] same inputs → same findings; the date enters only through `now`; no database, model or randomness in the module")


def test_the_gate_summary_and_the_stored_snapshot_carry_no_case_text():
    hostile = "![x](https://attacker.example/p.png) [click](https://attacker.example/x) <img src=x onerror=alert(1)>"
    a = alert(ALERT_TYPE="DEVICE_IDENTITY_LINKAGE", ALERT_NARRATIVE="stale KYC. " + hostile, CUSTOMER_REF=hostile)
    tx = [txn("T1", "CREDIT", 100000, hostile + " (I4C-flagged)", "2026-06-01", flagged=True), txn("T2", "DEBIT", 99000, hostile, "2026-06-02")]
    q = Q.assess(a, tx, now=NOW, txn_owners={"T1": "other"})
    snap, gate = Q.stored_snapshot(q), Q.gate_summary(q)
    blob = json.dumps([snap, gate])
    assert "attacker" not in blob and len(blob) < 6000, "stored and gate copies hold codes, effects and static titles only"
    assert snap["schema"] == "evidence_quality/1" and gate["manual_review"] and gate["blocking"] == []
    assert Q.stored_snapshot(None) is None and Q.gate_summary(None) is None and Q.gate_summary({"evaluated": False}) is None
    # the enforced-elsewhere codes are listed but not double counted
    g = Q.gate_summary(Q.assess(alert(), [], now=NOW))
    assert g["blocking"] == [] and [b["code"] for b in g["blocking_enforced_elsewhere"]] == ["TXN_NONE"]
    print("  [PASS] gate summary and ledger snapshot hold codes + effects + static titles (0 bytes of case text); findings the gate enforces under another code are not double-counted")


TESTS = [
    test_a_clean_record_has_no_issue_that_gates_a_decision, test_each_of_the_four_effects_is_produced_by_a_named_condition,
    test_missing_kyc_missing_history_and_the_unreadable_record_are_distinguished, test_stale_records_are_surfaced_with_the_policy_thresholds,
    test_contradictions_amount_flags_future_dates_and_malformed_rows, test_documents_referenced_versus_documents_stated_missing,
    test_unsupported_claims_in_the_detector_text_and_unresolved_identity, test_a_free_text_pattern_can_never_block_filing,
    test_the_demo_pair_gets_informational_findings_only_so_the_demo_flow_is_unchanged, test_seeded_aggregated_alerts_need_an_acknowledgement_and_the_policy_is_pinned,
    test_next_evidence_is_labelled_a_suggestion_and_is_built_from_fixed_templates, test_assess_is_deterministic_and_never_reads_the_clock_or_a_model,
    test_the_gate_summary_and_the_stored_snapshot_carry_no_case_text,
]

if __name__ == "__main__":
    raise SystemExit(Runner("Evidence quality (offline)").run(TESTS))
