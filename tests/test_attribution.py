"""
Attribution check (skills/attribution.py): is each verified fact attached to the right party, direction, date, side and flag?

grounding.py confirms a figure, a date or a party EXISTS in the record; this checks they BELONG TOGETHER. The property that matters most is not how much it
catches but that it stays silent when a sentence is ambiguous, so most of these tests are about what it must NOT flag. Findings are SOFT: labelled UNVERIFIED and
acknowledged by the officer, never a hard block (the extraction is heuristic, and a false hard block on a true filing cannot be overridden).

Offline. Usage:  python3 tests/test_attribution.py     (or pytest)
"""

from __future__ import annotations

import sys

from _helpers import ROOT, Runner

sys.path.insert(0, str(ROOT / "tests"))

import fabrication_benchmark as B  # noqa: E402
from skills import attribution as A  # noqa: E402
from skills import defensibility as D  # noqa: E402
from skills.grounding import extract_amounts, extract_dates, validate_narrative  # noqa: E402

R01 = B.build_record("ALERT-01")["transactions"]       # 3 UPI credits (handles A, B, D), 2 debits to the I4C-flagged handle C
R02 = B.build_record("ALERT-02")["transactions"]       # cash deposits into the customer's own linked accounts, one NEFT debit
R04 = B.build_record("ALERT-04")["transactions"]       # six NEFT credits from four named companies


def found(text: str, txns=R01) -> list[dict]:
    return A.check(text, txns, extract_amounts, extract_dates)


def silent(text: str, txns=R01) -> bool:
    return not found(text, txns)


def test_each_rule_catches_the_contradiction_and_explains_it_from_the_record():
    cases = {
        "party":     ("Rs.2.465L was received from UPI handle A.", ("not with UPI handle A", "UPI handle C")),
        "direction": ("Rs.95,000 was paid to UPI handle D on 2026-08-16.", ("paid to UPI handle D", "a credit from UPI handle D")),
        "date":      ("On 2026-08-13 debits of Rs.2.465L went to UPI handle C.", ("2026-08-13", "2026-08-15")),
        "side":      ("The debits totalled Rs.3.45L.", ("total of the credits", "Rs.3,40,700")),
        "ratio":     ("98.8% of the debits were later returned.", ("over the credits",)),
        "quantifier": ("All three credits came from UPI handle C.", ("involve UPI handle C",)),
        "flag":      ("UPI handle D, which is I4C-flagged, received the money.", ("does not mark", "UPI handle C")),
    }
    for rule, (text, expected) in cases.items():
        out = found(text)
        assert len(out) == 1 and out[0]["type"] == "attribution_mismatch", (rule, out)
        for needle in expected:
            assert needle in out[0]["why"], (rule, needle, out[0]["why"])
    print(f"  [PASS] {len(cases)} rules (party, direction, date, side, ratio, quantifier, flag) each catch their contradiction and explain it from the record's own data")


def test_a_clause_with_an_amount_before_the_party_is_read_as_one_clause():
    """Found by the first measurement: 'sent Rs.1.1L to UPI handle A' went undetected because the amount's full stops ended the clause."""
    assert not silent("The customer sent Rs.1.1L to UPI handle A.")
    assert not silent("The customer paid Rs.2.465L to UPI handle B.")
    assert silent("The customer paid Rs.2.465L to UPI handle C.")
    print("  [PASS] 'sent Rs.1.1L to handle A' is one clause (the amount's decimal points do not end it)")


def test_named_senders_are_parties_even_when_the_record_calls_them_unknown():
    """Found by the first measurement: 'Unknown UPI handle A' was dropped as a generic party, so only handle C could ever be checked."""
    p = A.Parties(R01)
    assert set(p.letter) == {"A", "B", "C", "D"} and p.flagged["upi handle c"] and not p.flagged["upi handle a"]
    assert A.Parties([{"counterparty": "Unknown individual", "type": "CREDIT", "amount_inr": 1}, {"counterparty": "Multiple counterparties (see alert narrative)"}]).keys == {}
    print("  [PASS] 'Unknown UPI handle A/B/D' are named parties; 'Unknown individual' and 'Multiple counterparties' are not")


