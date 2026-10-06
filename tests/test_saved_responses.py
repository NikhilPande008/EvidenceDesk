"""
Saved model responses: a real Cortex reply captured earlier, replayed only when the request is byte-identical, only when the officer asks,
re-checked against today's record, and flagged in the ledger.

What these tests pin (offline; no model, no Snowflake):
  * a saved reply matches ONE exact prompt; one changed character, or one changed transaction, matches nothing;
  * replay is equivalent to a live call that returns the same text: same parsing, same grounding, same findings;
  * a saved reply that cites a transaction the record does not hold is flagged ungrounded, exactly as a live one would be;
  * nothing is sent to a model during replay, and a miss fails instead of falling back silently to a live call;
  * the draft is offered only when BOTH of its model calls (draft and quality check) are saved;
  * the ledger row carries `ai_output` only when a saved reply was used, and the row hash covers it;
  * the screen offers the saved option beside, never instead of, the live one, and says what it loaded.

Usage:  python3 tests/test_saved_responses.py     (or pytest)
"""

from __future__ import annotations

import contextlib
import json
import re
import sys

from _helpers import FakeConn, ROOT, Runner, factors_json, recorder_kwargs, skills
from skills import CoPilotSkills  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
import setup_alerts as seed  # noqa: E402

from skills import po_copy as T  # noqa: E402
from skills import saved_responses as saved  # noqa: E402
from skills import saved_responses_data as DATA  # noqa: E402

LIVE = json.loads((ROOT / "tests/fixtures/live_assessments.json").read_text())
RAW = LIVE["ALERT-01"]["raw_response"]
WHEN = "2026-10-05T10:00:00+00:00"


def _case(alert_id="ALERT-01", drop_last_txn=False) -> dict:
    alert = next(a for a in seed.ALERTS if a["ALERT_ID"] == alert_id)
    txns = [{"txn_id": t["TXN_ID"], "date": t["TXN_DATE"], "type": t["TXN_TYPE"], "amount_inr": float(t["AMOUNT_INR"]),
             "channel": t["CHANNEL"], "counterparty": t["COUNTERPARTY"], "is_flagged": bool(t["IS_FLAGGED"])}
            for t in seed.TRANSACTIONS if t["ALERT_ID"] == alert_id]
    return skills().case_context_for(alert, txns[:-1] if drop_last_txn else txns)


def _entry(raw: str, model="llama3.3-70b") -> dict:
    return {"model": model, "captured_at": WHEN, "raw_response": raw}


@contextlib.contextmanager
def _table(entries: dict):
    """Install a saved-response table for the duration of a block."""
    before = dict(DATA.SAVED)
    DATA.SAVED.clear()
    DATA.SAVED.update(entries)
    try:
        yield
    finally:
        DATA.SAVED.clear()
        DATA.SAVED.update(before)


def _assessment_table(ctx, raw=RAW) -> dict:
    return {saved.prompt_key(skills()._assessment_prompt(ctx)): _entry(raw)}


def test_a_saved_reply_matches_one_exact_prompt_and_nothing_else():
    ctx = _case()
    prompt = skills()._assessment_prompt(ctx)
    table = {saved.prompt_key(prompt): _entry(RAW)}
    assert saved.lookup(prompt, table)["model"] == "llama3.3-70b"
    assert saved.lookup(prompt + " ", table) is None and saved.lookup(prompt.replace("Rs.", "INR", 1), table) is None, "one changed character matches nothing"
    for bad in ({"model": "", "captured_at": WHEN, "raw_response": RAW}, {"model": "m", "captured_at": "", "raw_response": RAW},
                {"model": "m", "captured_at": WHEN, "raw_response": "   "}, {"model": "m", "captured_at": WHEN}, "not a dict"):
        assert saved.lookup(prompt, {saved.prompt_key(prompt): bad}) is None, bad
    assert not DATA.SAVED or all(isinstance(v, dict) for v in DATA.SAVED.values())
    print("  [PASS] a saved reply is found only by the exact prompt text; a changed character or an entry without model, time or reply matches nothing")


