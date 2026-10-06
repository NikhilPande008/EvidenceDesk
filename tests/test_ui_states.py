"""
UI failure / empty / warning states (finding #7) — Streamlit AppTest against a scripted fake database.

Proves the app renders an explicit, honest state (never a stack trace, never a silent blank) when:
  database is down · transactions missing/unreadable · AI assessment output is invalid · Cortex Search is
  unavailable (keyword fallback) · Cortex Analyst is unavailable · ledger empty / tampered / legacy · corpus empty.
Also: ASSUMED warning, superseded qualification, FILE disabled unless the deterministic gate passes.

Offline. Usage:  python3 tests/test_ui_states.py     (or pytest)
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date

from _helpers import FakeConn, ROOT, Runner

sys.path.insert(0, str(ROOT / "scripts"))
import setup_alerts as seed  # noqa: E402
import snowflake.connector  # noqa: E402
import streamlit as st  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

from skills import po_copy as T  # noqa: E402


def _alert_row(a, full=False):
    row = {"ALERT_ID": a["ALERT_ID"], "ALERT_TYPE": a["ALERT_TYPE"], "SIGNAL_SOURCE": a["SIGNAL_SOURCE"],
           "ACCOUNT_TYPE": a["ACCOUNT_TYPE"], "CUSTOMER_PROFILE": a["CUSTOMER_PROFILE"], "ALERT_AMOUNT_INR": a["ALERT_AMOUNT_INR"],
           "ALERT_STATUS": "OPEN", "ALERT_DATE": date.fromisoformat(a["ALERT_DATE"]), "LAST_DISPOSITION": None,
           "CUSTOMER_REF": a["CUSTOMER_REF"], "ALERT_NARRATIVE": a["ALERT_NARRATIVE"], "LAST_DECISION_AT": None,
           "RFIS": ", ".join(a["RFI_TRIGGERS"])}
    if full:
        row.update({"CUSTOMER_REF": a["CUSTOMER_REF"], "ALERT_NARRATIVE": a["ALERT_NARRATIVE"], "RFI_TRIGGERS": json.dumps(a["RFI_TRIGGERS"]),
                    "RULES_CITED": json.dumps(a["RULES_CITED"]), "POE_FACTORS": json.dumps(a["POE_FACTORS"])})      # no answer key: ALERTS_CURRENT does not expose it
    return row


def _txn_rows(aid):
    return [{"TXN_ID": t["TXN_ID"], "TXN_DATE": t["TXN_DATE"], "TXN_TYPE": t["TXN_TYPE"], "AMOUNT_INR": t["AMOUNT_INR"], "CHANNEL": t["CHANNEL"],
             "COUNTERPARTY": t["COUNTERPARTY"], "IS_FLAGGED": t["IS_FLAGGED"]} for t in seed.TRANSACTIONS if t["ALERT_ID"] == aid]


class UIFake(FakeConn):
    """Scripted database: `rules` = [(needle, rows | Exception | callable)], first match wins."""

    def __init__(self, rules=()):
        super().__init__()
        self.rules = list(rules)

    def respond(self, sql):
        for needle, value in self.rules:
            if needle in sql:
                if isinstance(value, Exception):
                    raise value
                return value(sql) if callable(value) else value
        if "ALERTS_CURRENT WHERE ALERT_ID" in sql:
            aid = sql.split("ALERT_ID = '")[1].split("'")[0]
            return [_alert_row(next(a for a in seed.ALERTS if a["ALERT_ID"] == aid), full=True)]
        if "FROM FIU_COPILOT.AML.ALERTS_CURRENT" in sql and "ORDER BY ALERT_ID" in sql:
            return [{"ALERT_ID": a["ALERT_ID"], "ALERT_TYPE": a["ALERT_TYPE"]} for a in seed.ALERTS]
        if "FROM FIU_COPILOT.AML.ALERTS_CURRENT" in sql:
            return [_alert_row(a) for a in seed.ALERTS]
        if "SELECT TXN_ID, CUSTOMER_REF FROM FIU_COPILOT.AML.TRANSACTIONS WHERE ALERT_ID" in sql:          # the owner map (Phase 14)
            aid = sql.split("ALERT_ID = '")[1].split("'")[0]
            return [{"TXN_ID": t["TXN_ID"], "CUSTOMER_REF": t["CUSTOMER_REF"]} for t in seed.TRANSACTIONS if t["ALERT_ID"] == aid]
        if "FROM FIU_COPILOT.AML.TRANSACTIONS ORDER BY ALERT_ID" in sql:                                    # every alert's rows in one read (queue priority, cross-case links)
            return [{"ALERT_ID": t["ALERT_ID"], **row, "CUSTOMER_REF": t["CUSTOMER_REF"]} for t in seed.TRANSACTIONS for row in _txn_rows(t["ALERT_ID"]) if row["TXN_ID"] == t["TXN_ID"]]
        if "FROM FIU_COPILOT.AML.TRANSACTIONS WHERE ALERT_ID" in sql:
            return _txn_rows(sql.split("ALERT_ID = '")[1].split("'")[0])
        if "FROM FIU_COPILOT.AML.REGULATORY_CORPUS ORDER BY RULE_ID" in sql:                                # rule metadata for the governance page (YAML-derived)
            return _lifecycle_rows(full="APPROVAL_STATUS" in sql)
        return super().respond(sql)


def _lifecycle_rows(full: bool):
    import glob
    import yaml
    out = []
    for f in sorted(glob.glob(str(ROOT / "domain/corpus/rules/*.yaml"))):
        for r in yaml.safe_load(open(f))["rules"]:
            ps = r.get("primary_source") or {}
            row = {"RULE_ID": r["id"], "CATEGORY": r.get("category"), "EVIDENCE_LEVEL": r["evidence_level"], "SOURCE_AUTHORITY": r.get("source_authority"),
                   "SOURCE_DOCUMENT": ps.get("document"), "SOURCE_URL": ps.get("url"), "SOURCE_URL_VERIFIED": bool(ps.get("url_verified")),
                   "EFFECTIVE_DATE": r.get("effective_date"), "SNAPSHOT_DATE": r.get("snapshot_date"), "LAST_VERIFIED": r.get("last_verified"),
                   "VERIFIED_BY": r.get("verified_by"), "REVIEW_STATUS": r.get("review_status"), "OWNER": r.get("owner"), "SUPERSEDED_BY": r.get("superseded_by"),
                   "REPLACES": r.get("replaces"), "CORPUS_VERSION": r.get("corpus_version")}
            if full:
                row.update({"LAST_REVIEWED": None, "REVIEW_SLA_DAYS": None, "APPROVAL_STATUS": None, "APPROVED_BY": None, "APPROVED_ON": None})
            out.append(row)
    return out


def run_app(rules=(), page="Alert Queue", state=None):
    st.cache_resource.clear(); st.cache_data.clear()
    fake = UIFake(rules)
    real = snowflake.connector.connect
    snowflake.connector.connect = lambda **kw: fake
    from _helpers import scoped_env
    try:
        with scoped_env(SNOWFLAKE_ACCOUNT="acct-test", SNOWFLAKE_USER="u", SNOWFLAKE_PASSWORD="pw"):
            at = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=60)
            at.session_state["page"] = page
            for k, v in (state or {}).items():
                at.session_state[k] = v
            at.run()
    finally:
        snowflake.connector.connect = real
    return at


def _text(at) -> str:
    parts = [e.value for group in (at.error, at.warning, at.info, at.success, at.markdown, at.caption) for e in group]
    return "\n".join(str(p) for p in parts)


def _no_exception(at):
    assert not at.exception, f"app raised: {[e.value for e in at.exception]}"


def _state_get(state, key, default=None):
    """Read AppTest state without relying on its version-specific filtered_state view."""
    try:
        return state[key]
    except (KeyError, AttributeError):
        return default


def _everything(at) -> str:
    """Text AND the labels of expanders, with markdown escapes removed, for 'is this on the page' checks."""
    parts = [getattr(e, "value", None) or getattr(e, "label", "") for group in (at.error, at.warning, at.info, at.success, at.markdown, at.caption, at.expander) for e in group]
    return "\n".join(str(p) for p in parts).replace("\\", "")


def _choose(at, decision):
    next(r for r in at.radio if r.label == T.DECISION_PROMPT).set_value(decision).run()
    return at


def _record_button(at):
    return next((b for b in at.button if (b.key or "").startswith("record_")), None)


# ── tests ────────────────────────────────────────────────────────────────────

def test_alert_queue_renders_the_demo_pair():
    at = run_app()
    _no_exception(at)
    t = _text(at)
    assert T.PAIR_TITLE in t and "ALERT-01" in t and "ALERT-16" in t
    labels = {b.label for b in at.button}
    assert {"Open ALERT-01 — source facts first →", "Open ALERT-16 — source facts first →"} <= labels
    assert any(b.key == "review_ALERT-02" for b in at.button), "every other alert keeps its own Review button"
    print("  [PASS] Alert Queue renders the ALERT-01 vs ALERT-16 same-signal pair with its Open buttons, and a Review button per other alert")


def test_judge_demo_path_exposes_the_four_step_story_without_making_a_decision():
    at = run_app()
    _no_exception(at)
    text = _everything(at)
    for step in ("Judge demo path", "Compare ALERT-01 and ALERT-16", "Review regulatory basis and AI assessment",
                 "Test the evidence gate", "Record and reconstruct a decision"):
        assert step in text, step
    labels = {b.label for b in at.button}
    assert {"Open ALERT-01", "Review the case", "Open evidence gate", "Open decision archive"} <= labels
    assert not any(b.label.startswith("Record") for b in at.button), "the guide may only navigate; it must not create a decision action"
    print("  [PASS] judge demo path names the four existing workflow steps and exposes navigation only")


def test_database_down_shows_error_state_not_a_stack_trace():
    at = run_app([("ALERTS_CURRENT", RuntimeError("SQL access control error: Insufficient privileges to operate on view 'ALERTS_CURRENT'"))])
    _no_exception(at)
    msg = " ".join(e.value for e in at.error)
    assert msg.startswith("The alert queue is unavailable.") and "Tell your administrator" in msg and "Reference:" in msg, msg
    assert "Insufficient privileges" not in msg and "ALERTS_CURRENT" not in msg, "the database's own words are classified, never shown"
    assert any(b.label == "Retry" for b in at.button)
    print("  [PASS] alert queue: DB failure → a short, actionable message with a reference and a Retry button; the database's text is not shown (no exception)")


def test_empty_queue_state():
    at = run_app([("FROM FIU_COPILOT.AML.ALERTS_CURRENT", [])])
    _no_exception(at)
    assert T.EMPTY_QUEUE in [i.value for i in at.info]
    print("  [PASS] empty queue → 'No alerts are loaded. Ask your administrator to load the alert feed.'")


def test_connection_failure_is_actionable_and_secret_free():
    st.cache_resource.clear(); st.cache_data.clear()
    real = snowflake.connector.connect
    def boom(**kw):
        raise snowflake.connector.errors.DatabaseError("390100 Incorrect username or password was specified. pw=" + kw["password"])
    snowflake.connector.connect = boom
    from _helpers import scoped_env
    try:
        with scoped_env(SNOWFLAKE_ACCOUNT="ORGNAME-ACCT123456", SNOWFLAKE_USER="jdoe", SNOWFLAKE_PASSWORD="Sup3rSecretPW!"):
            at = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=60).run()
    finally:
        snowflake.connector.connect = real
    _no_exception(at)
    msg = " ".join(e.value for e in at.error)
    assert "Cannot connect to Snowflake" in msg and "SNOWFLAKE_PASSWORD" in msg
    assert "Sup3rSecretPW!" not in msg and "jdoe" not in msg and "ORGNAME-ACCT123456" not in msg
    print("  [PASS] connection failure → 'Cannot connect' with the fix; password / user / account never shown")


def _disposition(alert_id, rules=(), state=None):
    return run_app(rules, page="Disposition Panel", state={"selected_alert": alert_id, **(state or {})})


def test_disposition_separates_source_facts_from_ai_inference_and_regulatory_basis():
    at = _disposition("ALERT-16")
    _no_exception(at)
    t = _everything(at)
    for key in ("facts", "basis", "ai", "human"):
        assert T.ZONES[key][0] in t, key
    assert "PROVEN" in t and "ASSUMED" in t
    assert any(e.label == f"{T.PAIR_TITLE} — compare with ALERT-01" for e in at.expander)
    print("  [PASS] disposition: SOURCE FACTS | REGULATORY BASIS (PROVEN vs ASSUMED) | AI INFERENCE | HUMAN DECISION are separate labelled zones + the pair comparison")


def test_core_capability_labels_and_completion_summary_are_visible_and_bounded():
    receipt = {"decision_id": "receipt-1", "alert_id": "ALERT-16", "disposition": "NOT_FILE", "sla_days_remaining": 6,
               "po_id": "PO-17", "recorded_at": "5 Oct 2026, 10:30 IST", "evidence_txn_ids": ["T16-1", "T16-2"],
               "proven_rule_ids": ["STR-002"], "assumed_rule_ids": ["CTR-002"], "assumed_basis_acknowledged": True}
    at = _disposition("ALERT-16", state={"last_decision": receipt})
    _no_exception(at)
    text = _everything(at)
    for label in ("Cortex Search · Governed regulatory lookup", "Cortex Complete · Labelled suspicion assessment",
                  "Evidence gate · Deterministic grounding before filing", "Decision record complete",
                  "Final human disposition:", "Principal Officer:", "Evidence references:", "Regulatory basis:"):
        assert label in text, label
    assert "Ledger reference: receipt-1" in [entry.value for entry in at.text]
    assert any(b.label == "Open reconstruction" for b in at.button)
    assert "no STR was submitted" in text
    print("  [PASS] capability labels state their limits; completion summary names human outcome, provenance and reconstruction")


def test_transactions_unreadable_blocks_file_and_says_why():
    at = _disposition("ALERT-01", [("FROM FIU_COPILOT.AML.TRANSACTIONS WHERE ALERT_ID", RuntimeError("Object 'TRANSACTIONS' does not exist or not authorized"))])
    _no_exception(at)
    assert any(e.value.startswith("The transaction record is unavailable.") for e in at.error), [e.value for e in at.error]
    assert "does not exist" not in " ".join(e.value for e in at.error), "the database's own words are not shown"
    for cb in _choose(at, "FILE").checkbox:
        cb.check()
    at.run()
    assert _record_button(at).disabled, "FILE must be blocked without a transaction record, whatever is ticked"
    print("  [PASS] transactions unreadable → explicit error; a filing is blocked (fail closed, not 'no transactions')")


def test_no_transactions_warns_and_disables_file_and_ai():
    at = _disposition("ALERT-01", [("FROM FIU_COPILOT.AML.TRANSACTIONS WHERE ALERT_ID", [])])
    _no_exception(at)
    assert T.NO_TRANSACTIONS in [w.value for w in at.warning]
    for cb in _choose(at, "FILE").checkbox:
        cb.check()
    at.run()
    assert _record_button(at).disabled
    assert not any(b.label == "Run 11-Factor Assessment" for b in at.button)
    print("  [PASS] empty transaction set → warning; a filing and the AI assessment are unavailable")


def test_invalid_ai_assessment_surfaces_an_error_and_withholds_the_recommendation():
    from skills import CoPilotSkills
    bad = CoPilotSkills(None, cortex_fn=lambda p: "```json\n{not json}\n```").suspicion_evaluator({"customer_kyc": "x", "transactions": []})
    at = _disposition("ALERT-01", state={"poe_assessment": bad, "assessed_alert": "ALERT-01", "assessment_model": "llama3.3-70b"})
    _no_exception(at)
    msg = " ".join(e.value for e in at.error)
    assert "The AI output was invalid, so its recommendation is withheld." in msg
    assert "AI Recommendation:" not in _text(at), "no recommendation may be shown for invalid AI output"
    print("  [PASS] invalid AI assessment → clear UI error, recommendation withheld, nothing shown as a finding")


def test_file_button_requires_the_deterministic_gate_and_shows_what_failed():
    fake_gos = "I formed suspicion because ₹25,00,000 moved to Dubai via SWIFT on 2026-08-27. " + "Detail. " * 20
    at = _disposition("ALERT-01", state={"gos_text_ALERT-01": fake_gos, "_keep_gos_text_ALERT-01": fake_gos})
    _no_exception(at)
    assert any(e.value.startswith("**Facts check: BLOCKED.**") for e in at.error), [e.value for e in at.error]
    blocked = " ".join(e.value for e in at.error)
    assert "amount" in blocked and "geography" in blocked and "channel" in blocked and "date" in blocked
    at = _choose(at, "FILE")
    for cb in at.checkbox:
        cb.check()
    at.run()
    assert _record_button(at).disabled, "no acknowledgement lifts a filing whose text states facts that are not in the record"
    print("  [PASS] fabricated text → 'Facts check: BLOCKED' names amount/date/channel/geography; a filing cannot be recorded")


def test_grounded_text_enables_file_and_labels_unverified_assertions_and_scope():
    good = ("I formed suspicion on 2026-08-18 after credits of ₹1,10,000, ₹1,40,000 and ₹95,000 from unknown UPI handle A, B and D "
            "were followed by debits of ₹2,46,500 and ₹94,200 to UPI handle C (I4C-flagged). The beneficiary has known links to hawala operators. " + "More detail. " * 12)
    # The officer types an ID. (Before Phase 14 this test passed only because Streamlit's local-development placeholder e-mail was pre-filled as the
    # Principal Officer ID — an unauthenticated attribution the app no longer makes.)
    at = _disposition("ALERT-01", state={"gos_text_ALERT-01": good, "_keep_gos_text_ALERT-01": good, "po_id": "PO-T", "_keep_po_id": "PO-T"})
    _no_exception(at)
    assert any(s_.value.startswith("**Facts check: PASS.**") for s_ in at.success), ([e.value for e in at.error], [s_.value for s_ in at.success])
    assert any(w.value.startswith("**Unverified statements.**") for w in at.warning)
    assert any(e.label == "What the facts check did and did not verify" for e in at.expander)
    at = _choose(at, "FILE")
    assert any(c.label == T.ACK_UNVERIFIED for c in at.checkbox)
    record = lambda: _record_button(at)   # noqa: E731
    assert record().disabled, "an unacknowledged unverified statement, a narrative that was never AI-checked and ASSUMED rules are all still pending"
    assert any(c.label.startswith("I understand this filing rests partly on ASSUMED rules") for c in at.checkbox)
    for cb in at.checkbox:                                      # satisfy every pending condition explicitly
        cb.check()
    next(t for t in at.text_area if t.label.startswith("Why are you proceeding")).set_value(
        "The AI quality check was not run; I verified every figure against the account statement myself.")
    at.run()
    _no_exception(at)
    assert not record().disabled, [m.value for m in at.markdown if "Ready" in m.value or "Not ready" in m.value][:3]
    print("  [PASS] grounded text → facts check PASS; a filing stays blocked until the unverified-statement and ASSUMED-basis acknowledgements and a reason are given")


def test_ledger_states_empty_tampered_and_legacy():
    at = run_app([("FROM FIU_COPILOT.AML.DECISION_LEDGER d", [])], page="Decision Ledger")
    _no_exception(at)
    assert T.EMPTY_LEDGER in [i.value for i in at.info]
    row = lambda status, i="d1": {"DECISION_ID": i, "ALERT_ID": "ALERT-01", "CUSTOMER_REF": "C", "DISPOSITION": "FILE", "DECISION_MAKER_ID": "PO",
                          "SUSPICION_FORMED_AT": "2026-09-30", "DECISION_MADE_AT": "2026-09-30", "SLA_DAYS_REMAINING": 7, "STR_REFERENCE": "X",
                          "RATIONALE_TEXT": "r", "INTEGRITY_STATUS": status, "ALERT_TYPE": "T", "CUSTOMER_PROFILE": "p", "ALERT_AMOUNT_INR": 1}
    at = run_app([("FROM FIU_COPILOT.AML.DECISION_LEDGER d", [row("TAMPERED", "d1"), row("INTACT", "d2")])], page="Decision Ledger")
    _no_exception(at)
    assert T.INTEGRITY_TAMPERED.format(n=1) in [e.value for e in at.error]
    at = run_app([("FROM FIU_COPILOT.AML.DECISION_LEDGER d", [row("LEGACY_UNHASHED")])], page="Decision Ledger")
    assert any(T.INTEGRITY_LEGACY.format(n=1) in s_.value for s_ in at.success) and not at.error
    print("  [PASS] ledger: empty → guidance; TAMPERED → red error; LEGACY_UNHASHED → disclosed as unverifiable")


def test_regulatory_page_empty_corpus_and_search_fallback_and_warnings():
    empty = {"VERSION": "1.1.0", "N_VERSIONS": 1, "SNAPSHOT": "2026-09-17", "TOTAL": 0, "PROVEN": 0, "ASSUMED": 0, "NV": 0, "VERIFIED": 0, "SUPERSEDED": 0}
    at = run_app([("COUNT(DISTINCT CORPUS_VERSION)", [empty])], page="Regulatory Reference")
    _no_exception(at)
    assert T.EMPTY_CORPUS in [i.value for i in at.info]

    def rule(rid, lvl, **kw):
        base = dict(RULE_ID=rid, RULE_TEXT=f"text of {rid}", MY_SYNTHESIS="", EVIDENCE_LEVEL=lvl, SOURCE_DOCUMENT="doc", SOURCE_URL="https://x",
                    SOURCE_URL_VERIFIED=False, SNAPSHOT_DATE="2026-09-17", CATEGORY="CAT", SOURCE_AUTHORITY="STATUTE", CORPUS_VERSION="1.1.0",
                    REVIEW_STATUS="AUTHOR_ASSERTED", OWNER="o", LAST_VERIFIED=None, VERIFIED_BY=None, SUPERSEDED_BY=None, REPLACES=None)
        base.update(kw)
        return base
    str006 = rule("STR-006", "ASSUMED", REPLACES="FINnet direct-upload mechanism")
    rules = [("SEARCH_PREVIEW", RuntimeError("Cortex Search service CORPUS_SEARCH is suspended")),
             ("WHERE rc.RULE_ID =", [str006]), ("REPLACES IS NOT NULL", [str006]),
             ("CONTAINS(LOWER(rc.SEARCH_TEXT)", [rule("STR-002", "PROVEN"), rule("OLD-1", "ASSUMED", SUPERSEDED_BY="STR-006")])]
    # drive the widget through the skills layer the page uses
    from skills import CoPilotSkills
    res = CoPilotSkills(UIFake(rules)).regulatory_lookup_with_basis("upload the STR through FINnet direct upload", limit=5)
    assert res["mode"] == "keyword_fallback" and "suspended" in res["fallback_reason"]
    assert [r["rule_id"] for r in res["rules"]] == ["STR-006", "STR-002"] and res["superseded"][0]["rule_id"] == "OLD-1"
    st.cache_resource.clear(); st.cache_data.clear()
    at = run_app(rules, page="Regulatory Reference")
    at.text_input[0].set_value("upload the STR through FINnet direct upload").run()
    _no_exception(at)
    warns = " ".join(w.value for w in at.warning).replace("\\", "")        # untrusted rule text is Markdown-escaped (md_safe); the escapes do not display
    assert "Regulatory search did not answer" in warns and "plain keyword matching" in warns and "not ranked by meaning" in warns
    assert "Superseded instrument" in warns and "STR-006" in warns
    assert "ASSUMED content" in warns, "ASSUMED successor rule ⇒ explicit warning"
    print("  [PASS] regulatory page: empty corpus; Search down → keyword-fallback banner; superseded qualification; ASSUMED warning")


def test_analyst_unavailable_is_an_explicit_error_and_the_rest_of_the_dashboard_survives():
    from skills import CorpusAnalyst
    real = CorpusAnalyst.ask
    CorpusAnalyst.ask = lambda self, q: CorpusAnalyst._unavailable("Cortex Analyst HTTP 403 — role lacks CORTEX_USER / stage READ access")
    try:
        at = run_app(page="Dashboard")
        _no_exception(at)
        at.text_input[0].set_value("how many alerts are filed?")
        at.button[0].click().run()
    finally:
        CorpusAnalyst.ask = real
    _no_exception(at)
    err = " ".join(e.value for e in at.error)
    assert err.startswith("Ask the data is unavailable.") and "Reference:" in err and "not affected" in err
    assert "HTTP 403" not in err and "CORTEX_USER" not in err, "the service's own words are classified, never shown"
    assert any(m.label == "Alert-to-STR Ratio" for m in at.metric), "metrics computed directly from tables still render"
    print("  [PASS] Analyst down → explicit error with a reference (the service text is not shown); dashboard metrics unaffected")


def test_analyst_advisories_are_collapsed_plain_text_not_a_wall_of_warning_boxes():
    """Regression (live rehearsal 2026-10-01): one 'Ask the data' answer was followed by 12 yellow boxes of raw {'message': …} dicts."""
    from skills import CorpusAnalyst
    note = "Verified query 'open_alert_count' referred to physical tables. Please replace this verified query with SELECT COUNT(*) FROM __alerts"
    real = CorpusAnalyst.ask
    CorpusAnalyst.ask = lambda self, q: {"available": True, "generated_sql": "SELECT ALERT_STATUS, COUNT(*) AS ALERT_COUNT FROM ALERTS_CURRENT GROUP BY 1",
                                         "rows": [{"ALERT_STATUS": "OPEN", "ALERT_COUNT": 14}, {"ALERT_STATUS": "REVIEWED", "ALERT_COUNT": 2}],
                                         "interpretation": "How many alerts are there in each alert status?", "warnings": [], "analyst_notes": [note, note + " (2)"]}
    try:
        at = run_app(page="Dashboard")
        _no_exception(at)
        at.text_input[0].set_value("How many alerts are there in each status?")
        at.button[0].click().run()
    finally:
        CorpusAnalyst.ask = real
    _no_exception(at)
    assert not [w for w in at.warning if "Verified query" in w.value or "{'message'" in w.value], "advisories must not be warning boxes"
    exp = [e for e in at.expander if "Analyst notes about the semantic model (2)" in e.label]
    assert exp, [e.label for e in at.expander]
    assert any(note in t.value for t in exp[0].text), "advisories are rendered as plain text inside the collapsed expander"
    assert at.dataframe, "the answer's rows still render"
    print("  [PASS] Analyst advisories are a collapsed expander of plain text; the answer and rows are unaffected")


def test_html_is_escaped_in_rendered_markup():
    """A hostile rule text / decision field cannot inject markup through unsafe_allow_html."""
    from skills import CoPilotSkills  # noqa: F401
    evil = '<img src=x onerror=alert(1)>'
    row = {"RULE_ID": evil, "SUBCATEGORY": evil, "RULE_PREVIEW": evil, "EVIDENCE_LEVEL": "PROVEN", "REVIEW_STATUS": evil}
    at = run_app([("WHERE RULE_ID IN ('STR-001'", [row])], page="Regulatory Reference")
    _no_exception(at)
    html_blobs = " ".join(m.value for m in at.markdown)
    assert "<img src=x" not in html_blobs and "&lt;img" in html_blobs, html_blobs[:300]
    print("  [PASS] hostile rule metadata is HTML-escaped before unsafe_allow_html rendering")


def test_review_jump_after_manual_sidebar_navigation_stays_on_the_panel():
    """Regression (found rehearsing the demo in a real browser, 2026-10-01). Sequence: Review ALERT-16 → click *Alert Queue* in the
    sidebar → Review ALERT-01 → any widget interaction used to bounce the user back to the queue.

    LIMIT: AppTest keeps widget state in Python, so it could NOT reproduce the old failure (the stale value was held by the
    *browser*); the bug and the fix were verified in a real browser. This test pins the navigation contract; the next test pins the root cause."""
    at = run_app()
    _no_exception(at)
    assert at.sidebar.radio[0].key == "nav_page" and at.sidebar.radio[0].value == "Alert Queue"
    next(b for b in at.button if b.key == "pair_ALERT-16").click().run()
    assert at.sidebar.radio[0].value == "Disposition Panel" and at.session_state["selected_alert"] == "ALERT-16"
    at.sidebar.radio[0].set_value("Alert Queue").run()
    assert any((b.key or "").startswith("pair_") for b in at.button), "sidebar navigation back to the queue did not render the queue"
    next(b for b in at.button if b.key == "pair_ALERT-01").click().run()
    _no_exception(at)
    assert at.sidebar.radio[0].value == "Disposition Panel" and at.session_state["selected_alert"] == "ALERT-01"
    next(t for t in at.text_input if t.label == "Principal Officer ID").set_value("PO-X").run()   # any later interaction must not change the page
    _no_exception(at)
    assert at.sidebar.radio[0].value == "Disposition Panel" and at.session_state["selected_alert"] == "ALERT-01"
    assert any("Run 11-Factor Assessment" in b.label for b in at.button), "the Disposition Panel is no longer rendered"
    at.sidebar.radio[0].set_value("Alert Queue").run()                           # the queue's own "Review →" buttons take the same path
    next(b for b in at.button if b.key == "review_ALERT-02").click().run()
    assert at.sidebar.radio[0].value == "Disposition Panel" and at.session_state["selected_alert"] == "ALERT-02"
    print("  [PASS] Review jumps after manual sidebar navigation keep the panel through later interactions (pair + list buttons)")


def test_navigation_radio_is_keyed_and_never_driven_by_a_changing_index():
    """Root cause of the bounce: an UNKEYED `st.radio(..., index=<changes with session_state>)` changes widget identity whenever the
    page changes, so the browser keeps a stale value. Guard it structurally (AppTest cannot reproduce the stale browser state)."""
    import re
    src = (ROOT / "streamlit_app.py").read_text()
    radio = re.search(r'st\.radio\(\s*"Navigate"[^)]*\)', src)
    assert radio, "navigation radio not found"
    assert 'key="nav_page"' in radio.group(0) and "index=" not in radio.group(0), radio.group(0)
    assert 'st.session_state["page"] = "Disposition Panel"' not in src, "pages must be requested via _goto, not assigned after the radio exists"
    assert src.count('st.session_state["_goto"] = "Disposition Panel"') == 2
    assert src.index('st.session_state.pop("_goto"') < src.index(radio.group(0)), "_goto must be applied BEFORE the radio is created"
    print("  [PASS] navigation radio is keyed, has no changing index, and _goto is applied before it is created")


TESTS = [
    test_alert_queue_renders_the_demo_pair, test_database_down_shows_error_state_not_a_stack_trace, test_empty_queue_state,
    test_connection_failure_is_actionable_and_secret_free,
    test_disposition_separates_source_facts_from_ai_inference_and_regulatory_basis,
    test_transactions_unreadable_blocks_file_and_says_why, test_no_transactions_warns_and_disables_file_and_ai,
    test_invalid_ai_assessment_surfaces_an_error_and_withholds_the_recommendation,
    test_file_button_requires_the_deterministic_gate_and_shows_what_failed,
    test_grounded_text_enables_file_and_labels_unverified_assertions_and_scope,
    test_ledger_states_empty_tampered_and_legacy, test_regulatory_page_empty_corpus_and_search_fallback_and_warnings,
    test_analyst_unavailable_is_an_explicit_error_and_the_rest_of_the_dashboard_survives, test_html_is_escaped_in_rendered_markup,
    test_review_jump_after_manual_sidebar_navigation_stays_on_the_panel, test_navigation_radio_is_keyed_and_never_driven_by_a_changing_index,
    test_analyst_advisories_are_collapsed_plain_text_not_a_wall_of_warning_boxes,
]


def test_queue_filters_survive_case_navigation():
    at = run_app()
    at.text_input(key="aq_search").set_value("ALERT-02").run()
    at.multiselect(key="aq_type").set_value(["STRUCTURING"]).run()
    at.slider(key="aq_amt").set_value((1.0, 10.0)).run()
    at.button(key="review_ALERT-02").click().run()
    assert at.session_state["selected_alert"] == "ALERT-02"
    at.button(key="back_to_cases").click().run()
    _no_exception(at)
    assert at.text_input(key="aq_search").value == "ALERT-02"
    assert at.multiselect(key="aq_type").value == ["STRUCTURING"]
    assert tuple(at.slider(key="aq_amt").value) == (1.0, 10.0)
    assert [b.key for b in at.button if (b.key or "").startswith("review_")] == ["review_ALERT-02"]
    assert "Return to last case row" in _text(at)


def test_case_clock_does_not_invent_a_reporting_deadline():
    from datetime import datetime, timezone
    from streamlit_app import case_clock
    now = datetime(2026, 10, 2, 12, tzinfo=timezone.utc)
    alert = {"ALERT_DATE": "2026-09-01"}
    absent = case_clock(alert, now=now)
    assert absent == {"age": "31 calendar days old", "days": None, "label": "Suspicion time not recorded", "source": None}
    assert case_clock(alert, "2026-10-01", now=now, source="feed")["source"] == "feed" and absent["source"] is None, "the source is reported only when there is a clock"
    assert case_clock(alert, "2026-10-01", now=now)["days"] == 6
    assert case_clock(alert, "2026-09-01", now=now)["days"] < 0
    for value in ("invalid", "2027-01-01"):
        assert case_clock(alert, value, now=now)["label"] == "Suspicion time needs review"
    assert case_clock(alert, "2026-10-01", unavailable=True, now=now)["days"] is None


def test_timestamp_lookup_failure_keeps_case_review_available():
    at = run_app([("MIN(SUSPICION_FORMED_AT)", RuntimeError("timestamp lookup failed"))])
    _no_exception(at)
    assert "Suspicion time unavailable" in _text(at)
    assert any(b.key == "review_ALERT-02" for b in at.button)
    assert not any("WD overdue" in m.value for m in at.markdown)


def test_recorded_deadlines_sort_ahead_of_unknown_times():
    from datetime import datetime, timezone
    at = run_app([("MIN(SUSPICION_FORMED_AT)", [{"ALERT_ID": "ALERT-02", "RECORDED_SUSPICION_AT": datetime.now(timezone.utc)}])])
    _no_exception(at)
    reviews = [b.key for b in at.button if (b.key or "").startswith("review_")]
    assert reviews[0] == "review_ALERT-02"
    assert "Suspicion time not recorded" in _text(at)


TESTS += [test_queue_filters_survive_case_navigation, test_case_clock_does_not_invent_a_reporting_deadline,
          test_timestamp_lookup_failure_keeps_case_review_available, test_recorded_deadlines_sort_ahead_of_unknown_times]

def test_movement_summary_detection_does_not_modify_records():
    from copy import deepcopy
    from skills.evidence import movement_records
    rows = [{"txn_id": "A", "type": "CREDIT", "counterparty": "Cash deposits (15d)"},
            {"txn_id": "B", "type": "DEBIT", "counterparty": "Hospital"},
            {"txn_id": "C", "type": "OTHER", "is_summary": True}]
    before = deepcopy(rows)
    result = movement_records(rows)
    assert rows == before
    assert result["summary_ids"] == ["A", "C"] and result["row_count"] == 3
    assert result["groups"]["DEBIT"] == [rows[1]]


def test_movement_filter_preserves_note_and_does_not_run_ai():
    at = _disposition("ALERT-01")
    at.text_area(key="gos_text_ALERT-01").set_value("Working note for this case only.").run()
    at.radio(key="movement_direction_ALERT-01").set_value("Credits").run()
    _no_exception(at)
    assert len(at.dataframe[0].value) == 3
    assert at.text_area(key="gos_text_ALERT-01").value == "Working note for this case only."
    assert not _state_get(at.session_state, "assessment")
    assert next(r for r in at.radio if r.label == T.DECISION_PROMPT).value is None
    assert "₹340,700" in _text(at)  # full-record debit totals remain visible


def test_working_notes_stay_with_their_case():
    at = _disposition("ALERT-01")
    at.text_area(key="gos_text_ALERT-01").set_value("First case evidence note.").run()
    next(s for s in at.selectbox if s.label == "Alert").set_value("ALERT-16").run()
    assert at.text_area(key="gos_text_ALERT-16").value == ""
    at.text_area(key="gos_text_ALERT-16").set_value("Second case evidence note.").run()
    next(s for s in at.selectbox if s.label == "Alert").set_value("ALERT-01").run()
    _no_exception(at)
    assert at.text_area(key="gos_text_ALERT-01").value == "First case evidence note."


def test_summary_and_absent_debit_rows_are_not_presented_as_complete_transfers():
    at = _disposition("ALERT-02")
    assert "Aggregated records present" in _text(at)
    at = _disposition("ALERT-04")
    assert "No debit rows" in _text(at)
    at.radio(key="movement_direction_ALERT-04").set_value("Debits").run()
    _no_exception(at)
    assert "does not establish that no transfers occurred" in _text(at)


TESTS += [test_movement_summary_detection_does_not_modify_records,
          test_movement_filter_preserves_note_and_does_not_run_ai,
          test_working_notes_stay_with_their_case,
          test_summary_and_absent_debit_rows_are_not_presented_as_complete_transfers]

def test_narrative_references_preserve_exact_text_and_reset_after_edit():
    note = "Review T01-1 and T01-2 before deciding."
    at = _disposition("ALERT-01", state={"gos_text_ALERT-01": note})
    refs = at.selectbox(key="narrative_reference_ALERT-01")
    assert refs.options == ["Transaction · T01-1", "Transaction · T01-2"]
    refs.set_value("Transaction · T01-2").run()
    assert at.text_area(key="gos_text_ALERT-01").value == note
    at.text_area(key="gos_text_ALERT-01").set_value("Review T01-1 only, not a conclusion.").run()
    _no_exception(at)
    assert at.selectbox(key="narrative_reference_ALERT-01").value == "Transaction · T01-1"
    assert not _state_get(at.session_state, "poe_assessment")


def test_reference_matching_does_not_match_an_id_prefix():
    at = _disposition("ALERT-01", state={"gos_text_ALERT-01": "Review T01-100 before deciding."})
    _no_exception(at)
    assert not any(s.key == "narrative_reference_ALERT-01" for s in at.selectbox)
    assert "No supplied transaction or case-basis rule IDs matched" in _text(at)


def test_reference_navigation_keeps_stale_quality_stale():
    import hashlib
    old = "Review T01-1 before deciding."
    at = _disposition("ALERT-01", state={"gos_text_ALERT-01": old + " Revised.", "gos_alert": "ALERT-01",
        "gos_result": {"narrative": old, "status": "READY", "checked_sha": hashlib.sha256(old.encode()).hexdigest(),
                       "quality_score": 9, "ai_output_valid": True, "hard_gate_passed": True}})
    _no_exception(at)
    assert T.STALE_QUALITY in _text(at)
    at.selectbox(key="narrative_reference_ALERT-01").set_value("Transaction · T01-1").run()
    assert T.STALE_QUALITY in _text(at)
    assert "not sentence-level verification" in _text(at)


def test_counter_evidence_has_two_sides_and_keeps_hostile_text_inert():
    from test_po_workflow import with_ai
    at = _disposition("ALERT-16", state=with_ai("ALERT-16", triggered=("POE-005", "POE-008", "POE-009"),
        evidence="<script>alert('hostile')</script> record observation"))
    _no_exception(at)
    text = _text(at)
    assert "Observations supporting the leading call" in text
    assert "Observations challenging the leading call" in text
    assert "not probabilities" in text
    assert "<script>" not in " ".join(m.value for m in at.markdown)


TESTS += [test_narrative_references_preserve_exact_text_and_reset_after_edit,
          test_reference_matching_does_not_match_an_id_prefix,
          test_reference_navigation_keeps_stale_quality_stale,
          test_counter_evidence_has_two_sides_and_keeps_hostile_text_inert]

def test_review_sheet_keeps_full_rationale_and_distinguishes_filing():
    from test_po_workflow import case, choose
    note = "Officer observation.\n\n" + "Evidence requires careful review. " * 15 + "FINAL EXACT LINE"
    at = choose(case("ALERT-01", text=note), "FILE")
    _no_exception(at)
    assert note in [t.value for t in at.text]
    assert _record_button(at).label == "Record decision to file"
    assert "does not submit an STR" in _text(at)
    assert "Decision review sheet" in _text(at)


def test_failed_recording_preserves_form_without_receipt():
    from unittest.mock import patch
    from skills import CoPilotSkills
    from test_po_workflow import case, choose, tick_all
    at = tick_all(choose(case("ALERT-16"), "NOT_FILE"))
    note = at.text_area(key="gos_text_ALERT-16").value
    with patch.object(CoPilotSkills, "alert_disposition_recorder", side_effect=RuntimeError("Test-only write failure")):
        _record_button(at).click().run()
    _no_exception(at)
    assert at.text_area(key="gos_text_ALERT-16").value == note
    assert not _state_get(at.session_state, "last_decision")
    assert not _state_get(at.session_state, "form_gen", 0)
    assert "NOT recorded" in _text(at)


def test_dossier_separates_recorded_fingerprint_from_current_replay():
    from test_po_workflow import _reconstruction_harness
    at = AppTest.from_function(_reconstruction_harness).run()
    _no_exception(at)
    text = _text(at)
    assert "not a complete historical copy" in text
    assert "current case data" in text
    assert "Evidence at decision time" in text
    assert "Officer reasoning and recorded outcome" in text


TESTS += [test_review_sheet_keeps_full_rationale_and_distinguishes_filing,
          test_failed_recording_preserves_form_without_receipt,
          test_dossier_separates_recorded_fingerprint_from_current_replay]

if __name__ == "__main__":
    raise SystemExit(Runner("UI failure / empty / warning states (AppTest, no network)").run(TESTS))
