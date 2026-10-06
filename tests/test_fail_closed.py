"""
Fail-closed AI-output handling (Critical finding #1).

Every malformed / empty / unexpected model-output path must produce:
  * status REJECT or NEEDS_MANUAL_REVIEW  (never READY)
  * hard_gate_passed == False
  * quality_score == 0 (never a defaulted 10/10)
and the workflow layer (gos_readiness) must refuse READY.

Offline only — the model is injected via cortex_fn, so every branch is deterministic.

Usage:  python3 tests/test_fail_closed.py     (or pytest)
"""

from __future__ import annotations

import json

from _helpers import (Runner, case_context, checklist_json, factors_json, fixture, skills)

NOT_READY = ("REJECT", "NEEDS_MANUAL_REVIEW")


def _assert_fail_closed(res: dict, why: str):
    assert res["status"] in NOT_READY, f"{why}: status={res['status']} (must be REJECT/NEEDS_MANUAL_REVIEW)"
    assert res["recommendation"] != "READY", f"{why}: recommendation READY"
    assert res["hard_gate_passed"] is False, f"{why}: hard_gate_passed must be False"
    assert res["ai_output_valid"] is False, f"{why}: ai_output_valid must be False"
    assert res["quality_score"] == 0, f"{why}: quality_score={res['quality_score']} (must be 0, not a default pass)"
    assert res["passed"] is False, f"{why}: passed must be False"
    assert res["ai_output_error"], f"{why}: an error reason must be surfaced to the UI"


def _qc(model_output, narrative=None) -> dict:
    narrative = narrative if narrative is not None else fixture("gos_good.txt")
    return skills(lambda p: model_output).str_quality_checker(narrative, case_context())


# ── str_quality_checker: the five cases the audit named ─────────────────────

def test_qc_malformed_json():
    for bad in ('[{"item_number": 1, "applies": fals', "not json at all", "{'item_number': 1}",
                '[{"item_number": 1,'):
        _assert_fail_closed(_qc(bad), f"malformed {bad[:20]!r}")
    print("  [PASS] QC malformed JSON → NEEDS_MANUAL_REVIEW, hard gate false, score 0")


def test_qc_empty_output():
    for empty in ("", "   \n  ", None, "[]", "null"):
        _assert_fail_closed(_qc(empty), f"empty {empty!r}")
    print("  [PASS] QC empty / None / [] / null output → fail closed")


def test_qc_markdown_wrapped_invalid_output():
    for bad in ("```json\n{not valid}\n```",
                "Here you go:\n```json\n[{\"item_number\": 1, \"applies\": \n```",       # truncated inside fence
                "```\nSorry, I cannot evaluate this narrative.\n```",
                "```json\n```"):
        _assert_fail_closed(_qc(bad), f"fenced {bad[:24]!r}")
    print("  [PASS] QC markdown-wrapped invalid output → fail closed")


def test_qc_incomplete_output():
    nine = json.loads(checklist_json())[:9]
    _assert_fail_closed(_qc(json.dumps(nine)), "9 of 10 items")
    one = json.loads(checklist_json())[:1]
    _assert_fail_closed(_qc(json.dumps(one)), "1 of 10 items")
    dup = json.loads(checklist_json())
    dup[9] = dict(dup[0])                                       # item 1 twice, item 10 missing
    _assert_fail_closed(_qc(json.dumps(dup)), "duplicate item / missing item")
    print("  [PASS] QC incomplete factor output (9/10, 1/10, duplicate) → fail closed")


def test_qc_wrong_json_shape():
    cases = {
        "dict instead of array":      json.dumps({"results": json.loads(checklist_json())}),
        "array of strings":           json.dumps(["pass"] * 10),
        "array of arrays":            json.dumps([[1, False]] * 10),
        "applies as string 'false'":  json.dumps([{"item_number": i + 1, "applies": "false", "note": ""} for i in range(10)]),
        "applies missing":            json.dumps([{"item_number": i + 1, "note": ""} for i in range(10)]),
        "item_number out of range":   json.dumps([{"item_number": i + 11, "applies": False} for i in range(10)]),
        "item_number as string":      json.dumps([{"item_number": str(i + 1), "applies": False} for i in range(10)]),
        "bare number":                "10",
    }
    for why, out in cases.items():
        _assert_fail_closed(_qc(out), why)
    print(f"  [PASS] QC wrong JSON shape ({len(cases)} variants) → fail closed")


