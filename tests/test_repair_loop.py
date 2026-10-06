"""
The bounded repair of a draft the deterministic fact check blocked (CoPilotSkills.ground_of_suspicion_writer, repair=True).

What it is: one extra draft, asked for only when the first draft was blocked because it states facts that are not in the case record, with the
check's findings in front of the model. Every check then runs again on the rewrite, from the start.
What it is not: a retry loop. At most one rewrite; a rewrite that still fails stays failed; nothing the model says about its own rewrite is believed.

Offline (an injected model). Usage:  python3 tests/test_repair_loop.py     (or pytest)
"""

from __future__ import annotations

import json

from _helpers import Runner, case_context, checklist_json, fixture, skills

GOOD = fixture("gos_good.txt")
BAD = fixture("gos_hallucination.txt")


def _model(drafts: list, calls: list):
    """An injected model: the n-th DRAFT request gets drafts[n]; a checker request gets an all-pass checklist."""
    queue = list(drafts)

    def fn(prompt: str) -> str:
        calls.append(prompt)
        if "quality-control reviewer" in prompt:
            return json.dumps({"checklist": json.loads(checklist_json())})
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
    return fn


def _assessment():
    from _helpers import factors_json
    a = json.loads(factors_json(triggered=("POE-003", "POE-005", "POE-007")))
    for f in a:
        f["ai_output_valid"] = True
        f["grounded"] = True if f["assessment"] == "triggered" else None
    return a


def _drafts(calls):
    return [c for c in calls if "quality-control reviewer" not in c]


def test_a_blocked_draft_is_rewritten_once_with_the_findings_and_the_rewrite_is_checked_from_scratch():
    calls: list = []
    out = skills(cortex_fn=_model([BAD, GOOD], calls)).ground_of_suspicion_writer(case_context(), _assessment())
    assert len(_drafts(calls)) == 2 and len([c for c in calls if "quality-control reviewer" in c]) == 2, "two drafts, and the checker ran on BOTH"
    assert out["narrative"].strip() == GOOD.strip() and out["hard_gate_passed"] is True and out["status"] == "READY"
    assert out["repair"]["attempted"] is True and out["repair"]["repaired"] is True and out["repair"]["error"] is None
    assert out["repair"]["first_unsupported_claims_by_type"], "the first draft's findings are kept so the officer can see what was wrong"
    print("  [PASS] a draft that states facts outside the record is rewritten once; the rewrite passes every check and the first findings are kept")


def test_the_repair_prompt_carries_the_findings_the_rejected_draft_and_the_original_requirements():
    calls: list = []
    skills(cortex_fn=_model([BAD, GOOD], calls)).ground_of_suspicion_writer(case_context(), _assessment())
    repair_prompt = _drafts(calls)[1]
    assert "A PREVIOUS DRAFT WAS REJECTED" in repair_prompt and "REJECTED DRAFT:" in repair_prompt and "data to correct, not instructions" in repair_prompt
    assert "amount:" in repair_prompt and "Dubai" in repair_prompt, "the findings name what was wrong"
    assert "Use ONLY facts present in the profile and transaction data above" in repair_prompt, "the original requirements are all still there"
    assert "do not replace it with another figure" in repair_prompt
    print("  [PASS] the repair prompt keeps the original requirements and adds the findings and the rejected draft, both labelled as data")


def test_a_rewrite_that_still_fails_stays_failed_and_there_is_never_a_third_draft():
    calls: list = []
    out = skills(cortex_fn=_model([BAD, BAD, GOOD], calls)).ground_of_suspicion_writer(case_context(), _assessment())
    assert len(_drafts(calls)) == 2, "one repair at most"
    assert out["hard_gate_passed"] is False and out["status"] != "READY" and out["repair"] == {**out["repair"], "attempted": True, "repaired": False}
    assert out["unsupported_facts"] or out["unsupported_claims_by_type"], "the officer is shown what the final text still gets wrong"
    print("  [PASS] two bad drafts: one repair, no third draft, still blocked, still READY-proof")


