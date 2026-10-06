"""
Evidence grounding (finding #5): deterministic validation of amounts, dates, counterparties,
channels, geographies, identifiers and customer-profile claims, plus ADVERSARIAL tests proving that
fabricated facts cannot yield READY — even when the model's own quality check says 10/10, and even
through the recorder.

Offline / deterministic. Usage:  python3 tests/test_grounding.py     (or pytest)
"""

from __future__ import annotations

import json

from _helpers import (Runner, case_context, checklist_json, factors_json, fixture, recorder_kwargs, skills)

CTX = case_context()
TX = CTX["transactions"]
PROFILE = CTX["customer_kyc"]
DATES = ["2026-08-19"]


def gate(narrative, **kw):
    return skills().validate_gos_evidence(narrative, kw.pop("transactions", TX), profile_text=kw.pop("profile", PROFILE),
                                          context_dates=kw.pop("dates", DATES), alert_narrative=kw.pop("alert", ""))


def blocked_types(narrative, **kw) -> set:
    r = gate(narrative, **kw)
    assert not r["passed"], f"fabricated narrative PASSED the gate: {narrative!r}"
    return set(r["unsupported_claims_by_type"])


# ── amounts ──────────────────────────────────────────────────────────────────

def test_amounts_every_notation_of_a_fabricated_figure_is_blocked():
    forms = ["₹25,00,000", "Rs. 25,00,000", "Rs.25,00,000", "INR 2500000", "INR 25,00,000", "₹25 lakh", "25 lakh",
             "₹25.0 lakhs", "Rs 25 lac", "₹2.5 crore", "2.5 Cr", "₹2500000", "Rs. 2,500,000", "₹25L"]
    for f in forms:
        assert "amount" in blocked_types(f"The customer transferred {f} to an unrelated party."), f
    print(f"  [PASS] fabricated ₹25L blocked in {len(forms)} notations (₹/Rs/INR, lakh/lac/crore/L/Cr) — old gate passed 4 of 5")


def test_amounts_legitimate_notations_and_derived_sums_pass():
    ok = ["₹3,45,000 from an unidentified individual", "₹3.45 lakh received", "Rs. 3,45,000 credited", "INR 345000 credited",
          "credits totalling ₹5,55,000", "a same-day debit of ₹5,47,000", "₹5.47 lakh transferred", "₹2,10,000 was credited"]
    for n in ok:
        r = gate(n)
        assert not r["unsupported_claims_by_type"].get("amount"), (n, r["unsupported_claims_by_type"])
    print(f"  [PASS] {len(ok)} legitimate notations / subset sums accepted (no over-blocking)")


def test_amounts_precision_tolerance_is_half_a_displayed_unit_not_one_percent():
    assert "amount" in blocked_types("A credit of ₹3,46,000 was received.")                 # exact digits ⇒ exact match
    assert "amount" in blocked_types("A credit of ₹3.6 lakh was received.", profile="")       # 3.55–3.65L ∌ 3.45L
    assert not gate("A credit of ₹3.5 lakh was received.")["unsupported_claims_by_type"].get("amount")   # rounds 3.45→3.5
    print("  [PASS] tolerance = half the last displayed unit (₹3,46,000 blocked; '₹3.5 lakh' as rounding accepted)")


def test_foreign_currency_amounts_are_unsupported_unless_in_record():
    assert "amount" in blocked_types("The customer received USD 30,000 from an overseas account.")
    print("  [PASS] foreign-currency figures not in the case record are blocked")


# ── dates ────────────────────────────────────────────────────────────────────

def test_dates_fabricated_or_reformatted_are_blocked_real_ones_pass():
    for d in ("2026-08-20", "20/08/2026", "20 August 2026", "August 20, 2026", "20th Aug 2026", "2026-02-30", "2026-13-45"):
        assert "date" in blocked_types(f"On {d} the customer moved the funds onward."), d
    for d in ("2026-08-12", "12/08/2026", "12 August 2026", "August 19, 2026", "19th Aug 2026", "2023-01-10"):
        assert not gate(f"On {d} the account was reviewed.")["unsupported_claims_by_type"].get("date"), d
    print("  [PASS] dates: in-window fabricated date blocked (old gate allowed +10 days); 6 formats parsed; profile/txn/suspicion dates accepted")


