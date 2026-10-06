"""
Decoding discipline for the live model calls (prompt v2.2).

Every live Cortex Complete call carries an explicit options object: temperature 0, a max_tokens cap for its purpose and, for the two replies that are
parsed, a JSON schema (structured outputs). These suites pin what that changes and what it must not:

  * the statement is still ONE statement, and a hostile prompt cannot leave its literal (the options form builds an array/object constant, so the
    escaping has to hold there too);
  * the reply envelope (structured_output / choices) is unpacked to the same text the parsers always saw, and token usage is kept;
  * a model that refuses the schema is asked again WITHOUT it, not given up on; a model that errors is still replaced by the fallback unless the
    comparison switch says otherwise;
  * the validators are not weakened: the object wrapper is accepted, anything else that is not one array is still rejected.

Offline. Usage:  python3 tests/test_decoding.py     (or pytest)
"""

from __future__ import annotations

import json

from _helpers import FakeConn, HOSTILE_STRINGS, Runner, case_context, checklist_json, factors_json, scan_sql, skills


def _sk(responder):
    from skills import CoPilotSkills
    conn = FakeConn([("CORTEX.COMPLETE", responder)])
    return CoPilotSkills(conn), conn


def _structured(obj, usage=None):
    return json.dumps({"created": 1, "model": "m", "structured_output": [{"raw_message": obj, "type": "json"}], "usage": usage or {"total_tokens": 7}})


def _choices(text, usage=None):
    return json.dumps({"choices": [{"messages": text}], "created": 1, "model": "m", "usage": usage or {"total_tokens": 5}})


def test_sf_const_renders_every_value_kind_and_keeps_hostile_text_inside_its_literal():
    from skills.core import _sf_const
    assert _sf_const({"a": 1, "b": True, "c": None, "d": [1.5, "x"]}) == "{'a': 1, 'b': TRUE, 'c': NULL, 'd': [1.5, 'x']}"
    for s in HOSTILE_STRINGS:
        sql = f"SELECT {_sf_const([{'role': 'user', 'content': s}])}, {_sf_const({s: s})}"
        n, lits = scan_sql(sql)
        assert n == 1, f"statement broke out for {s[:30]!r}"
        assert lits == ["role", "user", "content", s, s, s], f"literals not preserved for {s[:30]!r}"
    print(f"  [PASS] the options-form constant renders every value kind, and {len(HOSTILE_STRINGS)} hostile strings stay inside their literals as ONE statement")


def test_the_live_statement_carries_temperature_a_token_cap_and_the_schema():
    from skills import core
    sk, conn = _sk(lambda sql: [{"RESPONSE": _structured({"assessments": json.loads(factors_json())})}])
    out = sk._cortex_complete("PROMPT TEXT", schema=core.assessment_schema(), purpose="assessment")
    sql = conn.stmts("SELECT SNOWFLAKE.CORTEX.COMPLETE")[0]
    n, lits = scan_sql(sql)
    assert n == 1 and "PROMPT TEXT" in lits
    assert "'temperature': 0" in sql and f"'max_tokens': {core.COMPLETE_MAX_TOKENS['assessment']}" in sql and "'response_format'" in sql and "'json'" in sql
    assert sql.startswith("SELECT SNOWFLAKE.CORTEX.COMPLETE('llama3.3-70b', [{'role': 'user', 'content': 'PROMPT TEXT'}]")
    assert json.loads(out)["assessments"][0]["factor_id"] == "POE-002", "the structured reply comes back as the JSON text the parsers expect"
    assert sk.last_usage == {"total_tokens": 7} and sk.last_decoding == {"temperature": 0, "max_tokens": 3000, "structured": True}
    print("  [PASS] a live call asks for temperature 0, a purpose-sized max_tokens and the JSON schema; the reply and its token usage are kept")


