"""
Case prioritisation — the explainable workload-ordering score (skills/prioritisation.py).

Pins the policy tables, the explanation, the "deadline only from a recorded suspicion time" rule, and — most importantly — that
priority and the FILE / NOT_FILE decision stay separate in BOTH directions (neither module imports the other, nor feedback).

Offline. Usage:  python3 tests/test_prioritisation.py     (or pytest)
"""

from __future__ import annotations

import re
import sys
from datetime import date

from _helpers import ROOT, Runner

sys.path.insert(0, str(ROOT / "scripts"))
import setup_alerts as seed  # noqa: E402

from skills import evidence_quality as Q  # noqa: E402
from skills import prioritisation as P  # noqa: E402
from skills.evidence import signal_brief  # noqa: E402

NOW = date(2026, 10, 3)


def case(aid):
    a = next(x for x in seed.ALERTS if x["ALERT_ID"] == aid)
    tx = [{"txn_id": t["TXN_ID"], "date": t["TXN_DATE"], "type": t["TXN_TYPE"], "amount_inr": t["AMOUNT_INR"], "channel": t["CHANNEL"],
           "counterparty": t["COUNTERPARTY"], "is_flagged": t["IS_FLAGGED"]} for t in seed.TRANSACTIONS if t["ALERT_ID"] == aid]
    return a, tx


def score(aid, sla=None, **over):
    a, tx = case(aid)
    a = {**a, **over}
    return P.prioritise(a, signal_brief(tx) if tx else None, Q.assess(a, tx, now=NOW), sla_days_remaining=sla, now=NOW)


def points(res):
    return {f["id"]: f["points"] for f in res["factors"]}


# ── structure ────────────────────────────────────────────────────────────────

def test_the_nine_factors_have_fixed_weights_that_sum_to_100_and_never_exceed_them():
    assert sum(P.WEIGHTS.values()) == 100 and len(P.WEIGHTS) == 9
    wanted = {"severity", "amount", "flagged_counterparties", "suspicious_flow", "pass_through", "deadline", "case_age", "evidence_sufficiency", "missing_data"}
    assert set(P.WEIGHTS) == wanted, "signal severity, amount, flagged counterparties, suspicious flow, deadline, age, sufficiency, missing-data risk (+ pass-through)"
    for a in seed.ALERTS:
        for sla in (None, -3, 0, 2, 9):
            r = score(a["ALERT_ID"], sla)
            assert [f["id"] for f in r["factors"]] == list(P.WEIGHTS) and all(0 <= f["points"] <= f["max_points"] == P.WEIGHTS[f["id"]] for f in r["factors"])
            assert r["score"] == sum(f["points"] for f in r["factors"]) and 0 <= r["score"] <= 100
            assert r["band"] == P.band_for(r["score"]) and r["policy_version"] == P.POLICY_VERSION
    print("  [PASS] 9 factors, weights fixed (sum 100), every factor within its maximum for all 19 alerts × 5 deadline states; the score is the sum of the factors")


def test_every_factor_explains_itself_and_the_explanation_is_assembled_from_them():
    r = score("ALERT-01")
    assert all(f["detail"] and isinstance(f["inputs"], dict) for f in r["factors"])
    assert r["explanation"].startswith(f"Priority {r['score']}/100 ({r['band']}). Main drivers:")
    assert len(r["drivers"]) == 3 and [d["points"] for d in r["drivers"]] == sorted((d["points"] for d in r["drivers"]), reverse=True)
    for d in r["drivers"]:
        assert d["detail"].rstrip(".") in r["explanation"] and f"(+{d['points']})" in r["explanation"]
    assert "98.8%" in r["explanation"] and "flagged" in r["explanation"].lower()
    assert P.DISCLAIMER in r["disclaimer"] and "not a risk rating" in r["disclaimer"] and "not a recommendation to file" in r["disclaimer"]
    print(f"  [PASS] each factor carries its inputs and a sentence; the 'why' text is built from the top drivers: “{r['explanation'][:96]}…”")


# ── each factor, pinned ──────────────────────────────────────────────────────

def test_severity_comes_from_a_policy_table_and_is_labelled_as_such():
    assert points(score("ALERT-01"))["severity"] == P.SOURCE_POINTS["I4C"] + P.TYPE_POINTS[1] == 15
    assert points(score("ALERT-07"))["severity"] == P.SOURCE_POINTS["INTERNAL_RULE"] + P.TYPE_POINTS[3] == 5
    r = score("ALERT-01", SIGNAL_SOURCE="SOMETHING_NEW", ALERT_TYPE="BRAND_NEW_RULE")
    assert points(r)["severity"] == P.SOURCE_UNKNOWN_POINTS + P.TYPE_POINTS[3]
    note = next(f for f in r["factors"] if f["id"] == "severity")["note"]
    assert "not a regulatory ranking" in note
    print("  [PASS] severity = source points + type-tier points from the policy table; an unknown source / type scores low, not high; the table is labelled 'not a regulatory ranking'")