# ── txn ids / channels / geographies / identifiers / entities ───────────────

def test_txn_ids():
    assert "txn_id" in blocked_types("As shown by TXN-999 the funds moved.")
    assert "txn_id" in blocked_types("See T01-9 and T01B-7 for the onward hops.")
    assert not gate("Per TXN-001 and TXN-003 the funds moved.")["unsupported_claims_by_type"].get("txn_id")
    print("  [PASS] invented TXN IDs (TXN-999, T01-9, T01B-7) blocked; real IDs accepted")


def test_channels_must_exist_on_the_transactions():
    for ch in ("SWIFT wire", "RTGS transfer", "cash deposit", "IMPS", "NEFT"):
        assert "channel" in blocked_types(f"The funds moved via {ch} to the counterparty."), ch
    assert not gate("The credits arrived over UPI.")["unsupported_claims_by_type"].get("channel")
    r = skills().validate_gos_evidence("Funds moved via SWIFT.", [{k: v for k, v in t.items() if k != "channel"} for t in TX])
    assert any("channels" in x for x in r["verification_scope"]["not_checkable_now"]), "missing channel data is reported, not silently passed"
    print("  [PASS] channels not on any transaction blocked; missing channel data is reported as not checkable")


def test_geographies_and_identifiers_and_entities():
    for g in ("Dubai", "Singapore", "Hong Kong", "Cayman"):
        assert "geography" in blocked_types(f"An onward transfer went to a beneficiary in {g}."), g
    assert not gate("The NRI account received remittances from Singapore.", profile=PROFILE + " NRI resident in Singapore")["unsupported_claims_by_type"].get("geography")
    for ident in ("ramesh.kumar@okhdfcbank", "UPI-55XXXXXX12", "SBIN0001234", "ABCDE1234F", "9876543210", "123456789012"):
        assert "identifier" in blocked_types(f"Funds were sent to {ident} immediately."), ident
    assert not gate("Funds went to UPI-98XXXXXX76 immediately.")["unsupported_claims_by_type"].get("identifier")
    assert "entity" in blocked_types("The funds were paid to Meridian Global Traders Pvt Ltd on 2026-08-19.")
    assert "entity" in blocked_types("A transfer to First Gulf Bank followed.")
    ents = [dict(TX[0], counterparty="ABC Infrastructure Ltd")]
    assert not gate("Credits came from ABC Infrastructure Ltd.", transactions=ents)["unsupported_claims_by_type"].get("entity")
    print("  [PASS] jurisdictions, UPI/masked-UPI/IFSC/PAN/phone/account numbers, and named entities checked against the record")


# ── customer-profile claims ──────────────────────────────────────────────────

def test_profile_claims_are_checked_against_the_profile():
    assert "profile_income" in blocked_types("The customer's declared monthly income of ₹90,000 cannot explain the credits.")
    assert "profile_income" in blocked_types("Against a declared annual income of ₹12 lakh the credits are anomalous.")
    assert not gate("Against a declared annual income of ₹3.6 lakh the credits are anomalous.")["unsupported_claims_by_type"].get("profile_income")
    assert "profile_fact" in blocked_types("The account had been dormant for 18 months before the credits.")
    assert "profile_fact" in blocked_types("As a politically exposed person the customer's credits need scrutiny.")
    assert "profile_fact" in blocked_types("The customer's Aadhaar linkage is unconfirmed.")
    assert not gate("The account is dormant for 18 months.", profile=PROFILE + " Account dormant for 18 months.")["unsupported_claims_by_type"].get("profile_fact")
    print("  [PASS] fabricated income / dormancy / PEP / KYC-document claims blocked; profile-supported ones pass")


def test_no_transactions_means_the_gate_cannot_pass():
    r = skills().validate_gos_evidence("I formed suspicion after reviewing the account activity in detail.", [])
    assert r["passed"] is False and "evidence" in r["unsupported_claims_by_type"]
    print("  [PASS] no transaction evidence ⇒ gate fails (a failed/empty transaction load can no longer pass vacuously)")


# ── soft claims are LABELLED, never silently accepted ───────────────────────