def test_replay_is_equivalent_to_a_live_call_that_returns_the_same_text_and_sends_nothing():
    ctx = _case()
    calls: list[str] = []
    sk = skills(lambda p: calls.append(p) or "SHOULD NEVER BE USED")
    with _table(_assessment_table(ctx)), sk.replaying():
        replayed = sk.suspicion_evaluator(ctx)
    assert calls == [], "replay must not call the model"
    assert (sk.output_source, sk.output_captured_at, sk.last_model_used) == (saved.SOURCE_SAVED, WHEN, "llama3.3-70b")
    live = skills(lambda p: RAW).suspicion_evaluator(ctx)
    assert replayed == live, "same parsing, same grounding, same findings as a live call returning this text"
    assert skills().assessment_validity(replayed)["valid"] and any(f["assessment"] == "triggered" and f["grounded"] for f in replayed)
    print("  [PASS] replay == a live call returning the same text (valid, grounded factors identical) and the model is never called")


def test_a_miss_fails_instead_of_quietly_calling_the_model_and_a_changed_record_is_a_miss():
    ctx = _case()
    calls: list[str] = []
    sk = skills(lambda p: calls.append(p) or RAW)
    with _table(_assessment_table(ctx)):
        assert sk.saved_assessment_available(ctx) and sk.saved_assessment_available(ctx)["captured_at"] == WHEN
        changed = _case(drop_last_txn=True)
        assert sk.saved_assessment_available(changed) is None, "one transaction fewer is a different prompt"
        try:
            with sk.replaying():
                sk.suspicion_evaluator(changed)
        except saved.SavedResponseUnavailable as err:
            assert "Nothing was sent to a model" in str(err)
        else:
            raise AssertionError("a miss must raise, not fall back to a live call")
    assert calls == [], "no fallback to the model"
    with _table({}):
        assert sk.saved_assessment_available(ctx) is None
    print("  [PASS] a changed record is a different prompt: no saved reply is offered, replay raises SavedResponseUnavailable, and the model is not called")


def test_outside_replay_the_call_is_live_and_says_so():
    ctx = _case()
    sk = skills(lambda p: RAW)
    with _table(_assessment_table(ctx)):
        with sk.replaying():
            sk.suspicion_evaluator(ctx)
        assert sk.output_source == saved.SOURCE_SAVED
        sk.suspicion_evaluator(ctx)                                    # after the block: a live (injected) call, even though a saved reply exists
    assert sk.output_source == saved.SOURCE_LIVE and sk.output_captured_at is None and sk.last_model_used == "injected-test-fn"
    print("  [PASS] the saved reply is used only inside replaying(); the next call is live and the source flips back")


def test_a_saved_reply_that_cites_a_transaction_the_record_does_not_hold_is_flagged_like_a_live_one():
    ctx = _case()
    forged = re.sub(r'"T01-\d+"', '"T99-9"', RAW)
    assert forged != RAW
    sk = skills()
    with _table(_assessment_table(ctx, forged)), sk.replaying():
        replayed = sk.suspicion_evaluator(ctx)
    live = skills(lambda p: forged).suspicion_evaluator(ctx)
    assert replayed == live
    assert any(f["assessment"] == "triggered" and f["grounded"] is False for f in replayed), "the grounding check still runs on saved text"
    print("  [PASS] a saved reply citing transactions the record lacks is marked ungrounded, exactly as a live reply would be")


def _draft_tables(ctx, assessment, with_check=True):
    sk = skills()
    narrative = ("The account received credits from several UPI handles within five days and the amounts were then transferred out, which does not fit the "
                 "declared occupation. The record does not explain the source of these funds.")
    checks = json.dumps([{"item_number": i, "item": "x", "applies": False, "note": "specific"} for i in range(1, 11)])
    table = {saved.prompt_key(sk._gos_prompt(ctx, assessment)): _entry(narrative)}
    if with_check:
        table[saved.prompt_key(sk._checker_prompt(narrative, ctx))] = _entry(checks)
    return table