def test_amount_flagged_counterparties_and_flow_follow_their_bands():
    expect = {99_999: 2, 100_000: 5, 500_000: 8, 2_500_000: 11, 10_000_000: 14}
    for amount, pts in expect.items():
        assert points(score("ALERT-01", ALERT_AMOUNT_INR=amount))["amount"] == pts, amount
    r = score("ALERT-01")
    assert points(r)["flagged_counterparties"] == P.FLAGGED_COUNT_POINTS[1] and points(r)["suspicious_flow"] == 14 and points(r)["pass_through"] == 6
    r16 = score("ALERT-16")
    assert points(r16)["flagged_counterparties"] == 0 and points(r16)["suspicious_flow"] == 0 and points(r16)["pass_through"] == 4
    no_credit = P.prioritise(case("ALERT-01")[0], {"txn_count": 1, "total_credit": 0, "total_debit": 5, "flagged_counterparties": [], "flagged_debit_share_pct": None,
                                                   "onward_ratio_pct": None}, None, now=NOW)
    assert points(no_credit)["suspicious_flow"] == 0 and any("credit" in g for g in no_credit["data_gaps"])
    print("  [PASS] amount bands (₹1L · 5L · 25L · 1Cr), flagged-counterparty count, flagged share of credits (98.8 % → 14) and pass-through ratio follow the tables")


def test_no_transactions_means_zero_for_flow_factors_and_a_stated_gap_never_an_invented_number():
    a = case("ALERT-01")[0]
    r = P.prioritise(a, None, Q.assess(a, [], now=NOW), now=NOW)
    assert points(r)["flagged_counterparties"] == points(r)["suspicious_flow"] == points(r)["pass_through"] == 0
    assert any("No transaction record" in g for g in r["data_gaps"])
    r2 = P.prioritise({}, None, None, now=NOW)
    assert r2["score"] == points(r2)["severity"] and any("Evidence quality was not assessed" in g for g in r2["data_gaps"]) and any("alert amount" in g for g in r2["data_gaps"])
    print("  [PASS] absent inputs score 0 with a named data gap (no transactions, no alert amount, quality not assessed) — nothing is guessed")


def test_the_deadline_is_scored_only_from_a_recorded_suspicion_time():
    none = score("ALERT-01", None)
    dl = next(f for f in none["factors"] if f["id"] == "deadline")
    assert dl["points"] == 0 and "No suspicion time is recorded" in dl["detail"] and any("not scored" in g for g in none["data_gaps"])
    got = {sla: points(score("ALERT-01", sla))["deadline"] for sla in (-2, 0, 1, 3, 5, 7)}
    assert got == {-2: 15, 0: 15, 1: 13, 3: 10, 5: 6, 7: 3}, got
    assert score("ALERT-01", -2)["score"] > score("ALERT-01", 7)["score"] > score("ALERT-01", None)["score"], "a closer recorded deadline ranks higher; an unrecorded one adds nothing"
    print("  [PASS] no recorded suspicion time → deadline 0 with 'not scored'; overdue 15 · 0–1 WD 15/13 · ≤3 10 · ≤5 6 · more 3 — an unrecorded deadline is never presented as on time or overdue")


def test_case_age_sufficiency_and_missing_data_enter_with_their_own_sentences():
    assert [points(score("ALERT-01", ALERT_DATE=d))["case_age"] for d in ("2026-10-02", "2026-09-26", "2026-09-19", "2026-09-12", "2026-09-02", "2026-08-18")] == [0, 2, 4, 5, 7, 8]
    ok, thin = score("ALERT-16"), score("ALERT-06")
    assert points(ok)["evidence_sufficiency"] > points(thin)["evidence_sufficiency"]
    assert points(thin)["missing_data"] > points(ok)["missing_data"] == 0
    cap = P.prioritise(case("ALERT-06")[0], None, {"evaluated": True, "sufficiency_pct": 10, "counts": {Q.BLOCKS_FILING: 5, Q.REQUIRES_MANUAL_REVIEW: 5}}, now=NOW)
    assert points(cap)["missing_data"] == P.WEIGHTS["missing_data"]
    print("  [PASS] case age bands (calendar days, reference only); sufficiency adds more for a decision-ready record; missing-data risk adds for gating issues and is capped at its weight")


# ── what the score is for, and what it is not ────────────────────────────────

def test_equal_signal_different_priority_and_priority_is_not_the_decision():
    """The demo pair fired the same detector for the same amount; the record differs, so the priority differs. Neither is a decision."""
    a01, a16 = score("ALERT-01"), score("ALERT-16")
    assert a01["score"] > a16["score"] and points(a01)["severity"] == points(a16)["severity"]
    assert a01["band"] in ("High", "Critical") and a16["band"] in ("Medium", "Low")
    for word in ("FILE", "NOT_FILE", "close", "file an STR", "should file"):
        assert word.lower() not in a01["explanation"].lower().replace("flagged", ""), f"the explanation must not recommend a decision: {word!r}"
    print("  [PASS] ALERT-01 (High) outranks its look-alike ALERT-16 (Medium) on the evidence; the explanation never recommends filing or closing")