def test_unverifiable_assertions_are_labelled_not_blocking_and_scope_is_explicit():
    r = gate(fixture("gos_good.txt") + " The beneficiary has known links to hawala operators and is FATF-listed.")
    assert r["passed"] is True, "interpretive assertions are labelled, not hard-blocked"
    kinds = {a["type"] for a in r["unverified_assertions"]}
    assert "third_party_characterisation" in kinds and len(r["unverified_assertions"]) >= 2
    scope = r["verification_scope"]
    assert scope["verified"] and any("interpretive" in x for x in scope["not_verified"]), "must state what was NOT verified"
    print(f"  [PASS] {len(r['unverified_assertions'])} unverifiable assertions labelled UNVERIFIED; result states what is NOT verified")


def test_unreproducible_percentages_and_multiples_are_labelled():
    r = gate("Some ₹5,55,000 arrived and 42% of it was forwarded; that is 90 times the monthly income.")
    types = [a["type"] for a in r["unverified_assertions"]]
    assert "percentage" in types and "multiple" in types, r["unverified_assertions"]
    ok = gate("₹5,47,000 (98.6% of the ₹5,55,000 received) left the account; the credits are 18.5 times monthly income.")
    assert not ok["unverified_assertions"], ok["unverified_assertions"]
    print("  [PASS] made-up percentages/multiples labelled UNVERIFIED; reproducible ones (98.6%, 18.5×) accepted")


def test_old_good_fixture_contained_unsupported_claims_the_old_gate_missed():
    r = gate(fixture("gos_unsupported_profile_claims.txt"))
    assert not r["passed"] and set(r["unsupported_claims_by_type"]) == {"profile_fact"}
    print("  [PASS] the previous 'good' fixture ('dormant for 18 months', 'Aadhaar unconfirmed') is now rejected as unsupported")


# ── ADVERSARIAL: fabricated facts can never yield READY ─────────────────────

FABRICATIONS = {
    "amount ₹":            "I formed suspicion on 2026-08-19 because ₹25,00,000 moved to an overseas beneficiary over UPI.",
    "amount Rs":           "I formed suspicion on 2026-08-19: Rs. 25,00,000 was sent by UPI to a new counterparty.",
    "amount INR":          "I formed suspicion on 2026-08-19: INR 2500000 left the account over UPI.",
    "amount lakh":         "I formed suspicion on 2026-08-19 after 25 lakh was moved over UPI to a third party.",
    "date":                "I formed suspicion on 2026-08-27 after the ₹5,47,000 debit to UPI-98XXXXXX76 over UPI.",
    "txn id":              "I formed suspicion on 2026-08-19 after TXN-777 moved ₹5,47,000 to UPI-98XXXXXX76 over UPI.",
    "channel":             "I formed suspicion on 2026-08-19 after ₹5,47,000 was wired by SWIFT to UPI-98XXXXXX76.",
    "geography":           "I formed suspicion on 2026-08-19 after ₹5,47,000 reached a beneficiary in Dubai via UPI.",
    "identifier":          "I formed suspicion on 2026-08-19: ₹5,47,000 went to fraudster@okaxis over UPI.",
    "entity":              "I formed suspicion on 2026-08-19: ₹5,47,000 went to Crescent Global Traders Pvt Ltd over UPI.",
    "profile income":      "I formed suspicion on 2026-08-19 as a declared monthly income of ₹1,20,000 cannot explain ₹5,55,000 of credits over UPI.",
    "profile dormancy":    "I formed suspicion on 2026-08-19: the account was dormant for 24 months before ₹5,55,000 of credits arrived over UPI.",
    "profile PEP":         "I formed suspicion on 2026-08-19: the politically exposed customer received ₹5,55,000 over UPI.",
    "fixture halluc.":     fixture("gos_hallucination.txt"),
}


def test_fabricated_facts_never_yield_ready_even_with_perfect_llm_quality_scores():
    """The model's own QC says 10/10 for every fabricated narrative; the deterministic gate must still stop READY."""
    for why, narrative in FABRICATIONS.items():
        narrative = narrative + " " + ("The pattern contrasts sharply with the declared profile. " * 4)
        res = skills(lambda p: checklist_json()).str_quality_checker(narrative, {**CTX, "context_dates": DATES})
        assert res["status"] != "READY" and res["hard_gate_passed"] is False, f"{why}: status={res['status']}"
        assert res["quality_score"] == 10, "sanity: the LLM did award 10/10"
        assert res["unsupported_claims_by_type"], why
    print(f"  [PASS] {len(FABRICATIONS)} fabrication classes: LLM says 10/10, status is still REJECT (hard gate false)")


