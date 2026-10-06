"""
Record-backed support for the Beneficiary and Complexity factors (skills/nexus_support.py), and what it does to the recommendation.

The replay of 16 alerts with the real model recommended FILE for ALERT-16, the legitimate twin of ALERT-01, because the model triggered
POE-007 and POE-010 on a record that does not back either. These suites pin the rule and its three promises:
  * it only DISCOUNTS, and only where the record can test the factor (no rows, no verdict);
  * it never raises a recommendation, and a caller that does not pass the rows gets exactly the old behaviour;
  * the discounted factor is still reported, with its reason, and the recommendation falls to REVIEW (never to NOT_FILE).

Offline. Usage:  python3 tests/test_nexus_support.py     (or pytest)
"""

from __future__ import annotations

import json
import sys

from _helpers import ROOT, Runner, factors_json, skills

sys.path.insert(0, str(ROOT / "scripts"))


def row(i, kind, amount, channel, cp, flagged=False, date="2026-09-09"):
    return {"txn_id": f"T-{i}", "date": date, "type": kind, "amount_inr": amount, "channel": channel, "counterparty": cp, "is_flagged": flagged}


ALERT_16 = [row(1, "CREDIT", 150000, "UPI", "Brother (KYC-linked family)"), row(2, "CREDIT", 120000, "UPI", "Father (KYC-linked family)"),
            row(3, "CREDIT", 75000, "UPI", "Sister (KYC-linked family)"), row(4, "DEBIT", 300000, "NEFT", "City General Hospital")]
ALERT_01 = [row(1, "CREDIT", 110000, "UPI", "Unknown UPI handle A"), row(2, "CREDIT", 140000, "UPI", "Unknown UPI handle B"),
            row(3, "DEBIT", 246500, "UPI", "UPI handle C (I4C-flagged)", True), row(4, "CREDIT", 95000, "UPI", "Unknown UPI handle D"),
            row(5, "DEBIT", 94200, "UPI", "UPI handle C (I4C-flagged)", True)]


def _assessment(*triggered, grounded=True):
    a = json.loads(factors_json(triggered=triggered, cite=("T-1",)))
    for f in a:
        f["ai_output_valid"] = True
        f["grounded"] = grounded if f["assessment"] == "triggered" else None
    return a


def test_the_legitimate_twin_has_neither_nexus_factor_backed_and_the_flagged_case_has_both():
    from skills import nexus_support as N
    b16, c16 = N.assess("POE-007", ALERT_16), N.assess("POE-010", ALERT_16)
    assert b16 == {"testable": True, "supported": False, "reason": "every one of the 1 outgoing row(s) goes to a named counterparty that carries no flag"}
    assert c16["testable"] and c16["supported"] is False and "pass-through shape only" in c16["reason"]
    assert N.assess("POE-007", ALERT_01)["supported"] is True and "flagged" in N.assess("POE-007", ALERT_01)["reason"]
    assert N.assess("POE-010", ALERT_01)["supported"] is True
    print("  [PASS] ALERT-16-shaped rows back neither Beneficiary nor Complexity; ALERT-01-shaped rows back both")


def test_each_support_route_is_recognised():
    from skills import nexus_support as N
    base = [row(1, "CREDIT", 100, "UPI", "Asha Kumar"), row(2, "DEBIT", 90, "NEFT", "Ravi Shah")]
    assert N.assess("POE-010", base)["supported"] is False
    assert N.assess("POE-010", base + [row(3, "DEBIT", 5, "SWIFT", "Ravi Shah")])["supported"] is True, "SWIFT channel"
    assert N.assess("POE-010", [row(1, "CREDIT", 100, "UPI", "Asha"), row(2, "DEBIT", 90, "NEFT", "Zhao Trading Co., Shenzhen, China")])["supported"] is True, "a foreign place on a row"
    cash = [row(i, "CREDIT", 9000, "CASH", f"Counter {i}") for i in range(3)] + [row(9, "DEBIT", 27000, "NEFT", "Single account")]
    assert N.assess("POE-010", cash)["supported"] is True and "structuring" in N.assess("POE-010", cash)["reason"], "three cash rows"
    assert N.assess("POE-010", cash[:2] + [row(9, "DEBIT", 18000, "NEFT", "Single account")])["supported"] is False, "two cash rows are not enough"
    unknown = [row(i, "CREDIT", 10, "UPI", f"Unidentified handle {i}") for i in range(3)] + [row(9, "DEBIT", 30, "UPI", "Handle Z")]
    assert N.assess("POE-010", unknown)["supported"] is True and "unidentified senders" in N.assess("POE-010", unknown)["reason"]
    assert N.assess("POE-007", base + [row(4, "DEBIT", 1, "UPI", "Unknown beneficiary")])["supported"] is True, "an unidentified recipient"
    print("  [PASS] cross-border hop, foreign place, three cash rows, a flagged party, three unidentified senders, an unidentified recipient: each backs the factor; two cash rows do not")


