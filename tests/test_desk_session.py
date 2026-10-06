"""
Time on the desk, as a stated proxy (R3): a bounded measurement stored inside the sealed provenance, and a KPI that says exactly what it is.

  * clean_desk_session accepts only whole, bounded, non-negative seconds and never lets model waiting exceed the session;
  * the recorder stores it inside METADATA_JSON (so the ledger's row hash covers it) and stores nothing when none is supplied or it is malformed;
  * the KPI is a PROXY with its caveat when decisions carry the measurement, NOT_MEASURED otherwise, and it never produces an improvement claim;
  * the Investigation desk starts the clock when a case is first shown, subtracts model waiting, and restarts after a decision.

Offline. Usage:  python3 tests/test_desk_session.py     (or pytest)
"""

from __future__ import annotations

import json

from _helpers import FakeConn, Runner, recorder_kwargs


def test_the_desk_session_is_cleaned_to_whole_bounded_seconds():
    from skills.ledger import DESK_SESSION_BASIS, clean_desk_session
    ok = clean_desk_session({"opened_at_utc": "2026-10-05T10:00:00+00:00", "desk_seconds": 312.6, "model_wait_seconds": 100.2})
    assert ok == {"opened_at_utc": "2026-10-05T10:00:00+00:00", "desk_seconds": 313, "model_wait_seconds": 100, "hands_on_upper_bound_seconds": 213, "basis": DESK_SESSION_BASIS}
    assert clean_desk_session({"desk_seconds": 60, "model_wait_seconds": 90})["model_wait_seconds"] == 60, "waiting for a model can never exceed the session"
    assert clean_desk_session({"desk_seconds": 10 ** 9})["desk_seconds"] == 7 * 24 * 3600, "an absurd value is clamped to a week"
    assert clean_desk_session({"desk_seconds": 5, "model_wait_seconds": "x"})["model_wait_seconds"] == 0
    for bad in (None, "text", [], {}, {"desk_seconds": -1}, {"desk_seconds": "abc"}, {"desk_seconds": float("nan")}, {"desk_seconds": float("inf")}, {"model_wait_seconds": 3}):
        assert clean_desk_session(bad) is None, bad
    print("  [PASS] whole seconds, clamped to a week, model wait capped at the session, and anything malformed is dropped")


def test_the_recorder_stores_it_inside_the_sealed_provenance_and_stores_nothing_otherwise():
    from skills import CoPilotSkills
    with_it = CoPilotSkills(FakeConn()).alert_disposition_recorder(**recorder_kwargs(desk_session={"desk_seconds": 400, "model_wait_seconds": 120, "opened_at_utc": "2026-10-05T10:00:00+00:00"}))
    d = with_it["provenance"]["desk_session"]
    assert d["desk_seconds"] == 400 and d["hands_on_upper_bound_seconds"] == 280 and "proxy" in d["basis"]
    conn = FakeConn()
    CoPilotSkills(conn).alert_disposition_recorder(**recorder_kwargs(desk_session={"desk_seconds": 400}))
    insert = conn.stmts("INSERT")[0]
    assert "desk_seconds" in insert and "hands_on_upper_bound_seconds" in insert, "it is part of METADATA_JSON, which the row hash covers"
    without = CoPilotSkills(FakeConn()).alert_disposition_recorder(**recorder_kwargs())
    assert "desk_session" not in without["provenance"]
    malformed = CoPilotSkills(FakeConn()).alert_disposition_recorder(**recorder_kwargs(desk_session={"desk_seconds": "NaN?"}))
    assert "desk_session" not in malformed["provenance"], "a malformed value is dropped, never written"
    print("  [PASS] stored inside METADATA_JSON when supplied and valid; absent otherwise; a malformed value never reaches a sealed row")


def _row(disposition, desk=None, aid="ALERT-01", when="2026-10-05T10:00:00"):
    meta = {"schema_version": "3", "human_decision": disposition}
    if desk is not None:
        meta["desk_session"] = {"desk_seconds": desk + 60, "model_wait_seconds": 60, "hands_on_upper_bound_seconds": desk, "basis": "x"}
    return {"DISPOSITION": disposition, "ALERT_ID": aid, "DECISION_MADE_AT": when, "SUSPICION_FORMED_AT": None, "SLA_DAYS_REMAINING": 5, "META_TEXT": json.dumps(meta)}