def test_fabricated_facts_never_yield_ready_through_the_writer():
    assessment = skills(lambda p: factors_json(triggered=("POE-003", "POE-005", "POE-007"))).suspicion_evaluator(CTX)
    for why, narrative in FABRICATIONS.items():
        narrative = narrative + " " + ("Detail supporting the profile contrast. " * 8)
        model = lambda p, n=narrative: checklist_json() if "DRAFT GROUND OF SUSPICION" in p else n
        res = skills(model).ground_of_suspicion_writer({**CTX, "context_dates": DATES}, assessment)
        assert res["status"] == "REJECT" and res["hard_gate_passed"] is False, f"{why}: {res['status']}"
    print(f"  [PASS] writer: all {len(FABRICATIONS)} fabricated drafts come back REJECT, never READY")


def test_fabricated_facts_cannot_be_filed_through_the_recorder():
    from skills import CoPilotSkills
    from skills.ledger import LedgerBlocked
    from _helpers import FakeConn
    for why, narrative in FABRICATIONS.items():
        conn = FakeConn()
        try:
            CoPilotSkills(conn).alert_disposition_recorder(**recorder_kwargs(
                rationale_text=narrative + " " + "Supporting detail on the profile contrast. " * 4,
                override_reason="I know the AI said otherwise but I want to file anyway, please."))
            raise AssertionError(f"{why}: FILE was recorded!")
        except LedgerBlocked:
            pass
        assert conn.log == [], f"{why}: nothing may reach the database"
    print(f"  [PASS] recorder: FILE refused for all {len(FABRICATIONS)} fabrications — even WITH a written override (gate is not overridable)")


def test_ungrounded_factor_evidence_cannot_drive_a_file_recommendation():
    sk = skills()
    base = dict(triggered=("POE-003", "POE-005", "POE-007"))
    cases = {
        "invented txn id":      factors_json(**base, cite=("TXN-777",)),
        "no txn cited":         factors_json(**base, cite=()),
        "fabricated amount":    factors_json(**base, evidence="Received ₹25,00,000 from an overseas remitter."),
        "fabricated geography": factors_json(**base, evidence="Funds routed to a beneficiary in Dubai."),
        "fabricated date":      factors_json(**base, evidence="Burst of credits on 2026-08-27."),
    }
    for why, out in cases.items():
        a = skills(lambda p, out=out: out).suspicion_evaluator(CTX)
        summ = sk.evidence_sufficiency_summary(a)
        assert summ["recommendation"] != "FILE", f"{why}: {summ['recommendation']}"
        assert summ["ungrounded_triggered"], why
    honest = skills(lambda p: factors_json(**base, cite=("TXN-001", "TXN-003"))).suspicion_evaluator(CTX)
    assert sk.evidence_sufficiency_summary(honest)["recommendation"] == "FILE"
    invented = skills(lambda p: factors_json(**base, cite=("TXN-001", "TXN-777"))).suspicion_evaluator(CTX)
    assert all("TXN-777" not in f["evidence_txn_ids"] for f in invented), "invented IDs are stripped from provenance"
    print(f"  [PASS] {len(cases)} kinds of ungrounded factor evidence ⇒ never FILE; honest citations ⇒ FILE; invented IDs stripped")


def test_challenge_step_surfaces_ungrounded_factors_against_a_file_proposal():
    sk = skills()
    a = skills(lambda p: factors_json(triggered=("POE-003", "POE-005", "POE-007"), cite=("TXN-777",))).suspicion_evaluator(CTX)
    ch = sk.challenge_disposition("FILE", a, TX)
    assert any(c["type"] == "ungrounded_factor" for c in ch["counter_evidence"]), ch
    print("  [PASS] challenge_disposition flags ungrounded 'triggered' factors as counter-evidence to FILE")

# ── notations added after the fabrication benchmark (tests/fabrication_benchmark.py, evidence/fabrication-benchmark/) ──
AGED = "Data entry operator; Rs.28K/month declared; Low-risk; account 14 months old"
AGED_DATES = ["2026-08-18"]