def test_qc_cortex_error_fails_closed_but_keeps_deterministic_gate():
    def boom(_prompt):
        raise RuntimeError("Cortex unavailable\nSELECT secret_prompt_text_here")
    res = skills(boom).str_quality_checker(fixture("gos_good.txt"), case_context())
    _assert_fail_closed(res, "cortex exception")
    assert "secret_prompt_text_here" not in res["ai_output_error"], "error must not leak SQL/prompt text"
    assert res["evidence_gate_passed"] is True, "deterministic gate still ran independently"
    print("  [PASS] Cortex exception → fail closed; error sanitised; deterministic gate still ran")


def test_qc_valid_output_still_passes_and_fenced_json_accepted():
    """Guard against over-rejection: well-formed output (even fenced / after prose) is accepted."""
    for wrapped in (checklist_json(), f"```json\n{checklist_json()}\n```",
                    f"Here is my evaluation:\n```json\n{checklist_json()}\n```"):
        res = _qc(wrapped)
        assert res["ai_output_valid"] is True and res["status"] == "READY", res
        assert res["quality_score"] == 10 and res["hard_gate_passed"] is True
    revise = _qc(checklist_json([True, True, True, False, False, False, False, False, False, False]))
    assert revise["status"] == "NEEDS_REVISION" and revise["quality_score"] == 7, revise["status"]
    print("  [PASS] valid / fenced / prose-prefixed output accepted; score 7 → NEEDS_REVISION (no over-rejection)")


def test_qc_model_cannot_rewrite_check_text():
    """The model-supplied 'item' text is ignored; the canonical checklist is reported."""
    from skills.core import CHECKLIST_ITEMS
    res = _qc(checklist_json())
    assert [c["item"] for c in res["checklist"]] == CHECKLIST_ITEMS
    print("  [PASS] checklist items are canonical (model cannot rename a check)")


# ── ground_of_suspicion_writer ──────────────────────────────────────────────

def _writer(model):
    from skills.core import POE_FACTORS  # noqa: F401
    assessment = skills(lambda p: factors_json(triggered=("POE-003", "POE-005", "POE-007"))).suspicion_evaluator(case_context())
    return skills(model).ground_of_suspicion_writer(case_context(), assessment)


def test_writer_invalid_quality_output_never_ready():
    good_narrative = fixture("gos_good.txt")

    def model(prompt):
        return good_narrative if "DRAFT GROUND OF SUSPICION" not in prompt else "garbage"
    res = _writer(model)
    assert res["status"] == "NEEDS_MANUAL_REVIEW" and res["hard_gate_passed"] is False
    assert res["narrative"] == good_narrative.strip(), "the draft is preserved for the PO"
    assert res["quality_score"] == 0
    print("  [PASS] writer: valid draft + garbage QC output → NEEDS_MANUAL_REVIEW (draft kept)")


def test_writer_empty_or_short_narrative_blocked():
    for out in ("", None, "Suspicious.", "x" * 199):
        res = _writer(lambda p, out=out: out)
        assert res["status"] == "NEEDS_MANUAL_REVIEW" and res["hard_gate_passed"] is False, res
    print("  [PASS] writer: empty / None / <200-char narrative → NEEDS_MANUAL_REVIEW")