def test_correctly_bound_statements_are_never_flagged():
    for aid, rid, sentence in B.R_CORRECT:
        assert silent(sentence, B.build_record(aid)["transactions"]), (rid, sentence, found(sentence, B.build_record(aid)["transactions"]))
    for pid, sentence in B.CORRECT_ATTRIBUTIONS:
        assert silent(sentence), (pid, sentence, found(sentence))
    for aid, gid, sentence in B.REGRESSION_CORRECT:
        assert silent(sentence, B.build_record(aid)["transactions"]), (gid, sentence)
    print(f"  [PASS] {len(B.R_CORRECT) + len(B.CORRECT_ATTRIBUTIONS) + len(B.REGRESSION_CORRECT)} correctly bound statements across 4 alerts: none flagged")


def test_ambiguous_or_non_asserting_sentences_are_skipped_not_guessed_at():
    skipped = [
        "Rs.1.1L, from UPI handle A, was credited on 2026-08-13 and Rs.1.4L, from UPI handle B, on 2026-08-14.",     # two parties, two amounts
        "Rs.1.4L went from UPI handle A to UPI handle C.",                                                          # two parties: which one is the claim about?
        "Rs.2.465L was not paid to UPI handle A.",                                                                  # a negation is not an assertion
        "If Rs.1.1L had been paid to UPI handle C the pattern would differ.",                                      # a hypothetical
        "Rs.1.1L could have been received from UPI handle C.",                                                      # hedged
        "Rs.2.5L was received from UPI handle A.",                                                                  # a subset sum, not a single transaction
        "The customer received USD 1,000 from UPI handle A.",                                                       # foreign currency is the amount check's job
        "Credits totalled Rs.3.45L and debits Rs.3.407L.",                                                          # both sides named: ambiguous
        "UPI handle A, a long-standing sender, appears three times.",                                               # no amount, no flag, no quantifier
    ]
    for text in skipped:
        assert silent(text), (text, found(text))
    assert silent("Rs.1.1L was received from UPI handle A.", [])
    assert found("", R01) == [] and found("   ", R01) == []
    print(f"  [PASS] {len(skipped)} ambiguous / negated / hypothetical / hedged / non-transaction sentences are skipped; no record or no text gives no findings")


def test_sentence_splitting_survives_abbreviations_and_decimals():
    s = A.sentences("A payment of Rs. 62,500 went to Sunrise Traders Pvt. Ltd. on 2026-08-15. The credits totalled Rs.3.45L; the debits Rs.3.407L. See T01-1.")
    assert s == ["A payment of Rs. 62,500 went to Sunrise Traders Pvt. Ltd. on 2026-08-15.", "The credits totalled Rs.3.45L", "the debits Rs.3.407L.", "See T01-1."], s
    print("  [PASS] sentences: 'Rs.', 'Pvt. Ltd.' and decimals do not end a sentence; a semicolon does")


def test_an_own_account_has_no_direction_but_still_has_a_party_and_a_date():
    assert A.Parties(R02).own == {"acct-02-a cash deposits", "acct-02-b cash deposits", "acct-02-c cash deposits"}
    assert silent("ACCT-02-B received a cash deposit of Rs.1,42,500 on 2026-08-19.", R02), "'received' is the natural way to say a deposit was made into the account"
    assert not silent("ACCT-02-B received Rs.1,35,000 on 2026-08-19.", R02), "1,35,000 is ACCT-02-C's deposit"
    assert not silent("ACCT-02-B received a cash deposit of Rs.1,42,500 on 2026-08-20.", R02), "wrong date"
    print("  [PASS] own accounts and deposit rows: no direction check (it false-flagged 'ACCT-02-B received a deposit' when first measured); party and date still apply")