def test_the_record_that_cannot_test_a_factor_gives_no_verdict():
    from skills import nexus_support as N
    summary = [row(1, "CREDIT", 8500000, "CASH", "Multiple counterparties (see alert narrative)")]
    for fid in ("POE-007", "POE-010"):
        r = N.assess(fid, summary)
        assert r["testable"] is False and r["supported"] is None, (fid, r)
        assert N.discounted(fid, summary) is None
    assert N.assess("POE-007", [row(1, "CREDIT", 5, "UPI", "A person")])["testable"] is False, "no outgoing row: the beneficiary cannot be tested"
    assert N.assess("POE-010", None)["testable"] is False and N.discounted("POE-010", []) is None
    assert N.assess("POE-006", ALERT_16)["testable"] is False and N.discounted("POE-006", ALERT_16) is None and N.discounted("POE-011", ALERT_16) is None
    print("  [PASS] an aggregate summary row, no outgoing row, no rows at all, or a factor with no record test: no verdict, nothing is discounted")


def test_the_recommendation_falls_to_review_for_the_twin_and_stays_file_for_the_flagged_case():
    sk = skills()
    a = _assessment("POE-003", "POE-005", "POE-007", "POE-010")
    old = sk.evidence_sufficiency_summary(a)
    assert old["recommendation"] == "FILE" and old["discounted_nexus_factors"] == [], "no rows passed: exactly the old behaviour"
    twin = sk.evidence_sufficiency_summary(a, ALERT_16)
    assert twin["recommendation"] == "REVIEW" and twin["grounded_nexus_factors"] == []
    assert [d["factor_id"] for d in twin["discounted_nexus_factors"]] == ["POE-007", "POE-010"] and "DG-19" in twin["basis_note"] and "not backed by the record" in twin["basis_note"]
    assert twin["triggered_count"] == 4, "the factors stay triggered and visible; only their weight toward FILE changes"
    flagged = sk.evidence_sufficiency_summary(a, ALERT_01)
    assert flagged["recommendation"] == "FILE" and flagged["grounded_nexus_factors"] == ["POE-007", "POE-010"] and flagged["discounted_nexus_factors"] == []
    print("  [PASS] ALERT-16-shaped rows: FILE becomes REVIEW with the reason; ALERT-01-shaped rows stay FILE; no rows passed behaves exactly as before")


def test_one_supported_nexus_factor_is_enough_and_the_rule_never_raises_anything():
    sk = skills()
    mixed = _assessment("POE-003", "POE-005", "POE-007", "POE-011")           # beneficiary is discounted, geography is not testable here
    r = sk.evidence_sufficiency_summary(mixed, ALERT_16)
    assert r["recommendation"] == "FILE" and r["grounded_nexus_factors"] == ["POE-011"] and [d["factor_id"] for d in r["discounted_nexus_factors"]] == ["POE-007"]
    for assessment in (_assessment("POE-003"), _assessment("POE-003", "POE-005"), _assessment(), _assessment("POE-003", "POE-005", "POE-009")):
        before = sk.evidence_sufficiency_summary(assessment)["recommendation"]
        assert sk.evidence_sufficiency_summary(assessment, ALERT_16)["recommendation"] == before, "the rule never changes a recommendation that did not rest on a discounted nexus factor"
    ungrounded = _assessment("POE-003", "POE-005", "POE-007", grounded=False)
    assert sk.evidence_sufficiency_summary(ungrounded, ALERT_16)["discounted_nexus_factors"] == [], "an ungrounded factor was never counted, so there is nothing to discount"
    print("  [PASS] a second, supported nexus factor still carries a FILE; recommendations that never rested on the discounted factors do not move")


