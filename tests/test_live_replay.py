"""
Deterministic replay of REAL Cortex output (captured live 2026-09-30, llama3.3-70b, AWS_AP_SOUTHEAST_7).

tests/fixtures/live_assessments.json holds the raw model responses for the judge-demo pair. Replaying
them offline pins the behaviour that matters without an LLM:

  ALERT-01  → FILE      (flagged-beneficiary factor triggered and grounded)
  ALERT-16  → REVIEW    the legitimate twin. Three volume factors (income level / frequency / size) are
                        genuinely triggered, but source-of-income and beneficiary are CLEAR. The original
                        rule ("≥3 triggered factors → FILE") recommended FILE for it — caught by the first
                        live end-to-end run. NEXUS_FACTORS policy fixes it.

Usage:  python3 tests/test_live_replay.py     (or pytest)
"""

from __future__ import annotations

import json
import sys

from _helpers import ROOT, Runner, skills

sys.path.insert(0, str(ROOT / "scripts"))
import setup_alerts as seed  # noqa: E402

LIVE = json.loads((ROOT / "tests/fixtures/live_assessments.json").read_text())


def _case(alert_id: str) -> dict:
    alert = next(a for a in seed.ALERTS if a["ALERT_ID"] == alert_id)
    txns = [{"txn_id": t["TXN_ID"], "date": t["TXN_DATE"], "type": t["TXN_TYPE"], "amount_inr": float(t["AMOUNT_INR"]),
             "channel": t["CHANNEL"], "counterparty": t["COUNTERPARTY"], "is_flagged": bool(t["IS_FLAGGED"])}
            for t in seed.TRANSACTIONS if t["ALERT_ID"] == alert_id]
    return skills().case_context_for(alert, txns)


def _assess(alert_id: str):
    return skills(lambda p: LIVE[alert_id]["raw_response"]).suspicion_evaluator(_case(alert_id))


def test_real_model_output_passes_strict_validation_and_grounding():
    for aid in ("ALERT-01", "ALERT-16"):
        a = _assess(aid)
        assert skills().assessment_validity(a)["valid"], (aid, skills().assessment_validity(a))
        ungrounded = [f["factor_id"] for f in a if f["assessment"] == "triggered" and not f["grounded"]]
        assert not ungrounded, f"{aid}: real model output should be grounded, ungrounded: {ungrounded}"
        assert all(t in {x["txn_id"] for x in _case(aid)["transactions"]} for f in a for t in f["evidence_txn_ids"])
    print("  [PASS] real llama3.3-70b output for both demo alerts: strictly valid, every triggered factor grounded in the record")


def test_alert_01_is_recommended_file():
    a = _assess("ALERT-01")
    s = skills().evidence_sufficiency_summary(a)
    assert s["recommendation"] == "FILE", s
    assert s["grounded_nexus_factors"], "FILE must rest on a source/beneficiary/complexity/geography factor"
    print(f"  [PASS] ALERT-01 → FILE (nexus factors: {s['grounded_nexus_factors']})")


def test_alert_16_twin_is_not_recommended_file_but_reviewed():
    a = _assess("ALERT-16")
    s = skills().evidence_sufficiency_summary(a)
    grounded = [f for f in a if f["assessment"] == "triggered" and f["grounded"]]
    assert len(grounded) >= 3, "sanity: the OLD 'count ≥3' rule would have said FILE for the legitimate twin"
    assert not s["grounded_nexus_factors"]
    assert s["recommendation"] == "REVIEW" and "product policy" in s["basis_note"], s
    clear = {f["factor_id"] for f in a if f["assessment"] == "clear"}
    assert {"POE-006", "POE-007"} <= clear, "the model itself found the source of funds and the beneficiary clear"
    print(f"  [PASS] ALERT-16 → REVIEW: {len(grounded)} volume factors triggered, but POE-006/POE-007 clear (old rule said FILE)")


def test_challenge_step_shows_deterministic_counter_evidence_for_the_twin():
    a = _assess("ALERT-16")
    txns = _case("ALERT-16")["transactions"]
    to_file = skills().challenge_disposition("FILE", a, txns)
    kinds = {c["type"] for c in to_file["counter_evidence"]}
    assert {"no_flagged_counterparty", "documented_sources"} <= kinds, kinds
    to_close = skills().challenge_disposition("NOT_FILE", a, txns)
    assert any(c["type"] == "triggered_factor" for c in to_close["counter_evidence"]), "closing is challenged by the volume factors"
    t01 = _case("ALERT-01")["transactions"]
    a01 = skills().challenge_disposition("FILE", _assess("ALERT-01"), t01)
    assert "no_flagged_counterparty" not in {c["type"] for c in a01["counter_evidence"]}, "ALERT-01 has flagged counterparties"
    print("  [PASS] challenge step: FILE on ALERT-16 is challenged by 'no flagged counterparty' + 'documented sources'; CLOSE by volume factors")


TESTS = [test_real_model_output_passes_strict_validation_and_grounding, test_alert_01_is_recommended_file,
         test_alert_16_twin_is_not_recommended_file_but_reviewed, test_challenge_step_shows_deterministic_counter_evidence_for_the_twin]

if __name__ == "__main__":
    raise SystemExit(Runner("Replay of captured live Cortex output (no network)").run(TESTS))