def test_the_draft_is_offered_only_when_both_of_its_calls_are_saved():
    ctx = _case()
    assessment = skills(lambda p: RAW).suspicion_evaluator(ctx)
    sk = skills(lambda p: "unused")
    with _table(_draft_tables(ctx, assessment, with_check=False)):
        assert sk.saved_draft_available(ctx, assessment) is None, "a draft whose quality check is not saved would half-run"
    with _table(_draft_tables(ctx, assessment)):
        assert sk.saved_draft_available(ctx, assessment)["model"] == "llama3.3-70b"
        with sk.replaying():
            gos = sk.ground_of_suspicion_writer(ctx, assessment)
    assert gos["output_source"] == saved.SOURCE_SAVED and gos["output_captured_at"] == WHEN and gos["model_used"] == "llama3.3-70b"
    assert gos["narrative"].startswith("The account received credits") and gos["quality_score"] == 10
    live = skills(lambda p: "x").ground_of_suspicion_writer(ctx, assessment)
    assert live["output_source"] == saved.SOURCE_LIVE and live["output_captured_at"] is None
    print("  [PASS] the saved draft needs the draft AND its quality check; it is read back with its source and capture time, a live draft says 'live'")


def test_the_ledger_row_carries_ai_output_only_for_a_saved_reply_and_the_hash_covers_it():
    from skills.ledger import build_provenance
    assert saved.provenance("live", WHEN, "m") is None and saved.provenance(None, None) is None
    assert saved.provenance(saved.SOURCE_SAVED, WHEN, "llama3.3-70b", ["draft", "assessment", "draft"]) == {
        "source": "saved_response", "captured_at": WHEN, "model": "llama3.3-70b", "parts": ["assessment", "draft"]}
    base = dict(disposition="FILE", ai_recommendation="FILE", override_reason=None, corpus_version="1.1.1", regulatory_basis={}, model_name="m", prompt_version="v", skill_version="s",
                evidence_txn_ids=[], transactions=[], poe_assessment=[], gos_narrative="n", gos_quality=None, unverified_claims_acknowledged=None)
    assert "ai_output" not in build_provenance(**base), "a live decision has no such key"
    assert build_provenance(**base, ai_output=saved.provenance(saved.SOURCE_SAVED, WHEN, "m", ["assessment"]))["ai_output"]["parts"] == ["assessment"]

    live_conn, saved_conn = FakeConn(), FakeConn()
    live_out = CoPilotSkills(live_conn).alert_disposition_recorder(**recorder_kwargs())
    saved_out = CoPilotSkills(saved_conn).alert_disposition_recorder(**recorder_kwargs(ai_output_source=saved.SOURCE_SAVED, ai_output_captured_at=WHEN, ai_output_parts=["assessment", "draft"]))
    assert "ai_output" not in live_out["provenance"] and "saved_response" not in live_conn.stmts("INSERT")[0]
    prov = saved_out["provenance"]["ai_output"]
    assert prov["source"] == "saved_response" and prov["captured_at"] == WHEN and prov["parts"] == ["assessment", "draft"]
    assert "saved_response" in saved_conn.stmts("INSERT")[0], "it is inside METADATA_JSON, which the row hash covers"
    print("  [PASS] a saved reply is recorded as ai_output {source, captured_at, model, parts}; a live decision has no such key; it sits inside the hashed METADATA_JSON")


def _fake_lookup(prompt, table=None):
    if "Evaluate this case against each of the 11 PO evaluation factors" in prompt:
        return _entry(factors_json(triggered=("POE-003", "POE-005", "POE-007")))
    return None