def test_amounts_with_the_currency_after_the_figure_or_in_words_are_read():
    wrong = ["7,85,000 INR", "785000 rupees", "2.5 million rupees", "twenty-five lakh rupees", "five hundred thousand rupees",
             "Rupees Seven Lakh Eighty Five Thousand", "ten lakh"]
    for f in wrong:
        assert "amount" in blocked_types(f"The customer received {f} from an unrelated party."), f
    right = ["345000 rupees", "3,45,000 INR", "three lakh forty-five thousand rupees", "two lakh ten thousand rupees"]
    for f in right:
        assert not gate(f"The customer received {f}.")["unsupported_claims_by_type"].get("amount"), f
    for counts in ("Three UPI credits and four debits followed.", "About two hundred and fifty transactions were reviewed.", "Five thousand customers were screened."):
        assert not gate(counts)["unsupported_claims_by_type"].get("amount"), f"a count is not money: {counts}"
    print(f"  [PASS] amounts: {len(wrong)} wrong figures blocked in suffix and word notation; {len(right)} true ones pass; counts are not money")


def test_dates_in_every_common_format_including_no_year_are_checked():
    wrong = ["On 27.08.2026 funds moved.", "On 2026/08/27 funds moved.", "On 20260827 funds moved.", "On 27th August funds moved.", "On August 27 funds moved.",
             "On the twenty-seventh of August funds moved.", "On 31 February funds moved.", "On the thirty-first of April funds moved."]
    for t in wrong:
        assert "date" in blocked_types(t), t
    right = ["On 12.08.2026 a credit arrived.", "On 2026/08/19 funds left.", "On 20260812 a credit arrived.", "On 12th August a credit arrived.",
             "On August 19 funds left.", "On the nineteenth of August funds left.", "On the twelfth of August a credit arrived."]
    for t in right:
        assert not gate(t)["unsupported_claims_by_type"].get("date"), t
    assert not gate("The pattern may 5 times repeat.")["unsupported_claims_by_type"].get("date"), "lower-case 'may' is a verb"
    assert not gate("Account 123456789012345 was reviewed.")["unsupported_claims_by_type"].get("date"), "a long number is not a compact date"
    print(f"  [PASS] dates: {len(wrong)} wrong dates blocked (dotted, slash, compact, no-year, ordinal words, impossible days); {len(right)} true ones pass")


def test_channels_named_by_phrase_must_exist_on_the_record():
    for phrase in ("a wire transfer", "an international remittance", "a debit card payment", "internet banking", "a demand draft", "cash was handed over", "paid in cash"):
        assert "channel" in blocked_types(f"The customer used {phrase}."), phrase
    neft = [{**TX[0], "channel": "NEFT"}]
    assert not gate("The customer used a wire transfer.", transactions=neft)["unsupported_claims_by_type"].get("channel"), "NEFT supports 'wire transfer'"
    assert not gate("The customer used internet banking.", transactions=neft)["unsupported_claims_by_type"].get("channel")
    assert "channel" in blocked_types("The customer used internet banking.", transactions=[{**TX[0], "channel": "UPI"}])
    print("  [PASS] channels: wire / remittance / card / net banking / draft / cash phrases need a matching channel on the record; NEFT supports a wire")


def test_wider_geographies_entities_identifiers_and_income_phrasing():
    for g in ("the Maldives", "the Bahamas", "Jersey", "Kathmandu", "Karachi", "Shenzhen", "Johannesburg"):
        assert "geography" in blocked_types(f"The money reached {g}."), g
    for e in ("Acme Holdings", "Rao & Sons", "Sunrise Group", "Kalyan Jewellers Inc", "Patel Brothers", "ICICI"):
        assert "entity" in blocked_types(f"Funds went to {e}."), e
    for i in ("+91 98765 43210", "98765-43210", "a card ending 4321", "1234 5678 9012 3456"):
        assert "identifier" in blocked_types(f"The customer's contact was {i}."), i
    assert "profile_income" in blocked_types("The customer earns about Rs.50,000 a month.", profile=AGED, dates=AGED_DATES) or \
        "amount" in blocked_types("The customer earns about Rs.50,000 a month.", profile=AGED, dates=AGED_DATES)
    assert "profile_income" in blocked_types("The customer earns Rs.3,45,000 a month.", profile=AGED, dates=AGED_DATES), "a derivable amount is not a true income"
    assert not gate("The customer earns Rs.28,000 per month.", profile=AGED, dates=AGED_DATES)["unsupported_claims_by_type"].get("profile_income")
    print("  [PASS] wider lists and phrasings: foreign places and cities, Holdings/Group/Inc/& Sons/bank brands, formatted phones and card tails, 'earns'/'salary'")