def test_a_plain_reply_envelope_is_unpacked_and_a_draft_call_sends_no_schema():
    sk, conn = _sk(lambda sql: [{"RESPONSE": _choices("The account received three credits.")}])
    out = sk._cortex_complete("DRAFT PROMPT", purpose="draft")
    assert out == "The account received three credits."
    sql = conn.stmts("SELECT SNOWFLAKE.CORTEX.COMPLETE")[0]
    assert "response_format" not in sql and "'max_tokens': 1200" in sql
    assert sk.last_decoding["structured"] is False
    print("  [PASS] a draft call has no schema and a 1200-token cap; the choices envelope is unpacked to the text")


def test_unpack_complete_is_conservative():
    from skills.core import CoPilotSkills as K
    assert K._unpack_complete("plain text") == ("plain text", None)
    assert K._unpack_complete(None) == ("", None)
    assert K._unpack_complete("{not json") == ("{not json", None)
    assert K._unpack_complete('{"foo": 1}') == ('{"foo": 1}', None), "an object that is not the service envelope is returned untouched"
    assert K._unpack_complete(_structured([1, 2]))[0] == "[1, 2]"
    assert K._unpack_complete(_structured("already text"))[0] == "already text"
    assert K._unpack_complete('[1, 2]') == ('[1, 2]', None)
    print("  [PASS] only the service's own envelope is unpacked; anything else comes back exactly as it arrived")


def test_a_model_that_refuses_the_schema_is_asked_again_without_it():
    from skills import core
    calls = []

    def responder(sql):
        calls.append(sql)
        if "response_format" in sql:
            raise RuntimeError("SQL execution error: response_format is not supported for this model")
        return [{"RESPONSE": _choices("[]")}]

    sk, _ = _sk(responder)
    out = sk._cortex_complete("P", schema=core.checklist_schema(), purpose="check")
    assert len(calls) == 2 and "response_format" in calls[0] and "response_format" not in calls[1]
    assert calls[0].split("(", 1)[1].split(",")[0] == calls[1].split("(", 1)[1].split(",")[0], "the SAME model is retried, not the fallback"
    assert out == "[]" and sk.last_decoding["structured"] is False
    print("  [PASS] a schema refusal is retried once on the same model without the schema, and the call is recorded as not structured")


def test_a_failing_primary_falls_back_unless_the_comparison_switch_is_set():
    from skills import core
    seen = []

    def responder(sql):
        seen.append("llama3.1-8b" if "'llama3.1-8b'" in sql else "primary")
        if "'llama3.1-8b'" not in sql:
            raise RuntimeError("statement timeout exceeded")
        return [{"RESPONSE": _choices("ok")}]

    sk, _ = _sk(responder)
    assert sk._cortex_complete("P", purpose="draft") == "ok" and sk.last_model_used == "llama3.1-8b" and seen == ["primary", "llama3.1-8b"]
    before = core.NO_MODEL_FALLBACK
    core.NO_MODEL_FALLBACK = True
    try:
        seen.clear()
        sk2, _ = _sk(responder)
        try:
            sk2._cortex_complete("P", purpose="draft")
            raise AssertionError("with no fallback a timeout must surface")
        except RuntimeError as err:
            assert "No Cortex model available" in str(err) and seen == ["primary"]
    finally:
        core.NO_MODEL_FALLBACK = before
    print("  [PASS] a timeout falls back to the 8B model by default; with FIU_CORTEX_NO_FALLBACK it surfaces instead of being answered by another model")


def test_the_object_wrapper_is_accepted_and_nothing_else_is_loosened():
    from skills.llm_output import LLMOutputError, parse_json_array
    arr = [{"a": 1}]
    assert parse_json_array(json.dumps(arr)) == arr
    assert parse_json_array(json.dumps({"assessments": arr}), "assessments") == arr
    assert parse_json_array(json.dumps({"only": arr})) == arr
    for raw, key in [(json.dumps({"assessments": "no"}), "assessments"), (json.dumps({"x": arr}), "assessments"), (json.dumps({"a": arr, "b": arr}), None),
                     (json.dumps({"a": arr, "b": 1}), None), ("42", None), (json.dumps({"assessments": []}), "assessments")]:
        try:
            parse_json_array(raw, key)
            raise AssertionError(f"should have been rejected: {raw}")
        except LLMOutputError:
            pass
    print("  [PASS] {\"assessments\": [...]} is accepted; a missing key, a scalar, two lists or an empty list are still rejected")