def test_priority_and_the_decision_gate_do_not_read_each_other_or_feedback():
    """Separation, enforced by reading the code: the gate takes no priority input; priority takes no gate or ledger-feedback input."""
    src = lambda n: open(ROOT / f"skills/{n}.py").read()
    for banned in ("defensibility", "feedback", "ledger", "core", "review_monitor", "human_review", "audit"):
        assert not re.search(rf"^\s*(?:from|import)\s+skills(?:\.{banned}\b|\s+import\s+[^\n]*\b{banned}\b)", src("prioritisation"), re.M), f"prioritisation must not import {banned}"
    for banned in ("prioritisation",):
        for mod in ("defensibility", "ledger", "core", "governance", "grounding"):
            assert banned not in src(mod), f"{mod} must not read the priority score"
    assert not re.search(r"^\s*(?:from|import)\s+skills(?:\.feedback\b|\s+import\s+[^\n]*\bfeedback\b)", src("evidence_quality"), re.M)
    print("  [PASS] prioritisation imports no gate / ledger / feedback / review module; the gate, ledger, core, governance and grounding never read the priority score")


def test_the_ordering_is_stable_and_explainable_with_ties_broken_by_date_amount_then_id():
    items = [{"alert": {"ALERT_ID": "B", "ALERT_DATE": "2026-09-01", "ALERT_AMOUNT_INR": 10}, "priority": {"score": 50}},
             {"alert": {"ALERT_ID": "A", "ALERT_DATE": "2026-09-01", "ALERT_AMOUNT_INR": 10}, "priority": {"score": 50}},
             {"alert": {"ALERT_ID": "C", "ALERT_DATE": "2026-08-01", "ALERT_AMOUNT_INR": 5}, "priority": {"score": 50}},
             {"alert": {"ALERT_ID": "D", "ALERT_DATE": "2026-09-01", "ALERT_AMOUNT_INR": 99}, "priority": {"score": 50}},
             {"alert": {"ALERT_ID": "Z", "ALERT_DATE": "2026-09-09", "ALERT_AMOUNT_INR": 1}, "priority": {"score": 80}}]
    assert [i["alert"]["ALERT_ID"] for i in sorted(items, key=P.sort_key)] == ["Z", "C", "D", "A", "B"]
    first = [i for i in sorted([{"alert": a, "priority": score(a["ALERT_ID"])} for a in seed.ALERTS], key=P.sort_key)]
    assert [i["alert"]["ALERT_ID"] for i in first][0] == "ALERT-01"
    assert [i["alert"]["ALERT_ID"] for i in first] == [i["alert"]["ALERT_ID"] for i in sorted(reversed(first), key=P.sort_key)], "input order never changes the result"
    print("  [PASS] ordering: score ↓, then earlier alert date, larger amount, alert id; ALERT-01 leads the seeded queue; shuffling the input changes nothing")


def test_hostile_alert_fields_cannot_reach_the_score_text_as_anything_but_text():
    hostile = "![x](https://attacker.example/p.png) [c](https://attacker.example/x)"
    a = {**case("ALERT-01")[0], "SIGNAL_SOURCE": hostile, "ALERT_TYPE": hostile}
    r = P.prioritise(a, None, None, now=NOW)
    assert isinstance(r["score"], int) and r["factors"][0]["points"] == P.SOURCE_UNKNOWN_POINTS + P.TYPE_POINTS[3]
    print("  [PASS] a hostile source / type scores as 'unknown' (low) and is only ever returned as text for the UI to escape")


TESTS = [
    test_the_nine_factors_have_fixed_weights_that_sum_to_100_and_never_exceed_them, test_every_factor_explains_itself_and_the_explanation_is_assembled_from_them,
    test_severity_comes_from_a_policy_table_and_is_labelled_as_such, test_amount_flagged_counterparties_and_flow_follow_their_bands,
    test_no_transactions_means_zero_for_flow_factors_and_a_stated_gap_never_an_invented_number, test_the_deadline_is_scored_only_from_a_recorded_suspicion_time,
    test_case_age_sufficiency_and_missing_data_enter_with_their_own_sentences, test_equal_signal_different_priority_and_priority_is_not_the_decision,
    test_priority_and_the_decision_gate_do_not_read_each_other_or_feedback, test_the_ordering_is_stable_and_explainable_with_ties_broken_by_date_amount_then_id,
    test_hostile_alert_fields_cannot_reach_the_score_text_as_anything_but_text,
]

if __name__ == "__main__":
    raise SystemExit(Runner("Case prioritisation (offline)").run(TESTS))