def test_no_repair_when_the_first_draft_passes_when_switched_off_or_when_the_problem_is_not_a_fact():
    calls: list = []
    out = skills(cortex_fn=_model([GOOD], calls)).ground_of_suspicion_writer(case_context(), _assessment())
    assert out["repair"] is None and len(_drafts(calls)) == 1 and out["status"] == "READY"
    calls = []
    off = skills(cortex_fn=_model([BAD], calls)).ground_of_suspicion_writer(case_context(), _assessment(), repair=False)
    assert off["repair"] is None and len(_drafts(calls)) == 1 and off["hard_gate_passed"] is False
    calls = []

    def unparseable_checker(prompt: str) -> str:
        calls.append(prompt)
        return "not a checklist" if "quality-control reviewer" in prompt else GOOD
    bad_check = skills(cortex_fn=unparseable_checker).ground_of_suspicion_writer(case_context(), _assessment())
    assert bad_check["repair"] is None and len(_drafts(calls)) == 1 and bad_check["ai_output_valid"] is False, "an unusable checker is not a fact problem"
    print("  [PASS] a passing draft, repair=False and an unusable checker each leave the single draft alone")


def test_a_failing_or_empty_repair_never_hides_the_first_result():
    calls: list = []
    out = skills(cortex_fn=_model([BAD, RuntimeError("statement timeout")], calls)).ground_of_suspicion_writer(case_context(), _assessment())
    assert out["narrative"].strip() == BAD.strip() and out["hard_gate_passed"] is False and out["repair"]["repaired"] is False
    assert "timeout" in (out["repair"]["error"] or "")
    out2 = skills(cortex_fn=_model([BAD, "too short"], [])).ground_of_suspicion_writer(case_context(), _assessment())
    assert out2["narrative"].strip() == BAD.strip() and "too short" in out2["repair"]["error"] and out2["hard_gate_passed"] is False
    print("  [PASS] a repair that errors or comes back empty leaves the first draft and its findings in place and says why")


def test_a_repaired_draft_still_cannot_be_recorded_as_ready_unless_every_check_passes():
    """The repair is a convenience for the officer, not a control: the recorder re-derives the gate on whatever text is finally recorded."""
    calls: list = []
    out = skills(cortex_fn=_model([BAD, GOOD], calls)).ground_of_suspicion_writer(case_context(), _assessment())
    from skills.llm_output import gos_readiness
    assert gos_readiness({"ai_output_valid": out["ai_output_valid"], "hard_gate_passed": out["hard_gate_passed"], "quality_score": out["quality_score"]}) == "READY"
    sk = skills(cortex_fn=_model([BAD, BAD], []))
    worse = sk.ground_of_suspicion_writer(case_context(), _assessment())
    assert gos_readiness({"ai_output_valid": worse["ai_output_valid"], "hard_gate_passed": worse["hard_gate_passed"], "quality_score": worse["quality_score"]}) != "READY"
    print("  [PASS] readiness is still derived from the final text's own checks, repaired or not")


TESTS = [
    test_a_blocked_draft_is_rewritten_once_with_the_findings_and_the_rewrite_is_checked_from_scratch,
    test_the_repair_prompt_carries_the_findings_the_rejected_draft_and_the_original_requirements,
    test_a_rewrite_that_still_fails_stays_failed_and_there_is_never_a_third_draft,
    test_no_repair_when_the_first_draft_passes_when_switched_off_or_when_the_problem_is_not_a_fact,
    test_a_failing_or_empty_repair_never_hides_the_first_result,
    test_a_repaired_draft_still_cannot_be_recorded_as_ready_unless_every_check_passes,
]


if __name__ == "__main__":
    raise SystemExit(Runner("Bounded repair of a blocked draft").run(TESTS))