def test_writer_refuses_to_draft_from_invalid_assessment():
    calls = []
    sk = skills(lambda p: calls.append(p) or "")
    bad_assessment = skills(lambda p: "garbage").suspicion_evaluator(case_context())
    res = sk.ground_of_suspicion_writer(case_context(), bad_assessment)
    assert res["status"] == "NEEDS_MANUAL_REVIEW" and res["hard_gate_passed"] is False
    assert calls == [], "no model call may be made from an untrusted assessment"
    partial = json.loads(factors_json(triggered=("POE-003",)))[:6]
    res2 = sk.ground_of_suspicion_writer(case_context(), partial)
    assert res2["status"] == "NEEDS_MANUAL_REVIEW" and calls == []
    print("  [PASS] writer: invalid / partial assessment → no draft, NEEDS_MANUAL_REVIEW, zero model calls")


def test_writer_ready_only_when_everything_valid():
    def model(prompt):
        return checklist_json() if "DRAFT GROUND OF SUSPICION" in prompt else fixture("gos_good.txt")
    res = _writer(model)
    assert res["status"] == "READY" and res["hard_gate_passed"] and res["ai_output_valid"], res["status"]
    print("  [PASS] writer: READY only when assessment, draft, QC output and evidence gate are all valid")


# ── central readiness decision ──────────────────────────────────────────────

def test_gos_readiness_defaults_never_ready():
    from skills.llm_output import gos_readiness
    for q in (None, {}, [], "READY", {"quality_score": 10}, {"quality_score": 10, "hard_gate_passed": True},
              {"quality_score": 10, "ai_output_valid": True},
              {"quality_score": 10, "ai_output_valid": "yes", "hard_gate_passed": True},
              {"quality_score": True, "ai_output_valid": True, "hard_gate_passed": True},
              {"quality_score": "10", "ai_output_valid": True, "hard_gate_passed": True},
              {"quality_score": 10, "ai_output_valid": True, "hard_gate_passed": False},
              {"quality_score": 10, "ai_output_valid": False, "hard_gate_passed": True}):
        assert gos_readiness(q) != "READY", f"{q!r} must not be READY"
    assert gos_readiness({"quality_score": 8, "ai_output_valid": True, "hard_gate_passed": True}) == "READY"
    print("  [PASS] gos_readiness: every missing / mistyped / false input is non-READY (no fail-open defaults)")


# ── suspicion_evaluator + sufficiency summary ───────────────────────────────

def _assess(out):
    return skills(lambda p: out).suspicion_evaluator(case_context())


def test_evaluator_bad_output_yields_invalid_assessment_and_manual_review():
    sk = skills()
    bad_outputs = {
        "malformed":        '[{"factor_id": "POE-002", "assessment": "trig',
        "empty":            "",
        "none":             None,
        "empty array":      "[]",
        "fenced garbage":   "```json\nnope\n```",
        "wrong shape dict": json.dumps({"factors": json.loads(factors_json())}),
        "strings":          json.dumps(["triggered"] * 11),
        "incomplete (8/11)": factors_json(drop=("POE-002", "POE-003", "POE-004")),
        "unknown assessment": factors_json(assessment="maybe"),
        "unknown factor id": json.dumps([{"factor_id": "POE-999", "assessment": "clear", "evidence": "x"}] * 11),
    }
    for why, out in bad_outputs.items():
        a = _assess(out)
        assert len(a) == 11 and all(f["ai_output_valid"] is False for f in a), why
        assert all(f["assessment"] == "insufficient_data" for f in a), f"{why}: must never default to clear/triggered"
        summ = sk.evidence_sufficiency_summary(a)
        assert summ["recommendation"] == "NEEDS_MANUAL_REVIEW", f"{why}: {summ['recommendation']}"
        assert summ["ai_output_valid"] is False and summ["ai_output_error"]
        assert sk.assessment_validity(a)["valid"] is False
    print(f"  [PASS] evaluator: {len(bad_outputs)} bad-output variants → invalid assessment → NEEDS_MANUAL_REVIEW")