def test_the_screen_offers_the_saved_assessment_beside_the_live_one_and_says_what_it_loaded():
    from test_ui_states import _disposition
    real = saved.lookup
    saved.lookup = lambda prompt, table=None: None      # an empty table: independent of whatever real replies the repository ships
    try:
        plain = _disposition("ALERT-16")
    finally:
        saved.lookup = real
    assert not plain.exception, [e.value for e in plain.exception]
    assert not any(b.label == T.SAVED_ASSESSMENT_BUTTON for b in plain.button), "nothing saved, nothing offered"
    assert any(b.label == "Run 11-Factor Assessment" for b in plain.button)

    saved.lookup = _fake_lookup
    try:
        at = _disposition("ALERT-16")
        assert not at.exception, [e.value for e in at.exception]
        assert any(b.label == "Run 11-Factor Assessment" for b in at.button), "the live option stays"
        assert any(b.label == T.SAVED_ASSESSMENT_BUTTON for b in at.button)
        assert any("matches this case exactly" in c.value for c in at.caption)
        next(b for b in at.button if b.label == T.SAVED_ASSESSMENT_BUTTON).click().run()
        assert not at.exception, [e.value for e in at.exception]
        notice = [i.value.replace("\\", "") for i in at.info if "saved model response" in i.value]
        assert notice and "5 Oct 2026 (UTC)" in notice[0] and "llama3.3-70b" in notice[0] and "not generated now" in notice[0], [i.value for i in at.info]
        assert at.session_state["assessment_source"] == saved.SOURCE_SAVED and at.session_state["assessment_captured_at"] == WHEN
    finally:
        saved.lookup = real
    print("  [PASS] the screen offers 'Load the saved assessment' next to the live button only when one matches, and says it is saved, when captured and by which model")


def test_the_replies_the_repository_ships_match_the_seeded_demo_alerts_exactly():
    """The saved data is real model output keyed by prompt hash. It is only useful if the prompt the application builds for a seeded alert hashes to a key in it."""
    from test_ui_states import _disposition
    assert len(DATA.SAVED) >= 19, "one saved assessment per seeded alert, plus drafts and their checks"
    assert {e["model"] for e in DATA.SAVED.values()} == {"llama3.3-70b"} and all(e["captured_at"].startswith("2026-10-06") for e in DATA.SAVED.values())
    for aid in ("ALERT-01", "ALERT-16"):
        at = _disposition(aid)
        assert not at.exception, [e.value for e in at.exception]
        assert any(b.label == T.SAVED_ASSESSMENT_BUTTON for b in at.button), f"{aid}: the shipped data does not match the prompt the application builds for it"
        assert any(b.label == "Run 11-Factor Assessment" for b in at.button), "the live option stays beside it"
    print("  [PASS] the shipped real replies match the prompt built for ALERT-01 and ALERT-16: the saved assessment is offered beside the live button")


def test_the_recorder_is_told_which_outputs_were_saved():
    from streamlit.testing.v1 import AppTest

    def harness():
        import streamlit as st
        import streamlit_app as ui
        st.session_state.update({"assessed_alert": "ALERT-16", "assessment_source": "saved_response", "assessment_captured_at": "2026-10-05T10:00:00+00:00",
                                 "gos_alert": "ALERT-16", "gos_result": {"output_source": "live", "output_captured_at": None}})
        a = ui._saved_output_args("ALERT-16", "FILE")
        st.session_state["gos_result"] = {"output_source": "saved_response", "output_captured_at": "2026-10-05T11:00:00+00:00"}
        b = ui._saved_output_args("ALERT-16", "FILE")
        st.session_state["assessment_source"] = "live"
        c = ui._saved_output_args("ALERT-16", "FILE")
        d = ui._saved_output_args("ALERT-16", None)
        e = ui._saved_output_args("ALERT-01", "FILE")
        st.json({"assessment_only": a, "both_saved": b, "draft_only": c, "no_ai": d, "other_alert": e})

    from test_ui_states import run_app  # noqa: F401  (imports the fake connector used by the page tests)
    at = AppTest.from_function(harness, default_timeout=60).run()
    assert not at.exception, [e.value for e in at.exception]
    out = json.loads(at.json[0].value)
    assert out["assessment_only"] == {"ai_output_source": "saved_response", "ai_output_captured_at": "2026-10-05T10:00:00+00:00", "ai_output_parts": ["assessment"]}
    assert out["both_saved"]["ai_output_parts"] == ["assessment", "draft"] and out["both_saved"]["ai_output_captured_at"] == "2026-10-05T10:00:00+00:00"
    assert out["draft_only"]["ai_output_parts"] == ["draft"] and out["draft_only"]["ai_output_captured_at"] == "2026-10-05T11:00:00+00:00"
    assert out["no_ai"] == {} and out["other_alert"] == {}, "no AI recommendation, or another alert's AI output, is never attributed to this decision"
    print("  [PASS] the app tells the recorder exactly which outputs (assessment / draft) were saved; none for a live, absent or other-alert AI")


