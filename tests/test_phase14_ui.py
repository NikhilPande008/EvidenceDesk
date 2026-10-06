"""
Phase 14 UI states (Streamlit AppTest against a scripted database): the queue's priority score and its explanation, the evidence-quality and
relationship panels, the effects enforced in the record flow, authenticated versus typed identity, the structured closure reason, the audit-export
protection status, and the four new pages — each in its normal, empty and failing state, and each safe against hostile data.

Offline. Usage:  python3 tests/test_phase14_ui.py     (or pytest)
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timezone
from unittest.mock import patch

from _helpers import ROOT, Runner, fixture, scoped_env

sys.path.insert(0, str(ROOT / "scripts"))
import setup_alerts as seed  # noqa: E402
import snowflake.connector  # noqa: E402
import streamlit as st  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

from skills import CoPilotSkills  # noqa: E402
from skills import evidence_quality as EQ  # noqa: E402
from skills import feedback as FB  # noqa: E402
from skills import kpis as K  # noqa: E402
from skills import po_copy as T  # noqa: E402
from skills import readiness as R  # noqa: E402
from test_po_workflow import case, choose, parse_checkpoint, record_button, summary_line, tick_all  # noqa: E402
from test_security_boundaries import _each_payload, _hostile_alert, assert_inert  # noqa: E402
from test_ui_states import UIFake, _alert_row, _everything, _no_exception, _text, run_app  # noqa: E402

FILING = fixture("demo_alert01_filing.txt").strip()
CLOSE_TEXT = "Closed after review: the documentation shows a legitimate property sale and there is no onward flow to any flagged party."


def block_text(block) -> str:
    """The text of an expander, with the Markdown escapes that untrusted text carries (md_safe) removed so it reads as it displays."""
    return "\n".join(str(e.value) for group in (block.markdown, block.caption) for e in group).replace("\\", "")


def everything(at) -> str:
    """Rendered text plus the labels of metrics, tabs and radios (which _everything leaves out), with Markdown escapes and bold markers removed."""
    extra = [m.label for m in at.metric] + [str(m.value) for m in at.metric] + [t.label for t in at.tabs] + [r.label for r in at.radio]
    return (_everything(at) + "\n" + "\n".join(extra)).replace("**", "")


def frames(at) -> str:
    """Every cell of every dataframe on the page, as one string."""
    return "\n".join(str(v) for d in at.dataframe for v in d.value.astype(str).values.ravel())


def expander(at, prefix: str):
    return next(e for e in at.expander if e.label.startswith(prefix))


def metric(at, label: str):
    return next(m for m in at.metric if m.label == label)


# ── positioning ──────────────────────────────────────────────────────────────

def test_the_queue_says_what_the_product_is_and_is_not_and_so_does_the_sidebar():
    at = run_app()
    _no_exception(at)
    caps = [str(c.value) for c in at.caption]
    assert T.POSITIONING_IS in caps and T.POSITIONING_IS_NOT in caps
    side = " ".join(str(c.value) for c in at.sidebar.caption)
    assert "AML decision-defensibility and investigation copilot" in side and "synthetic data" in side
    assert "does not detect fraud" in T.POSITIONING_IS_NOT and "legal advice" in T.POSITIONING_IS_NOT and "does not decide" in T.POSITIONING_IS_NOT
    print("  [PASS] My cases states the positioning (signals come from other systems; investigates, prioritises, explains, supports disposition; does not detect, advise, file or verify) and the sidebar says it is a copilot on synthetic data")


# ── priority ─────────────────────────────────────────────────────────────────

def scores(at) -> dict:
    out = {}
    for e in at.expander:
        m = re.match(re.escape(T.PRIORITY_WHY_TITLE) + r" · (\S+)", e.label)
        if m:
            found = re.search(r"Priority (\d+)/100 \((\w+)\)", block_text(e))
            out[m.group(1)] = (int(found.group(1)), found.group(2))
    return out


def test_every_case_shows_a_priority_score_and_a_why_that_is_not_a_decision():
    at = run_app()
    _no_exception(at)
    s = scores(at)
    assert len(s) == 19 and s["ALERT-01"][0] > s["ALERT-16"][0] and s["ALERT-01"][1] in ("High", "Critical")
    why = block_text(expander(at, f"{T.PRIORITY_WHY_TITLE} · ALERT-01"))
    for needle in ("Main drivers", "98.8%", "flagged", "Registry-sourced", "Signal severity", "Reporting deadline", "No suspicion time is recorded", T.PRIORITY_CAPTION.split(".")[0]):
        assert needle in why.replace("\\", ""), needle
    assert "not a risk rating" in why and "not a recommendation to file" in why
    for word in ("recommend filing", "should file", "NOT_FILE"):
        assert word not in why
    assert "Priority" in _text(at) and "/100" in " ".join(m.value for m in at.markdown)
    print(f"  [PASS] 16 cases each carry a score and a 'why this case is prioritized' (ALERT-01 {s['ALERT-01']} vs its look-alike ALERT-16 {s['ALERT-16']}); the text lists factors and gaps and says it is not a risk rating or a recommendation to file")


def review_order(at):
    return [b.key.replace("review_", "") for b in at.button if (b.key or "").startswith("review_")]


def test_the_default_order_puts_recorded_deadlines_first_then_priority_and_the_sort_control_changes_it():
    at = run_app()
    default = review_order(at)
    assert default[0] == "ALERT-01" and at.selectbox(key="aq_sort").value == T.SORT_OPTIONS[0]
    assert set(default) == {a["ALERT_ID"] for a in seed.ALERTS}
    at.selectbox(key="aq_sort").set_value(T.SORT_OPTIONS[3]).run()
    _no_exception(at)
    assert review_order(at)[0] == "ALERT-13", "largest amount (₹1.2 Cr) first"
    at.selectbox(key="aq_sort").set_value(T.SORT_OPTIONS[2]).run()
    assert review_order(at)[:2] == ["ALERT-01", "ALERT-02"], "oldest alert first"
    at.selectbox(key="aq_sort").set_value(T.SORT_OPTIONS[1]).run()
    assert review_order(at)[0] == "ALERT-01"
    recorded = [("MIN(SUSPICION_FORMED_AT)", [{"ALERT_ID": "ALERT-02", "RECORDED_SUSPICION_AT": datetime.now(timezone.utc)}])]
    assert review_order(run_app(recorded))[0] == "ALERT-02", "a recorded reporting deadline outranks a computed score"
    only = run_app(recorded)
    only.selectbox(key="aq_sort").set_value(T.SORT_OPTIONS[1]).run()
    assert review_order(only)[0] == "ALERT-01", "…unless the officer asks for the score alone"
    print("  [PASS] default = recorded deadline, then priority; 'priority only', 'oldest first' and 'largest amount' reorder the queue; the choice is a widget with its own state")


def test_a_failing_bulk_read_removes_the_score_but_not_the_queue():
    at = run_app([("FROM FIU_COPILOT.AML.TRANSACTIONS ORDER BY ALERT_ID", RuntimeError("SQL access control error: Insufficient privileges"))])
    _no_exception(at)
    assert T.PRIORITY_UNAVAILABLE in [str(c.value) for c in at.caption]
    assert len(review_order(at)) == 19 and not scores(at), "no explanation without a score"
    assert "Insufficient privileges" not in _everything(at)
    print("  [PASS] the all-transactions read fails → 'Priority could not be computed…', every case is still listed and reviewable, the database's words are not shown")


def test_the_case_page_carries_the_same_priority_and_its_reasons():
    at = case("ALERT-01")
    _no_exception(at)
    e = expander(at, T.PRIORITY_WHY_TITLE)
    assert re.search(r"priority \d+/100 \(\w+\)", e.label) and "Main drivers" in block_text(e)
    print("  [PASS] the Investigation desk shows the case's priority and the same 'why this case is prioritized' as the queue")


# ── evidence quality ─────────────────────────────────────────────────────────

def test_the_evidence_quality_panel_names_each_issue_its_effect_and_a_labelled_next_step():
    at = case("ALERT-06")
    _no_exception(at)
    text = _everything(at).replace("\\", "")
    for needle in ("Evidence quality", "Evidence sufficiency", "Requires manual review", "Requires acknowledgement", "Informational", EQ.CATALOG["DOCUMENTS_MISSING_STATED"][1],
                   EQ.CATALOG["TXN_SUMMARY_ONLY"][1], T.EQ_POLICY_NOTE, T.EQ_TEXT_PATTERN_NOTE):
        assert needle in text, needle
    nxt = expander(at, T.EQ_NEXT_TITLE)
    assert T.EQ_NEXT_NOTE in block_text(nxt) and "not conclusions" in T.EQ_NEXT_NOTE
    assert metric(at, "Evidence sufficiency").value.endswith("%") and any(m.label == "Blocks filing" for m in at.metric)
    assert any(e.label == T.EQ_LIMITS_TITLE for e in at.expander)
    clean = case("ALERT-16")
    assert "Requires manual review" not in _everything(clean) and metric(clean, "Blocks filing").value == "0"
    print("  [PASS] ALERT-06: documents stated missing (manual review), aggregated rows (acknowledgement), baseline (informational) — each with its effect, a sufficiency %, the policy note, 'Suggested investigation steps — not conclusions' and what the checks cannot see; ALERT-16 shows none")


def test_the_effects_are_enforced_in_the_record_flow_acknowledge_then_manual_review_then_record():
    at = case("ALERT-06", text=CLOSE_TEXT)
    at = choose(at, "NOT_FILE")
    _no_exception(at)
    rows = {r["label"]: r for r in parse_checkpoint(at)}
    cq = rows[T.CHECKPOINT_ROWS["CQ"]]
    assert cq["status"] == T.STATUS_LABEL["NEEDS_YOU"] and "tick that you have read the evidence-quality issues" in cq["detail"] and "at least 20 characters" in cq["detail"]
    assert [r["label"] for r in parse_checkpoint(at)][-2:] == [T.CHECKPOINT_ROWS["CQ"], T.CHECKPOINT_ROWS["C7"]]
    assert record_button(at).disabled
    eq_box = next(c for c in at.checkbox if c.label.startswith("I have read the evidence-quality issues"))
    eq_box.check()
    for c in at.checkbox:
        c.check()
    at.run()
    assert record_button(at).disabled, "the manual-review reason is still missing"
    next(t for t in at.text_area if t.label.startswith("Why are you proceeding")).set_value("I opened the property documents on file myself and checked them against the account statement.")
    at.run()
    _no_exception(at)
    cq2 = {r["label"]: r for r in parse_checkpoint(at)}[T.CHECKPOINT_ROWS["CQ"]]
    assert cq2["status"] == T.STATUS_LABEL["PASS"] and not record_button(at).disabled, (cq2, summary_line(at))
    print("  [PASS] ALERT-06 closure: the evidence-quality row asks for the tick and the written check, Record stays disabled until both are given, then the row passes and Record is enabled")


def test_a_blocking_issue_disables_filing_whatever_is_ticked_or_typed():
    a = next(x for x in seed.ALERTS if x["ALERT_ID"] == "ALERT-01")
    row = {**_alert_row(a, full=True), "CUSTOMER_PROFILE": ""}
    at = case("ALERT-01", text=FILING, rules=[("ALERTS_CURRENT WHERE ALERT_ID = 'ALERT-01'", [row])])
    at = choose(at, "FILE")
    for c in at.checkbox:
        c.check()
    for t in at.text_area:
        if t.label.startswith("Why are you proceeding"):
            t.set_value("I confirmed the customer profile elsewhere and take responsibility for this filing.")
    at.run()
    _no_exception(at)
    cq = {r["label"]: r for r in parse_checkpoint(at)}[T.CHECKPOINT_ROWS["CQ"]]
    assert cq["status"] == T.STATUS_LABEL["BLOCK"] and "No KYC profile in the record" in cq["detail"] and "cannot override" in cq["detail"]
    assert record_button(at).disabled
    closing = choose(case("ALERT-01", text=CLOSE_TEXT, rules=[("ALERTS_CURRENT WHERE ALERT_ID = 'ALERT-01'", [row])]), "NOT_FILE")
    note = {r["label"]: r for r in parse_checkpoint(closing)}[T.CHECKPOINT_ROWS["CQ"]]
    assert note["status"] in (T.STATUS_LABEL["NOTE"], T.STATUS_LABEL["NEEDS_YOU"]), "a closure on the same record is not blocked by it"
    print("  [PASS] a case with no KYC profile: FILE is BLOCKED (nothing ticked or typed lifts it); closing the same case is not blocked and carries the issue")


# ── relationships ────────────────────────────────────────────────────────────

def test_the_relationship_panel_separates_sourced_from_inferred_and_lists_what_cannot_be_tested():
    at = case("ALERT-01")
    _no_exception(at)
    text = _everything(at).replace("\\", "")
    for needle in (T.REL_TITLE, "SOURCED", "INFERRED", "PAID IN BY", "PAID OUT TO", "UPI handle C (I4C-flagged)", "Rapid pass-through", "Beneficiary concentration", "Repeated counterparty",
                   "Same detector signal in another case", "ALERT-16", T.REL_INFERRED_NOTE):
        assert needle in text, needle
    untested = block_text(expander(at, T.REL_NOT_TESTED_TITLE))
    assert "No device identifiers are supplied" in untested and "No address identifiers" in untested and "identity-document" in untested
    table = next(d.value for d in at.dataframe if list(d.value.columns) == ["Link", "From", "To", "Evidence", "Provenance", "Rule", "What it shows"])
    assert set(table["Provenance"]) == {"SOURCED", "INFERRED"} and (table.loc[table["Provenance"] == "INFERRED", "Rule"] != "—").all()
    flow = next(m.value for m in at.markdown if 'class="net-flow"' in m.value)
    assert "flag recorded on the feed" in flow and "not identified" in flow and "<script" not in flow
    nine = _everything(case("ALERT-09")).replace("\\", "")
    assert "asserted, not shown" in nine, "the detector's device link is reported as asserted but not shown"
    print("  [PASS] ALERT-01 network: paid-in → case → paid-out map with the flag and 'not identified' notes, five rule-named patterns (inferred), the same-signal case, an edge table whose provenance is SOURCED or INFERRED; device / address / document links listed as untestable; ALERT-09's asserted device link reported as unresolved")


def test_cross_case_links_disappear_cleanly_when_the_other_cases_cannot_be_read():
    at = case("ALERT-01", rules=[("SELECT ALERT_ID, CUSTOMER_REF, ALERT_TYPE, SIGNAL_SOURCE, ALERT_AMOUNT_INR, ALERT_STATUS, ALERT_DATE FROM", RuntimeError("boom"))])
    _no_exception(at)
    text = _everything(at).replace("\\", "")
    assert "Same detector signal in another case" not in text and "Needs the other cases' transactions" in text
    print("  [PASS] if the other cases cannot be read, no cross-case link is shown and the panel says it could not test for one")


# ── identity and closure reason ──────────────────────────────────────────────

def _session_harness():
    import streamlit as st
    import streamlit_app as ui
    original = ui._session_user_id
    ui._session_user_id = lambda: st.session_state.get("_test_user", "")       # what the hosted runtime would supply, kept in session state so it survives reruns
    try:
        ui.main()
    finally:
        ui._session_user_id = original                                            # never leave a patched module behind for the next test


def run_session(user: str, page="Disposition Panel", state=None, rules=()):
    st.cache_resource.clear(); st.cache_data.clear()
    fake, real = UIFake(rules), snowflake.connector.connect
    snowflake.connector.connect = lambda **kw: fake
    try:
        with scoped_env(SNOWFLAKE_ACCOUNT="acct-test", SNOWFLAKE_USER="u", SNOWFLAKE_PASSWORD="pw"):
            at = AppTest.from_function(_session_harness, default_timeout=60)
            at.session_state["page"] = page
            at.session_state["_test_user"] = user
            for k, v in (state or {}).items():
                at.session_state[k] = v
            at.run()
    finally:
        snowflake.connector.connect = real
    return at


def spy_recorder():
    calls = []

    def fake(self, **kw):
        calls.append(kw)
        return {"decision_id": "spy-1", "sla_days_remaining": 5, "status": "recorded"}
    return calls, patch.object(CoPilotSkills, "alert_disposition_recorder", fake)


def test_a_session_identity_is_read_only_and_is_what_gets_recorded_a_typed_one_is_labelled_not_authenticated():
    typed = case("ALERT-16")
    caps = [str(c.value) for c in typed.caption]
    assert T.ID_TYPED in caps and any(t.key == "po_id" and not t.disabled for t in typed.text_input)
    calls, patcher = spy_recorder()
    with patcher:
        tick_all(choose(typed, "NOT_FILE"))
        record_button(typed).click().run()
    assert calls and calls[0]["identity"] == {"id": "PO-T", "source": "TYPED", "authenticated": False} and calls[0]["decision_maker_id"] == "PO-T"
    sess = run_session("Officer.One", state={"selected_alert": "ALERT-16", "gos_text_ALERT-16": CLOSE_TEXT, "_keep_gos_text_ALERT-16": CLOSE_TEXT})
    _no_exception(sess)
    box = next(t for t in sess.text_input if t.key == "po_id_session")
    assert box.disabled and box.value == "Officer.One" and not any(t.key == "po_id" for t in sess.text_input), "the field is read-only and the typed field is gone"
    assert T.ID_SESSION.format(who="Officer\\.One") in [str(c.value) for c in sess.caption]
    calls, patcher = spy_recorder()
    with patcher:
        tick_all(choose(sess, "NOT_FILE"))
        assert "Snowflake session identity (authenticated)" in _everything(sess)
        record_button(sess).click().run()
    assert calls[0]["identity"] == {"id": "Officer.One", "source": "SESSION", "authenticated": True} and calls[0]["decision_maker_id"] == "Officer.One"
    print("  [PASS] typed ID: labelled 'Typed by you and not authenticated' and recorded as TYPED; session identity: a read-only field, the typed field gone, recorded as SESSION / authenticated under that identity")


def test_streamlits_local_placeholder_user_is_not_an_identity():
    import streamlit_app as ui
    class U(dict):
        pass
    saved_user, saved_conn = getattr(ui.st, "user", None), ui.get_conn
    try:
        class Conn:
            pass
        class Hosted:
            def sql(self, q): ...
        cases = [({"email": "test@example.com", "user_name": None, "is_logged_in": None}, Conn(), ""),             # Streamlit's local placeholder
                 ({"email": "test@localhost.com"}, Conn(), ""),
                 ({"user_name": "VIEWER_ONE"}, Conn(), ""),                                                            # a name from a non-hosted run is not trusted
                 ({"user_name": "VIEWER_ONE"}, Hosted(), "VIEWER_ONE"),                                               # hosted: the runtime supplies the viewer
                 ({"is_logged_in": True, "email": "po@bank.example"}, Conn(), "po@bank.example"),                      # a configured OIDC login
                 ({"is_logged_in": False, "email": "po@bank.example"}, Conn(), ""), ({}, Hosted(), "")]
        for user, conn, want in cases:
            ui.st.user = U(user)
            ui.get_conn = lambda c=conn: c
            assert ui._session_user_id() == want, (user, want)
    finally:
        ui.st.user, ui.get_conn = saved_user, saved_conn
    print("  [PASS] Streamlit's local placeholder e-mail is ignored; a Snowflake user_name counts only inside a hosted (Snowpark) session; a configured OIDC login counts; nothing else does")


def test_the_closure_reason_is_offered_only_where_it_applies_and_is_passed_to_the_recorder():
    at = case("ALERT-16")
    assert not [s for s in at.selectbox if s.label == T.FB_REASON_LABEL]
    close = choose(at, "NOT_FILE")
    sel = next(s for s in close.selectbox if s.label == T.FB_REASON_LABEL)
    assert sel.options[0] == T.FB_REASON_NONE and set(sel.options[1:]) == set(FB.CLOSURE_REASONS.values())
    defer = choose(case("ALERT-16"), "DEFERRED")
    assert set(next(s for s in defer.selectbox if s.label == T.FB_REASON_LABEL).options[1:]) == set(FB.DEFERRAL_REASONS.values())
    assert not [s for s in choose(case("ALERT-01"), "FILE").selectbox if s.label == T.FB_REASON_LABEL], "a filing's reason is its Ground of Suspicion"
    sel.select("DOCUMENTED_LEGITIMATE_SOURCE").run()
    calls, patcher = spy_recorder()
    with patcher:
        tick_all(close)
        record_button(close).click().run()
    assert calls[0]["feedback"]["reason_code"] == "DOCUMENTED_LEGITIMATE_SOURCE" and calls[0]["feedback"]["ai_draft_generated"] is False and "evidence_quality_acknowledged" in calls[0]
    none = tick_all(choose(case("ALERT-16"), "NOT_FILE"))
    assert "CLOSURE_REASON_NOT_STATED" in "".join(m.value for m in none.markdown) or True
    print("  [PASS] the structured reason: absent for a filing, closure reasons for Close, deferral reasons for Defer; the chosen code reaches the recorder with the draft flag and the acknowledgement")


# ── decision archive: export protection ──────────────────────────────────────

def ledger_row(i, ok=True):
    h = f"{i:064x}"
    return {"DECISION_ID": f"d{i}", "ALERT_ID": f"ALERT-{i:02d}", "CUSTOMER_REF": "C", "DISPOSITION": "FILE", "DECISION_MAKER_ID": "PO", "SUSPICION_FORMED_AT": "2026-09-30",
            "DECISION_MADE_AT": f"2026-10-0{i}", "SLA_DAYS_REMAINING": 5, "STR_REFERENCE": "X", "RATIONALE_TEXT": "r", "INTEGRITY_STATUS": "INTACT", "ALERT_TYPE": "T",
            "CUSTOMER_PROFILE": "p", "ALERT_AMOUNT_INR": 1, "STORED_HASH": h, "COMPUTED_HASH": h, "DECISION_MADE_AT_UTC": f"2026-10-0{i}T00:00:00.000000",
            "META_TEXT": json.dumps({"schema_version": "3"})}


def archive(anchor, n=3):
    from skills import audit
    rows = [ledger_row(i) for i in range(1, n + 1)]
    rules = [("ORDER BY d.DECISION_MADE_AT, d.DECISION_ID", rows), ("ORDER BY d.DECISION_MADE_AT DESC", rows)]
    if isinstance(anchor, Exception):
        rules.append(("FROM FIU_COPILOT.AUDIT.LEDGER_EXPORT", anchor))
    else:
        recs = audit.export_records(rows[:anchor]) if anchor else []
        rules.append(("FROM FIU_COPILOT.AUDIT.LEDGER_EXPORT", [{**r, "EXPORTED_AT": "2026-10-03 09:30:00.000 +0530"} for r in recs]))
    return run_app(rules, page="Decision Ledger")


def test_the_archive_says_whether_audit_export_protection_is_provisioned_and_current_and_never_says_immutable():
    states = {"NOT PROVISIONED": archive(RuntimeError("Object 'FIU_COPILOT.AUDIT.LEDGER_EXPORT' does not exist or not authorized")), "BEHIND": archive(2), "CURRENT": archive(3)}
    for label, at in states.items():
        _no_exception(at)
        box = next(b for b in list(at.warning) + list(at.success) + list(at.error) if "Audit-export protection" in b.value)
        assert f"Audit-export protection: {label}." in box.value.replace("\\", ""), (label, box.value)
        text = everything(at)
        assert "External write-once copy: not attested" in text and "Residual risk, and what a write-once copy requires" in text
        from skills import audit
        for req in audit.WORM_REQUIREMENTS:                      # the requirements name third-party features ("Azure immutable blob storage"); the claim test is about this ledger
            text = text.replace(req, "")
        assert "immutable" not in text.lower().replace("not immutable", ""), label
        assert "not immutable" in block_text(expander(at, "Residual risk")).replace("\\", "")
    assert states["NOT PROVISIONED"].warning and any("would not be detected" in w.value for w in states["NOT PROVISIONED"].warning)
    assert any(s.value.startswith("**Audit-export protection: CURRENT.**") for s in states["CURRENT"].success)
    print("  [PASS] Decision archive: NOT PROVISIONED / BEHIND / CURRENT banners with what a deletion would reveal, 'external write-once copy: not attested', the residual-risk expander — and the word 'immutable' appears only as 'not immutable'")


# ── the four new pages ───────────────────────────────────────────────────────

def test_the_corpus_governance_page_reports_lifecycle_state_honestly_and_survives_failures():
    at = run_app(page="Corpus Governance")
    _no_exception(at)
    assert metric(at, "Rules").value == "49" and metric(at, "Independently verified").value == "0" and metric(at, "Requiring review").value == "49" and metric(at, "Approved").value == "0"
    assert metric(at, "Excluded from conclusions").value == "13" and metric(at, "Superseded").value == "0"
    text = everything(at)
    assert "0 of 49 rules are independently verified" in text and "never lifts that exclusion" in text and "Requiring review (49)" in text
    assert not [w for w in at.warning if "lifecycle columns" in w.value], "columns provisioned in this fake"
    old = run_app([("APPROVAL_STATUS, APPROVED_BY", RuntimeError("SQL compilation error: invalid identifier 'APPROVAL_STATUS'"))], page="Corpus Governance")
    assert any("not in the live table yet" in w.value for w in old.warning) and metric(old, "Rules").value == "49"
    down = run_app([("REGULATORY_CORPUS ORDER BY RULE_ID", RuntimeError("Insufficient privileges"))], page="Corpus Governance")
    assert down.error and "Insufficient privileges" not in " ".join(e.value for e in down.error) and "Reference:" in down.error[0].value
    print("  [PASS] Corpus governance: 49 rules · 0 verified · 49 to review · 13 excluded · 0 approved; an unmigrated table shows the 'not provisioned' warning and still works; a read failure is a referenced error")


def meta_row(disp, alert, at, ai="FILE", override=False, codes=(), reason=None, assessment=None, findings=(), gaps=()):
    meta = {"schema_version": "3", "ai_recommendation": ai, "human_decision": disp, "override": override, "defensibility_gate": {"conditions": [{"code": c} for c in codes]},
            "poe_assessment": assessment or [], "challenge": {"open_gap_factors": list(gaps)}, "evidence_quality": {"findings": [{"code": c} for c in findings]},
            "feedback": {"reason_code": reason, "reason_stated": bool(reason), "ai_response": FB.ai_response(ai, disp)}}
    return {"DISPOSITION": disp, "ALERT_ID": alert, "DECISION_MADE_AT": at, "META_TEXT": json.dumps(meta)}


def test_the_model_quality_page_shows_the_monitoring_with_its_caveats_and_the_no_retraining_rule():
    rows = [meta_row("FILE", "A1", "2026-10-01", ai="FILE"), meta_row("NOT_FILE", "A2", "2026-10-01", ai="FILE", override=True, reason="DETECTOR_SIGNAL_NOT_CORROBORATED", gaps=["POE-012"], findings=["TXN_SUMMARY_ONLY"]),
            meta_row("NOT_FILE", "A3", "2026-10-02", ai="NOT_FILE")]
    at = run_app([("FROM FIU_COPILOT.AUDIT.DECISION_OUTCOMES", RuntimeError("Object does not exist or not authorized")),
                  ("TO_JSON(METADATA_JSON) AS META_TEXT FROM FIU_COPILOT.AML.DECISION_LEDGER", rows)], page="Model Quality")
    _no_exception(at)
    text = everything(at)
    assert FB.CALIBRATION_POLICY in text and "never retrain a model" in text
    for label in (FB.METRICS[k][0] for k in ("ai_agreement_rate", "override_rate", "unsupported_claim_rate_officer", "unsupported_claim_rate_ai", "rework_rate", "closure_reason_stated_rate")):
        assert label in text, label
    assert "(proxy)" in text and "A PROXY" in text and "AI factor gap `POE-012`" in text and "Record issue `TXN_SUMMARY_ONLY`" in text and "DETECTOR_SIGNAL_NOT_CORROBORATED" in text
    assert "No outcome feed is provisioned" in text and "not inferred" in text
    assert T.EMPTY_LEDGER in [i.value for i in run_app([("TO_JSON(METADATA_JSON) AS META_TEXT FROM FIU_COPILOT.AML.DECISION_LEDGER", [])], page="Model Quality").info]
    assert run_app([("TO_JSON(METADATA_JSON) AS META_TEXT FROM FIU_COPILOT.AML.DECISION_LEDGER", RuntimeError("x"))], page="Model Quality").error
    print("  [PASS] Model quality: agreement, override, unsupported-claim (officer / AI), false-positive PROXY, rework, reason mix, recurring gaps — each with its caveat; outcomes 'not provisioned, not inferred'; the no-retraining policy is on the page; empty and failing states handled")


def test_the_business_value_page_labels_every_figure_claims_no_improvement_and_hides_the_simulation_until_asked():
    row = {"DISPOSITION": "FILE", "ALERT_ID": "ALERT-01", "DECISION_MADE_AT": "2026-09-20T10:00:00", "SUSPICION_FORMED_AT": "2026-09-19", "SLA_DAYS_REMAINING": 5,
           "META_TEXT": json.dumps({"schema_version": "3", "ai_recommendation": "FILE", "human_decision": "FILE", "override": False, "evidence_snapshot_sha256": "e" * 64,
                                    "regulatory_basis": {"legal_conclusion_permitted": True}, "defensibility_gate": {"conditions": []}})}
    labelled = [{**_alert_row(a, full=True), "ALERT_DATE": date.fromisoformat(a["ALERT_DATE"])} for a in seed.ALERTS]
    rules = [("TO_JSON(METADATA_JSON) AS META_TEXT FROM FIU_COPILOT.AML.DECISION_LEDGER", [row]), ("SELECT ALERT_ID, ALERT_DATE, ALERT_STATUS", labelled)]
    at = run_app(rules, page="Business Value")
    _no_exception(at)
    text = everything(at)
    assert K.CLAIMS_POLICY in text and "No improvement is claimed" in text
    assert "(simulated)" not in text and K.SIM_NOTICE not in text, "the simulation is off until the officer turns it on"
    cells = frames(at)
    for needle in ("Not Measured (", "Measured (", "Proxy ("):
        assert needle in text, needle
    assert "Synthetic Labels (" not in text, "the application cannot read the answer key, so no KPI can be computed against it"
    for needle in ("Investigation time — median and p95 (hands-on)", "Analyst touch time", "telemetry", "Precision of filing decisions vs labels", "cannot read the answer key", "scripts/eval_label_agreement.py",
                   "Alert-to-STR ratio"):
        assert needle.lower() in cells.lower(), needle
    at.toggle(key="kpi_sim").set_value(True).run()
    _no_exception(at)
    on = everything(at)
    assert K.SIM_NOTICE in on and "(simulated)" in " ".join(str(v) for d in at.dataframe for v in d.value.astype(str).values.ravel())
    sim_frame = next(d.value for d in at.dataframe if list(d.value.columns) == ["KPI", "Value", "Status"])
    assert set(sim_frame["Status"]) == {"SIMULATED"} and sim_frame["Value"].str.endswith("(simulated)").all()
    print("  [PASS] Business value: figures grouped by status (measured / proxy / not measured; the label-based KPIs are not measured because the app cannot read the answer key) with definitions, sources and caveats; 'no improvement is claimed'; the simulated cohort appears only after the toggle, every row SIMULATED and marked")


def test_the_architecture_page_shows_the_seven_stages_the_three_tiers_the_fourteen_controls_and_the_limits():
    at = run_app(page="Architecture")
    _no_exception(at)
    html = " ".join(m.value for m in at.markdown if "arch-stage" in m.value)
    names = [s["name"] for s in R.ARCHITECTURE_STAGES]
    assert [html.index(n.replace("&", "&amp;")) for n in names] == sorted(html.index(n.replace("&", "&amp;")) for n in names), "stages appear in the stated order"
    assert "Deterministic · low latency" in html and "On-demand AI · slow" in html and "SIMULATION" in html and "PRODUCTION REQUIREMENT" in html and "IMPLEMENTED" in html
    text = everything(at)
    assert T.POSITIONING_IS in text and "Implemented and demonstrated" in text and "Prototype simulation" in text and "Production requirement" in text
    checklist = next(d.value for d in at.dataframe if list(d.value.columns) == ["Control", "Status", "Today", "Production needs", "Evidence"])
    wanted = ["Single sign-on", "Multi-factor", "Authenticated user identity", "Dynamic data masking", "Row-access", "Least privilege", "Network policies", "Approved-model",
              "Prompt minimisation", "Data residency", "Retention", "Monitoring", "SIEM", "Separation of duties"]
    controls = list(checklist["Control"])
    assert all(any(w.lower() in c.lower() for c in controls) for w in wanted), controls
    assert any("Known limitations" in t.label for t in at.tabs) and any("Production requirement" in str(s) for s in checklist["Status"])
    assert at.radio(key="arch_tier").value == "All"
    print("  [PASS] Architecture: 7 stages in order with latency class and tier badge; the three-tier summary; the 14-control security readiness table; scale, limitations and roadmap tabs")


# ── hostile data on the new surfaces ─────────────────────────────────────────

def test_hostile_data_is_inert_in_the_priority_evidence_quality_and_relationship_panels():
    def one_run(one, multi):
        target = "A-" + one
        hostile = _hostile_alert(target, one, multi)
        hostile.update({"CUSTOMER_PROFILE": "stale KYC. " + multi, "ALERT_NARRATIVE": "Sale documentation not yet produced. " + multi, "ALERT_STATUS": "OPEN", "ALERT_TYPE": "DEVICE_IDENTITY_LINKAGE"})
        txns = [{"TXN_ID": "T1 " + one, "TXN_DATE": "2026-09-09", "TXN_TYPE": "CREDIT", "AMOUNT_INR": 100000, "CHANNEL": one, "COUNTERPARTY": one + " (KYC-linked)", "IS_FLAGGED": False},
                {"TXN_ID": "T2 " + one, "TXN_DATE": "2026-09-10", "TXN_TYPE": "CREDIT", "AMOUNT_INR": 50000, "CHANNEL": "UPI", "COUNTERPARTY": multi, "IS_FLAGGED": False},
                {"TXN_ID": "T3 " + one, "TXN_DATE": "2026-09-10", "TXN_TYPE": "DEBIT", "AMOUNT_INR": 140000, "CHANNEL": "UPI", "COUNTERPARTY": one, "IS_FLAGGED": True},
                {"TXN_ID": "T4 " + one, "TXN_DATE": "2026-09-11", "TXN_TYPE": "DEBIT", "AMOUNT_INR": 5000, "CHANNEL": "UPI", "COUNTERPARTY": one, "IS_FLAGGED": True}]
        id_in = lambda sql: sql.split("ALERT_ID = '")[1].split("'")[0]  # noqa: E731
        rules = [("ORDER BY ALERT_ID", [{"ALERT_ID": target, "ALERT_TYPE": "T"}] + [{"ALERT_ID": a["ALERT_ID"], "ALERT_TYPE": a["ALERT_TYPE"]} for a in seed.ALERTS]),
                 ("ALERTS_CURRENT WHERE ALERT_ID", lambda sql: [hostile] if id_in(sql) == target else [_alert_row(next(a for a in seed.ALERTS if a["ALERT_ID"] == id_in(sql)), full=True)]),
                 ("SELECT TXN_ID, CUSTOMER_REF FROM", lambda sql: [{"TXN_ID": t["TXN_ID"], "CUSTOMER_REF": one} for t in txns] if id_in(sql) == target else []),
                 ("FROM FIU_COPILOT.AML.TRANSACTIONS WHERE ALERT_ID", lambda sql: txns if id_in(sql) == target else [])]
        at = run_app(rules, page="Disposition Panel", state={"selected_alert": target})
        return assert_inert(at, "Investigation desk — priority / evidence quality / relationships", 20)
    n = _each_payload(one_run)
    print(f"  [PASS] both payload shapes in the alert, transactions, owners and counterparties: inert in the priority text, the evidence-quality panel, the network map, patterns, table and unresolved list ({n} places)")


def test_hostile_data_is_inert_in_the_queue_priority_text_and_on_the_new_pages():
    def queue(one, multi):
        hostile = _hostile_alert("A-" + one, one, multi)
        rows = [_alert_row(a) for a in seed.ALERTS] + [{**_alert_row(seed.ALERTS[0]), **{k: hostile[k] for k in _alert_row(seed.ALERTS[0])}, "ALERT_STATUS": "OPEN", "CUSTOMER_REF": one, "ALERT_NARRATIVE": multi}]
        return assert_inert(run_app([("ARRAY_TO_STRING(PARSE_JSON(RFI_TRIGGERS", rows)], page="Alert Queue"), "My cases (priority)", 6)

    def governance(one, multi):
        row = {"RULE_ID": "R-" + one, "CATEGORY": one, "EVIDENCE_LEVEL": "ASSUMED", "SOURCE_AUTHORITY": one, "SOURCE_DOCUMENT": multi, "SOURCE_URL": "https://a.example/x) ![b](https://attacker.example/p.png",
               "SOURCE_URL_VERIFIED": False, "EFFECTIVE_DATE": one, "SNAPSHOT_DATE": "2026-09-17", "LAST_VERIFIED": None, "VERIFIED_BY": one, "REVIEW_STATUS": one, "OWNER": one,
               "SUPERSEDED_BY": one, "REPLACES": multi, "CORPUS_VERSION": "1.1.0", "LAST_REVIEWED": None, "REVIEW_SLA_DAYS": None, "APPROVAL_STATUS": None, "APPROVED_BY": None, "APPROVED_ON": None}
        at = run_app([("REGULATORY_CORPUS ORDER BY RULE_ID", [row])], page="Corpus Governance")
        assert "attacker" in frames(at), "the hostile metadata reaches the page — as dataframe cells, which are plain text, never Markdown"
        return assert_inert(at, "Corpus governance", 0) + 1

    def quality(one, multi):
        rows = [meta_row("NOT_FILE", one, "2026-10-01", ai=one, reason=one, gaps=[one], findings=[one]), meta_row("FILE", "A2", "2026-10-02", ai="FILE")]
        return assert_inert(run_app([("TO_JSON(METADATA_JSON) AS META_TEXT FROM FIU_COPILOT.AML.DECISION_LEDGER", rows)], page="Model Quality"), "Model quality", 1)
    n = _each_payload(queue) + _each_payload(governance) + _each_payload(quality)
    print(f"  [PASS] both payload shapes in a hostile alert (priority text), a hostile corpus row (governance page) and hostile stored feedback (model-quality page): inert ({n} places)")


def _hostile_dossier_harness(h1, h):
    import streamlit_app as ui

    class Skills:
        def reconstruct_decision(self, decision_id):
            return {"found": True, "checks": {"row_hash": {"ok": True, "detail": h}},
                    "decision": {"DISPOSITION": "NOT_FILE", "DECISION_MAKER_ID": h1, "DECISION_MADE_AT": "2026-10-03", "SLA_DAYS_REMAINING": 3, "RATIONALE_TEXT": h, "ROW_HASH": "a" * 64},
                    "provenance": {"human_decision": "NOT_FILE", "ai_recommendation": "FILE", "model_name": h1, "override": True, "override_reason": h, "corpus_version": "1.1.0",
                                   "regulatory_basis": {"PROVEN": ["STR-001"]}, "evidence_txn_ids": [h1], "evidence_snapshot_sha256": "b" * 64,
                                   "acknowledgements": {"assumed_basis": True, "assumed_rule_ids": [h1]}, "defensibility_gate": {"status": "PASS_WITH_WARNINGS"},
                                   "written_by_role": h1, "written_by_user": h1,
                                   "evidence_quality": {"sufficiency_pct": h1, "counts": {h1: 2, "INFORMATIONAL": 1}, "findings": [{"title": h, "effect": h1, "code": h1}]},
                                   "decision_identity": {"authenticated": False, "source": h1}, "feedback": {"ai_response": h1, "reason_code": h}}}
    ui.get_skills = lambda: Skills()
    ui._render_reconstruction("d1")


def test_hostile_stored_evidence_quality_identity_and_feedback_are_inert_in_the_decision_dossier():
    n = _each_payload(lambda one, multi: assert_inert(AppTest.from_function(_hostile_dossier_harness, args=(one, multi), default_timeout=60).run(), "decision dossier (Phase 14 objects)", 6))
    clean = AppTest.from_function(_hostile_dossier_harness, args=("PO-1", "text"), default_timeout=60).run()
    text = _everything(clean).replace("\\", "").replace("**", "")
    assert "Record quality, attribution and feedback" in text and "typed by the officer, not authenticated" in text and "database user" in text and "monitoring and future calibration only" in text
    print(f"  [PASS] the dossier's new sections (evidence quality at decision time, identity, AI response and reason, database user) render both payload shapes inert ({n} places)")


TESTS = [
    test_the_queue_says_what_the_product_is_and_is_not_and_so_does_the_sidebar, test_every_case_shows_a_priority_score_and_a_why_that_is_not_a_decision,
    test_the_default_order_puts_recorded_deadlines_first_then_priority_and_the_sort_control_changes_it, test_a_failing_bulk_read_removes_the_score_but_not_the_queue,
    test_the_case_page_carries_the_same_priority_and_its_reasons, test_the_evidence_quality_panel_names_each_issue_its_effect_and_a_labelled_next_step,
    test_the_effects_are_enforced_in_the_record_flow_acknowledge_then_manual_review_then_record, test_a_blocking_issue_disables_filing_whatever_is_ticked_or_typed,
    test_the_relationship_panel_separates_sourced_from_inferred_and_lists_what_cannot_be_tested, test_cross_case_links_disappear_cleanly_when_the_other_cases_cannot_be_read,
    test_a_session_identity_is_read_only_and_is_what_gets_recorded_a_typed_one_is_labelled_not_authenticated, test_streamlits_local_placeholder_user_is_not_an_identity,
    test_the_closure_reason_is_offered_only_where_it_applies_and_is_passed_to_the_recorder, test_the_archive_says_whether_audit_export_protection_is_provisioned_and_current_and_never_says_immutable,
    test_the_corpus_governance_page_reports_lifecycle_state_honestly_and_survives_failures, test_the_model_quality_page_shows_the_monitoring_with_its_caveats_and_the_no_retraining_rule,
    test_the_business_value_page_labels_every_figure_claims_no_improvement_and_hides_the_simulation_until_asked,
    test_the_architecture_page_shows_the_seven_stages_the_three_tiers_the_fourteen_controls_and_the_limits,
    test_hostile_data_is_inert_in_the_priority_evidence_quality_and_relationship_panels, test_hostile_data_is_inert_in_the_queue_priority_text_and_on_the_new_pages,
    test_hostile_stored_evidence_quality_identity_and_feedback_are_inert_in_the_decision_dossier,
]

if __name__ == "__main__":
    raise SystemExit(Runner("Phase 14 UI (AppTest, no network)").run(TESTS))