def test_the_challenge_to_a_file_proposal_is_strong_when_the_record_argues_against_it_twice():
    sk = skills()
    a = _assessment("POE-003", "POE-005", "POE-007", "POE-010")
    twin = sk.challenge_disposition("FILE", a, ALERT_16)
    assert {c["type"] for c in twin["counter_evidence"]} >= {"no_flagged_counterparty", "documented_sources"}
    assert twin["challenge_strength"] == "strong" and twin["recommendation_conflict"] is True, "six model-side triggers do not answer two record-side findings"
    flagged = sk.challenge_disposition("FILE", a, ALERT_01)
    assert flagged["challenge_strength"] == "none" and flagged["recommendation_conflict"] is False
    one = sk.challenge_disposition("FILE", a, [row(1, "CREDIT", 10, "UPI", "Asha"), row(2, "DEBIT", 9, "UPI", "Ravi")])
    assert one["challenge_strength"] == "moderate", "one record-side finding argues, but not decisively"
    assert sk.challenge_disposition("FILE", _assessment(), ALERT_01)["challenge_strength"] == "strong", "no triggered factor: unchanged"
    print("  [PASS] two record-side findings make the challenge STRONG even when the model triggered six factors; one makes it moderate; a flagged record leaves it at none")


def test_on_the_real_replay_of_16_alerts_the_rule_moves_exactly_one_recommendation():
    """The saved replies are the model's own words from evidence/live-replay/2026-10-05. The rule was written after ALERT-16 was seen, so this is a
    regression record, not a held-out measurement (the held-out check is the live replay of alerts written after the rule was frozen)."""
    path = ROOT / "evidence" / "live-replay" / "2026-10-05" / "results.json"
    if not path.is_file():
        print("  [SKIP] no replay evidence in this checkout")
        return
    import setup_alerts as seed
    from skills.core import POE_FACTORS
    names = dict(POE_FACTORS)
    rows = lambda aid: [{"txn_id": t["TXN_ID"], "date": t["TXN_DATE"], "type": t["TXN_TYPE"], "amount_inr": t["AMOUNT_INR"], "channel": t["CHANNEL"],  # noqa: E731
                         "counterparty": t["COUNTERPARTY"], "is_flagged": t["IS_FLAGGED"]} for t in seed.TRANSACTIONS if t["ALERT_ID"] == aid]
    sk = skills()
    moved = {}
    for r in json.loads(path.read_text())["alerts"]:
        if not r.get("assessment_valid"):
            continue
        a = [{"factor_id": f["factor_id"], "factor_name": names[f["factor_id"]], "assessment": f["assessment"], "evidence": "x", "evidence_txn_ids": f.get("evidence_txn_ids") or [],
              "rules_cited": [], "ai_output_valid": True, "grounded": f.get("grounded")} for f in r["factors"]]
        before, after = sk.evidence_sufficiency_summary(a)["recommendation"], sk.evidence_sufficiency_summary(a, rows(r["alert_id"]))["recommendation"]
        if before != after:
            moved[r["alert_id"]] = (before, after)
    assert moved == {"ALERT-16": ("FILE", "REVIEW")}, moved
    print("  [PASS] over the 16 real replies only ALERT-16 moves (FILE -> REVIEW); no FILE-labelled alert loses its FILE")


def test_the_rule_is_still_the_one_the_held_out_alerts_were_measured_against():
    """ALERT-17..19 are called held out only while this file is the one PREDICTION.md was written against. Editing the rule is allowed; doing it silently is not."""
    import hashlib
    rec = json.loads((ROOT / "evidence/heldout-gcc/2026-10-06/frozen_rule.json").read_text())
    got = hashlib.sha256((ROOT / rec["file"]).read_bytes()).hexdigest()
    assert got == rec["sha256"], (
        "skills/nexus_support.py changed after the Gulf-remittance alerts were measured against it. If the change is intended, ALERT-17..19 are no longer held out: "
        "say so in evidence/heldout-gcc/2026-10-06/FIRST_MEASUREMENT.md, update frozen_rule.json, and write new alerts to test the new rule.")
    print("  [PASS] skills/nexus_support.py is byte-identical to the rule the held-out alerts were measured against")


TESTS = [
    test_the_rule_is_still_the_one_the_held_out_alerts_were_measured_against,
    test_the_legitimate_twin_has_neither_nexus_factor_backed_and_the_flagged_case_has_both, test_each_support_route_is_recognised,
    test_the_record_that_cannot_test_a_factor_gives_no_verdict, test_the_recommendation_falls_to_review_for_the_twin_and_stays_file_for_the_flagged_case,
    test_one_supported_nexus_factor_is_enough_and_the_rule_never_raises_anything, test_the_challenge_to_a_file_proposal_is_strong_when_the_record_argues_against_it_twice,
    test_on_the_real_replay_of_16_alerts_the_rule_moves_exactly_one_recommendation,
]


if __name__ == "__main__":
    raise SystemExit(Runner("Record-backed nexus factors").run(TESTS))