def test_replies_can_be_gathered_from_several_runs_and_an_invalid_one_is_never_offered():
    import tempfile
    from pathlib import Path
    import eval_live_replay as R

    def folder(root, name, alerts, raw, when):
        d = Path(root) / name
        d.mkdir()
        (d / "results.json").write_text(json.dumps({"meta": {"generated_at_utc": when}, "alerts": alerts}))
        (d / "raw_responses.json").write_text(json.dumps(raw))
        return str(d)
    a1 = {"alert_id": "ALERT-01", "assessment_valid": True, "assessment_prompt_sha256": "h1"}
    a2 = {"alert_id": "ALERT-17", "assessment_valid": True, "assessment_prompt_sha256": "h2"}
    bad = {"alert_id": "ALERT-18", "assessment_valid": False, "assessment_prompt_sha256": "h3"}
    reply = lambda t: {"model": "m", "raw_response": t}   # noqa: E731
    with tempfile.TemporaryDirectory() as root:
        full = folder(root, "full", [a1, bad], {"h1": reply("first"), "h3": reply("never")}, "2026-10-06T08:00:00+00:00")
        extra = folder(root, "extra", [a1, a2], {"h1": reply("second"), "h2": reply("gulf")}, "2026-10-06T09:00:00+00:00")
        merged = R.saved_from_folders(f"{full},{extra}")
        assert set(merged) == {"h1", "h2"}, "an invalid assessment is not offered as a shortcut"
        assert merged["h1"]["raw_response"] == "first" and merged["h1"]["captured_at"].startswith("2026-10-06T08"), "the folder named first wins a clash"
        assert merged["h2"]["raw_response"] == "gulf" and merged["h2"]["captured_at"].startswith("2026-10-06T09"), "each reply keeps its own capture time"
        assert set(R.saved_from_folders(extra)) == {"h1", "h2"} and R.saved_from_folders(full).keys() == {"h1"}
    print("  [PASS] saved replies gather from several runs, the folder named first wins a clash, each keeps its own capture time, an invalid assessment is never offered")


TESTS = [
    test_the_replies_the_repository_ships_match_the_seeded_demo_alerts_exactly,
    test_replies_can_be_gathered_from_several_runs_and_an_invalid_one_is_never_offered,
    test_a_saved_reply_matches_one_exact_prompt_and_nothing_else,
    test_replay_is_equivalent_to_a_live_call_that_returns_the_same_text_and_sends_nothing,
    test_a_miss_fails_instead_of_quietly_calling_the_model_and_a_changed_record_is_a_miss,
    test_outside_replay_the_call_is_live_and_says_so,
    test_a_saved_reply_that_cites_a_transaction_the_record_does_not_hold_is_flagged_like_a_live_one,
    test_the_draft_is_offered_only_when_both_of_its_calls_are_saved,
    test_the_ledger_row_carries_ai_output_only_for_a_saved_reply_and_the_hash_covers_it,
    test_the_screen_offers_the_saved_assessment_beside_the_live_one_and_says_what_it_loaded,
    test_the_recorder_is_told_which_outputs_were_saved,
]

if __name__ == "__main__":
    raise SystemExit(Runner("Saved model responses (offline)").run(TESTS))