def test_evaluator_valid_output_including_fenced_and_case_variants():
    fenced = f"```json\n{factors_json(triggered=('POE-003', 'POE-005', 'POE-007'))}\n```"
    a = _assess(fenced)
    assert all(f["ai_output_valid"] for f in a)
    assert skills().evidence_sufficiency_summary(a)["recommendation"] == "FILE"
    upper = json.loads(factors_json()); upper[0]["assessment"] = "  CLEAR "
    assert _assess(json.dumps(upper))[0]["assessment"] == "clear"
    print("  [PASS] evaluator: valid / fenced / case-variant output accepted")


def test_missing_evidence_is_downgraded_toward_insufficient_never_toward_clear_or_triggered():
    """Found live 2026-09-30: the fallback model returned a factor with empty evidence. One empty field must
    not discard the whole assessment, but it also must never become a 'clear' or a FILE-supporting 'triggered'."""
    from skills.core import POE_FACTORS
    rows = [{"factor_id": f, "assessment": a} for (f, _), a in zip(POE_FACTORS, ["triggered", "clear"] * 6)]   # no evidence keys at all
    a = _assess(json.dumps(rows))
    assert all(f["ai_output_valid"] for f in a) and all(f["assessment"] == "insufficient_data" for f in a), a[0]
    assert {f.get("normalised_from") for f in a} == {"triggered", "clear"}
    assert skills().evidence_sufficiency_summary(a)["recommendation"] == "INSUFFICIENT_EVIDENCE"
    mixed = json.loads(factors_json(triggered=("POE-003", "POE-005", "POE-007")))
    mixed[0]["evidence"] = "   "                       # POE-002 clear w/o evidence → insufficient
    mixed[1]["evidence"] = ""                          # POE-003 triggered w/o evidence → insufficient (cannot support FILE)
    b = _assess(json.dumps(mixed))
    assert [f["assessment"] for f in b[:2]] == ["insufficient_data", "insufficient_data"] and b[1]["normalised_from"] == "triggered"
    assert skills().evidence_sufficiency_summary(b)["recommendation"] == "REVIEW", \
        "only 2 triggered factors retain evidence → human REVIEW, not FILE"
    bad_type = json.loads(factors_json()); bad_type[0]["evidence"] = ["not", "a", "string"]
    assert _assess(json.dumps(bad_type))[0]["ai_output_valid"] is False, "wrong TYPES stay hard failures"
    print("  [PASS] missing evidence → insufficient_data (clear→insufficient, triggered→insufficient); wrong types still invalid")


def test_sufficiency_summary_rejects_empty_and_hand_built_partials():
    sk = skills()
    for bad in ([], None, [{}], [{"factor_id": "POE-002", "assessment": "triggered", "evidence": "x"}] * 3,
                "not a list"):
        assert sk.evidence_sufficiency_summary(bad)["recommendation"] == "NEEDS_MANUAL_REVIEW", bad
    print("  [PASS] sufficiency summary: empty / partial / hand-built assessment → NEEDS_MANUAL_REVIEW")


TESTS = [
    test_qc_malformed_json, test_qc_empty_output, test_qc_markdown_wrapped_invalid_output,
    test_qc_incomplete_output, test_qc_wrong_json_shape,
    test_qc_cortex_error_fails_closed_but_keeps_deterministic_gate,
    test_qc_valid_output_still_passes_and_fenced_json_accepted, test_qc_model_cannot_rewrite_check_text,
    test_writer_invalid_quality_output_never_ready, test_writer_empty_or_short_narrative_blocked,
    test_writer_refuses_to_draft_from_invalid_assessment, test_writer_ready_only_when_everything_valid,
    test_gos_readiness_defaults_never_ready,
    test_evaluator_bad_output_yields_invalid_assessment_and_manual_review,
    test_evaluator_valid_output_including_fenced_and_case_variants,
    test_missing_evidence_is_downgraded_toward_insufficient_never_toward_clear_or_triggered,
    test_sufficiency_summary_rejects_empty_and_hand_built_partials,
]

if __name__ == "__main__":
    raise SystemExit(Runner("Fail-closed AI output tests (no Snowflake required)").run(TESTS))