def test_findings_are_soft_labelled_and_reach_the_officers_acknowledgement():
    text = "Rs.2.465L was received from UPI handle A. The credits came to Rs.3.45L."
    r = validate_narrative(text, R01, profile_text="Data entry operator; Rs.28K/month declared", alert_narrative="", context_dates=["2026-08-18"])
    assert r["passed"], "an attribution finding never blocks outright"
    att = [u for u in r["unverified_assertions"] if u["type"] == "attribution_mismatch"]
    assert len(att) == 1 and set(att[0]) == {"type", "text", "why"} and len(att[0]["text"]) <= 100 and len(att[0]["why"]) <= 400
    g = D.evaluate(disposition="FILE", rationale_text=text * 3, has_case_context=True, transaction_count=5, evidence_gate=r, gos_status="READY", ai_recommendation="FILE",
                   regulatory_basis=None, include_basis=False)
    cond = next(c for c in g["conditions"] if c["code"] == "UNVERIFIED_ASSERTIONS_IN_NARRATIVE")
    assert cond["severity"] == D.ACK_REQUIRED and cond["satisfied"] is False
    g2 = D.evaluate(disposition="FILE", rationale_text=text * 3, has_case_context=True, transaction_count=5, evidence_gate=r, gos_status="READY", ai_recommendation="FILE",
                    regulatory_basis=None, include_basis=False, unverified_claims_acknowledged=True)
    assert next(c for c in g2["conditions"] if c["code"] == "UNVERIFIED_ASSERTIONS_IN_NARRATIVE")["satisfied"] is True
    print("  [PASS] an attribution finding is UNVERIFIED (never a hard block): a filing needs the officer's acknowledgement, which is then recorded")


def test_hostile_record_and_narrative_text_never_break_the_check_or_escape_its_bounds():
    nasty = [{"txn_id": "T-1", "date": "2026-08-13", "type": "CREDIT", "amount_inr": 110000, "channel": "UPI", "counterparty": "A.*+?^$()[]{}|\\ ![x](http://attacker.example/p.png) Ltd"},
             {"txn_id": "T-2", "date": "2026-08-14", "type": "DEBIT", "amount_inr": 50000, "channel": "UPI", "counterparty": "'; DROP TABLE x; -- Pvt Ltd", "is_flagged": True}]
    for text in ("Rs.1.1L was received from 'A.*+?^$()[]{}|\\ ![x](http://attacker.example/p.png) Ltd'.", "Rs.50,000 was paid to '; DROP TABLE x; -- Pvt Ltd on 2026-08-01.", "x" * 50_000,
                 "Rs.1.1L was received from UPI handle A " * 2000):
        out = found(text, nasty)
        assert all(len(f["text"]) <= 100 and len(f["why"]) <= 400 for f in out)
    print("  [PASS] regex metacharacters, markdown and SQL in names and text: no exception, every finding bounded to 100 / 400 characters")


def test_the_check_is_deterministic_and_the_module_is_pure():
    a = found("Rs.2.465L was received from UPI handle A. All three credits came from UPI handle C.")
    b = found("Rs.2.465L was received from UPI handle A. All three credits came from UPI handle C.")
    assert a == b and len(a) == 2
    src = (ROOT / "skills/attribution.py").read_text()
    for banned in ("import snowflake", "cortex", "datetime.now", "requests", "os.environ", "open("):
        assert banned not in src, banned
    print("  [PASS] deterministic, and the module imports no database, model, network, clock or file access")


TESTS = [
    test_each_rule_catches_the_contradiction_and_explains_it_from_the_record, test_a_clause_with_an_amount_before_the_party_is_read_as_one_clause,
    test_named_senders_are_parties_even_when_the_record_calls_them_unknown, test_correctly_bound_statements_are_never_flagged,
    test_ambiguous_or_non_asserting_sentences_are_skipped_not_guessed_at, test_sentence_splitting_survives_abbreviations_and_decimals,
    test_an_own_account_has_no_direction_but_still_has_a_party_and_a_date, test_findings_are_soft_labelled_and_reach_the_officers_acknowledgement,
    test_hostile_record_and_narrative_text_never_break_the_check_or_escape_its_bounds, test_the_check_is_deterministic_and_the_module_is_pure,
]

if __name__ == "__main__":
    raise SystemExit(Runner("Attribution check (offline)").run(TESTS))