def test_the_kpi_is_a_proxy_with_its_caveat_when_decisions_carry_it_and_never_a_claim():
    from skills import kpis as K
    rows = [_row("FILE", 300), _row("NOT_FILE", 600, "ALERT-02"), _row("FILE", 900, "ALERT-03"), _row("DEFERRED", None, "ALERT-04")]
    k = {x["id"]: x for x in K.compute_kpis(rows, [])["kpis"]}["investigation_time"]
    assert k["status"] == K.PROXY and k["value"] == 600 and k["n"] == 3 and "10.0 min" in k["display"] and "p90" in k["display"]
    assert "1 decision(s) carry no desk-session measurement" in k["caveat"] and "UPPER BOUND" in k["caveat"] and "No baseline exists" in k["caveat"]
    assert "30 decisions" in k["needs"]
    none = {x["id"]: x for x in K.compute_kpis([_row("FILE")], [])["kpis"]}["investigation_time"]
    assert none["status"] == K.NOT_MEASURED and none["value"] is None and "telemetry" in none["needs"].lower() or "case-management" in none["needs"].lower()
    assert K.compute_kpis(rows, [])["baseline"]["captured"] is False
    assert K.improvement(None, {"value": 600, "n": 3, "definition": "d"}, higher_is_better=False)["allowed"] is False
    print("  [PASS] median 10.0 min (p90 15.0 min) over the 3 decisions that carry a measurement; the other is counted and excluded; no baseline, so no improvement claim")


def test_the_investigation_desk_starts_the_clock_subtracts_model_waiting_and_restarts_after_a_decision():
    import streamlit_app as ui
    from streamlit.testing.v1 import AppTest

    def harness():
        import json
        import time
        import streamlit as st
        import streamlit_app as app
        app._desk_open("ALERT-77")
        st.session_state["_desk_opened_ALERT-77"] = time.time() - 300       # five minutes ago
        app._model_wait_add("ALERT-77", 90.0)
        app._model_wait_add("ALERT-77", 30.5)
        args = app._desk_session_args("ALERT-77")["desk_session"]
        st.write(json.dumps({"desk": round(args["desk_seconds"]), "wait": args["model_wait_seconds"], "opened": args["opened_at_utc"][:4]}))
        assert app._desk_session_args("ALERT-NEVER-OPENED") == {}, "no clock was started for a case that was never opened"
    at = AppTest.from_function(harness, default_timeout=30).run()
    assert not at.exception, [e.value for e in at.exception]
    data = json.loads(at.markdown[0].value)
    assert 299 <= data["desk"] <= 302 and data["wait"] == 120.5 and data["opened"] == "2026"
    assert ui.PACK_APP_VERSION
    print("  [PASS] the clock starts when the case is first shown; model waiting accumulates; a case that was never opened has no clock")


def test_the_recording_call_passes_the_desk_session_and_clears_the_clock():
    import inspect
    import streamlit_app as ui
    src = inspect.getsource(ui._record_disposition)
    assert "_desk_session_args(alert_id)" in src and 'st.session_state.pop(f"_desk_opened_{alert_id}", None)' in src and 'st.session_state.pop(f"_model_wait_{alert_id}", None)' in src
    page = inspect.getsource(ui.page_disposition)
    assert "_desk_open(selected)" in page
    live = inspect.getsource(ui)
    assert live.count("_model_wait_add(selected") >= 4, "both model calls add their waiting time on success and on failure"
    print("  [PASS] the recorder call carries the desk session, a decision clears the clock, the desk opens it, and both model calls are timed")


TESTS = [
    test_the_desk_session_is_cleaned_to_whole_bounded_seconds,
    test_the_recorder_stores_it_inside_the_sealed_provenance_and_stores_nothing_otherwise,
    test_the_kpi_is_a_proxy_with_its_caveat_when_decisions_carry_it_and_never_a_claim,
    test_the_investigation_desk_starts_the_clock_subtracts_model_waiting_and_restarts_after_a_decision,
    test_the_recording_call_passes_the_desk_session_and_clears_the_clock,
]


if __name__ == "__main__":
    raise SystemExit(Runner("Time on the desk (session proxy)").run(TESTS))