def test_the_assessment_and_the_checklist_survive_the_wrapper_end_to_end():
    ctx = case_context()
    sk = skills(cortex_fn=lambda p: json.dumps({"assessments": json.loads(factors_json(triggered=("POE-003",)))}))
    out = sk.suspicion_evaluator(ctx)
    assert len(out) == 11 and all(f["ai_output_valid"] for f in out) and sum(f["assessment"] == "triggered" for f in out) == 1
    sk2 = skills(cortex_fn=lambda p: json.dumps({"checklist": json.loads(checklist_json())}))
    q = sk2.str_quality_checker("The account received credits. " * 12, ctx)
    assert q["ai_output_valid"] is True and q["quality_score"] == 10
    sk3 = skills(cortex_fn=lambda p: json.dumps({"assessments": json.loads(factors_json(drop=("POE-005",)))}))
    bad = sk3.suspicion_evaluator(ctx)
    assert all(f["ai_output_valid"] is False for f in bad), "a wrapped but INCOMPLETE assessment still fails closed"
    print("  [PASS] wrapped assessments and checklists parse; a wrapped assessment missing a factor still fails closed")


def test_schemas_name_every_factor_and_every_checklist_field():
    from skills import core
    a = core.assessment_schema()["schema"]["properties"]["assessments"]["items"]
    assert a["properties"]["factor_id"]["enum"] == [fid for fid, _ in core.POE_FACTORS]
    assert a["properties"]["assessment"]["enum"] == ["triggered", "clear", "insufficient_data"] and a["additionalProperties"] is False
    assert set(a["required"]) == {"factor_id", "factor_name", "assessment", "evidence", "evidence_txn_ids", "rules_cited"}
    c = core.checklist_schema()["schema"]["properties"]["checklist"]["items"]
    assert set(c["required"]) == {"item_number", "item", "applies", "note"} and c["properties"]["applies"]["type"] == "boolean"
    print("  [PASS] the assessment schema enumerates the eleven factor ids and the three verdicts; the checklist schema requires a boolean `applies`")


def test_prompts_ask_for_the_wrapper_keep_evidence_short_and_use_compact_transactions():
    sk = skills()
    ctx = case_context()
    ap = sk._assessment_prompt(ctx)
    assert '"assessments"' in ap and "at most 30 words" in ap and "indent" not in ap
    assert json.dumps(ctx["transactions"], separators=(",", ":")) in ap and json.dumps(ctx["transactions"], indent=2) not in ap
    cp = sk._checker_prompt("draft text", ctx)
    assert '"checklist"' in cp and json.dumps(ctx["transactions"], separators=(",", ":")) in cp
    gp = sk._gos_prompt(ctx, json.loads(factors_json(triggered=("POE-003",))))
    assert json.dumps(ctx["transactions"], separators=(",", ":")) in gp
    from skills import core
    assert core.PROMPT_VERSION == "v2.2"
    print("  [PASS] the three prompts carry the compact transaction block; the assessment and checklist prompts ask for the wrapped object; version v2.2")


TESTS = [
    test_sf_const_renders_every_value_kind_and_keeps_hostile_text_inside_its_literal,
    test_the_live_statement_carries_temperature_a_token_cap_and_the_schema,
    test_a_plain_reply_envelope_is_unpacked_and_a_draft_call_sends_no_schema,
    test_unpack_complete_is_conservative,
    test_a_model_that_refuses_the_schema_is_asked_again_without_it,
    test_a_failing_primary_falls_back_unless_the_comparison_switch_is_set,
    test_the_object_wrapper_is_accepted_and_nothing_else_is_loosened,
    test_the_assessment_and_the_checklist_survive_the_wrapper_end_to_end,
    test_schemas_name_every_factor_and_every_checklist_field,
    test_prompts_ask_for_the_wrapper_keep_evidence_short_and_use_compact_transactions,
]


if __name__ == "__main__":
    raise SystemExit(Runner("Decoding discipline for live model calls").run(TESTS))