def test_tenure_and_opening_year_are_checked_against_the_account_age():
    kw = dict(profile=AGED, dates=AGED_DATES)
    for t in ("The customer has been banking with us for ten years.", "The customer has been a client for five years.", "The account was opened in 2019.",
              "The account was opened in March 2021."):
        assert "profile_fact" in blocked_types(t, **kw), t
    for t in ("The customer has been banking with us for 14 months.", "The customer has been banking with us for fourteen months.",
              "The account was opened in 2025.", "The account was opened in June 2025."):
        assert not gate(t, **kw)["unsupported_claims_by_type"].get("profile_fact"), t
    unknown_age = gate("The account was opened in 2019.", profile="Salaried employee.", dates=AGED_DATES)
    assert unknown_age["passed"] and any(u["type"] == "account_opening" for u in unknown_age["unverified_assertions"]), "no account age to check → labelled UNVERIFIED, not blocked"
    print("  [PASS] profile facts: tenure and opening year contradict a 14-month-old account; true statements pass; with no age on file they are labelled UNVERIFIED")


def test_the_validator_says_it_does_not_check_attribution():
    scope = gate("Rs.2.465L was received from UPI handle A.")["verification_scope"]
    assert any("which party" in x and "which way the money moved" in x for x in scope["not_verified"]), scope["not_verified"]
    print("  [PASS] scope: the 'cannot verify' list names attribution (which party, which direction), measured at 0 of 9 in the benchmark")

def test_a_sentence_break_before_a_company_name_is_not_part_of_the_name():
    """'... on 15th July. DEF Engineering Pvt Ltd paid ...' was blocked as the entity 'July. DEF Engineering Pvt Ltd': the capitalised last word of the
    previous sentence was swallowed into the name. Found by running true narratives for another seeded alert (ALERT-04) through the validator."""
    txns = [{"txn_id": "T04-1", "date": "2026-07-15", "type": "CREDIT", "amount_inr": 1100000, "channel": "NEFT", "counterparty": "ABC Infrastructure Ltd"},
            {"txn_id": "T04-2", "date": "2026-08-15", "type": "CREDIT", "amount_inr": 930000, "channel": "NEFT", "counterparty": "DEF Engineering Pvt Ltd"}]
    kw = dict(transactions=txns, profile="State PWD engineer; Rs.95K/month declared", dates=["2026-08-20"])
    ok = gate("ABC Infrastructure Ltd credited Rs.11,00,000 on 15th July. DEF Engineering Pvt Ltd paid Rs.9,30,000 on 2026-08-15.", **kw)
    assert ok["passed"], ok["unsupported_claims_by_type"]
    bad = gate("ABC Infrastructure Ltd credited Rs.11,00,000 on 15th July. Sunrise Traders Pvt Ltd paid Rs.9,30,000 on 2026-08-15.", **kw)
    assert bad["unsupported_claims_by_type"]["entity"] == ["Sunrise Traders Pvt Ltd"], bad["unsupported_claims_by_type"]
    abbreviated = gate("Funds went to Sunrise Traders Pvt. Ltd. on 2026-08-15.", **kw)
    assert "entity" in abbreviated["unsupported_claims_by_type"], "'Pvt. Ltd.' is an abbreviation, not a sentence break"
    print("  [PASS] entities: a sentence ending before a company name does not become part of the name; 'Pvt. Ltd.' still reads as one name; a real stranger is still blocked")

def test_round_two_patterns_rupees_prefix_non_padded_iso_wired_and_cash_verbs():
    for t in ("A payment of rupees 6,50,000 followed.", "Rupees 25 lakh was moved.", "On 2026-9-12 a credit arrived.", "Funds were wired overseas.",
              "He wired the funds abroad.", "The customer withdrew cash from the branch counter.", "She deposited cash at the branch.", "Cash was withdrawn at the branch."):
        assert not gate(t)["passed"], f"fabrication passed: {t}"
    for t in ("A credit of rupees 3,45,000 was received.", "On 2026-8-12 a credit arrived."):
        assert gate(t)["passed"], (t, gate(t)["unsupported_claims_by_type"])
    for t in ("The hard-wired policy was followed.", "The account was wired into the system."):        # 'wired' as an adjective is not a wire transfer
        assert not gate(t)["unsupported_claims_by_type"].get("channel"), t
    cash = [{**TX[0], "channel": "CASH"}]
    assert not gate("The customer withdrew cash from the branch counter.", transactions=cash)["unsupported_claims_by_type"].get("channel"), "true when the record has cash"
    print("  [PASS] round 2: 'rupees 6,50,000', '2026-9-12', 'wired', 'withdrew/deposited cash' are read; true versions pass; 'hard-wired' is not a wire")

def test_the_draft_prompt_does_not_put_the_officers_voice_or_deliberation_in_the_models_mouth():
    from skills import core
    seen = []
    sk = skills(cortex_fn=lambda prompt: seen.append(prompt) or "The account received three UPI credits and two debits to a flagged handle. " * 6)
    assessment = json.loads(factors_json(triggered=("POE-003",)))
    sk.ground_of_suspicion_writer(case_context(), assessment)
    prompt = next(p for p in seen if "Ground of Suspicion (Part c)" in p)
    assert "Do NOT write in the first person" in prompt and "neutral, factual voice" in prompt
    for gone in ("Write as the Principal Officer in first person", "I formed suspicion because", "considered and rejected"):
        assert gone not in prompt, gone
    assert "Do NOT say that anyone considered, weighed or rejected an explanation" in prompt
    assert core.PROMPT_VERSION == "v2.2", "the ledger records which prompt wrote the draft"
    print("  [PASS] draft prompt: neutral voice, no first person, no claim that anyone considered or rejected anything; prompt version v2.2 is what the ledger records")


TESTS = [
    test_amounts_every_notation_of_a_fabricated_figure_is_blocked, test_amounts_legitimate_notations_and_derived_sums_pass,
    test_amounts_precision_tolerance_is_half_a_displayed_unit_not_one_percent,
    test_foreign_currency_amounts_are_unsupported_unless_in_record, test_dates_fabricated_or_reformatted_are_blocked_real_ones_pass,
    test_txn_ids, test_channels_must_exist_on_the_transactions, test_geographies_and_identifiers_and_entities,
    test_profile_claims_are_checked_against_the_profile, test_no_transactions_means_the_gate_cannot_pass,
    test_unverifiable_assertions_are_labelled_not_blocking_and_scope_is_explicit,
    test_unreproducible_percentages_and_multiples_are_labelled,
    test_old_good_fixture_contained_unsupported_claims_the_old_gate_missed,
    test_fabricated_facts_never_yield_ready_even_with_perfect_llm_quality_scores,
    test_fabricated_facts_never_yield_ready_through_the_writer,
    test_fabricated_facts_cannot_be_filed_through_the_recorder,
    test_ungrounded_factor_evidence_cannot_drive_a_file_recommendation,
    test_challenge_step_surfaces_ungrounded_factors_against_a_file_proposal,
    test_amounts_with_the_currency_after_the_figure_or_in_words_are_read, test_dates_in_every_common_format_including_no_year_are_checked,
    test_channels_named_by_phrase_must_exist_on_the_record, test_wider_geographies_entities_identifiers_and_income_phrasing,
    test_tenure_and_opening_year_are_checked_against_the_account_age, test_the_validator_says_it_does_not_check_attribution,
    test_a_sentence_break_before_a_company_name_is_not_part_of_the_name, test_round_two_patterns_rupees_prefix_non_padded_iso_wired_and_cash_verbs,
    test_the_draft_prompt_does_not_put_the_officers_voice_or_deliberation_in_the_models_mouth,
]

if __name__ == "__main__":
    raise SystemExit(Runner("Evidence-grounding + adversarial tests (no Snowflake required)").run(TESTS))
