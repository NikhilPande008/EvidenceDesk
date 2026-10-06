"""
Regulatory-confidence controls: the decision-level regulatory-basis object (corpus version, snapshot, rule IDs, evidence levels,
review status, source authority, supersession status), explicit acknowledgement of ASSUMED rules in a filing, and NO legal
conclusion where no supported corpus basis exists.

Deterministic paths covered: no-result · ASSUMED · NEEDS-VERIFICATION · superseded · not-in-corpus · corpus unreadable.
Offline (pure builders + a scripted fake database).
Usage:  python3 tests/test_regulatory_basis.py     (or pytest)
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from _helpers import FakeConn, Runner, basis_for, recorder_kwargs, rule_row

from skills import CoPilotSkills
from skills import governance as G

TOP_KEYS = {"schema", "corpus_version", "snapshot_date", "grade", "legal_conclusion_permitted", "requires_assumed_acknowledgement",
            "proven_rule_ids", "assumed_rule_ids", "excluded", "rules", "by_evidence_level", "independently_verified_count",
            "stale_review_rule_ids", "error", "basis_sha256"}
RULE_KEYS = {"rule_id", "evidence_level", "review_status", "source_authority", "corpus_version", "snapshot_date",
             "supersession_status", "superseded_by", "usable_as_basis", "unusable_reason"}


def _recent() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _blocked(conn, **over) -> str:
    try:
        CoPilotSkills(conn).alert_disposition_recorder(**recorder_kwargs(suspicion_formed_at=_recent(), **over))
    except Exception as err:  # noqa: BLE001
        assert type(err).__name__ == "LedgerBlocked", repr(err)
        return str(err)
    raise AssertionError("the decision was recorded; it should have been refused")


# ── the object ───────────────────────────────────────────────────────────────

def test_basis_object_carries_every_required_field():
    b = basis_for(["STR-001", "POE-003", "RFI-001"])
    assert TOP_KEYS <= set(b), TOP_KEYS - set(b)
    assert b["schema"] == G.BASIS_SCHEMA and b["corpus_version"] == "1.1.0" and b["snapshot_date"] == "2026-09-17"
    assert [r["rule_id"] for r in b["rules"]] == ["POE-003", "RFI-001", "STR-001"], "rules are listed in a stable (sorted) order"
    for r in b["rules"]:
        assert RULE_KEYS <= set(r), (r["rule_id"], RULE_KEYS - set(r))
    by = {r["rule_id"]: r for r in b["rules"]}
    assert (by["STR-001"]["evidence_level"], by["STR-001"]["source_authority"], by["STR-001"]["review_status"]) == ("PROVEN", "STATUTE", "AUTHOR_ASSERTED")
    assert by["POE-003"]["evidence_level"] == "ASSUMED" and by["POE-003"]["source_authority"] == "PRODUCT_COMPILED"
    assert by["STR-001"]["supersession_status"] == "CURRENT" and by["STR-001"]["superseded_by"] is None
    assert by["STR-001"]["corpus_version"] == "1.1.0" and by["STR-001"]["snapshot_date"] == "2026-09-11"
    print("  [PASS] basis object: corpus version + snapshot, and per rule evidence level, review status, source authority, supersession status")


def test_basis_grades_for_every_path():
    proven = basis_for(["STR-001"])
    assert (proven["grade"], proven["legal_conclusion_permitted"], proven["requires_assumed_acknowledgement"]) == (G.GRADE_PROVEN_ONLY, True, False)
    assumed = basis_for(["STR-001", "POE-003"])
    assert (assumed["grade"], assumed["legal_conclusion_permitted"], assumed["requires_assumed_acknowledgement"]) == (G.GRADE_INCLUDES_ASSUMED, True, True)
    assert assumed["proven_rule_ids"] == ["STR-001"] and assumed["assumed_rule_ids"] == ["POE-003"]
    nv = basis_for(["RFI-001"])
    assert (nv["grade"], nv["legal_conclusion_permitted"]) == (G.GRADE_NO_SUPPORTED_BASIS, False)
    assert nv["excluded"] == [{"rule_id": "RFI-001", "reason": G.UNUSABLE_NEEDS_VERIFICATION, "superseded_by": None}]
    assert nv["by_evidence_level"] == {"NEEDS-VERIFICATION": ["RFI-001"]}, "an NV citation stays visible, labelled, never counted"
    sup = basis_for(["STR-001", "POE-003"], overrides={"POE-003": {"SUPERSEDED_BY": "POE-099"}})
    assert sup["assumed_rule_ids"] == [] and sup["requires_assumed_acknowledgement"] is False, "a superseded rule is not counted — so it cannot demand an acknowledgement either"
    assert sup["excluded"] == [{"rule_id": "POE-003", "reason": G.UNUSABLE_SUPERSEDED, "superseded_by": "POE-099"}]
    assert {r["rule_id"]: r["supersession_status"] for r in sup["rules"]} == {"POE-003": "SUPERSEDED", "STR-001": "CURRENT"}
    only_sup = basis_for(["POE-003"], overrides={"POE-003": {"SUPERSEDED_BY": "POE-099"}})
    assert only_sup["grade"] == G.GRADE_NO_SUPPORTED_BASIS and not only_sup["legal_conclusion_permitted"]
    missing = basis_for(["STR-001", "ZZZ-404"])
    assert missing["excluded"] == [{"rule_id": "ZZZ-404", "reason": G.UNUSABLE_NOT_IN_CORPUS, "superseded_by": None}] and missing["legal_conclusion_permitted"]
    none = basis_for([])
    assert (none["grade"], none["legal_conclusion_permitted"], none["rules"]) == (G.GRADE_NO_SUPPORTED_BASIS, False, [])
    down = basis_for(["STR-001"], error="corpus unreadable: boom")
    assert (down["grade"], down["legal_conclusion_permitted"], down["requires_assumed_acknowledgement"]) == (G.GRADE_UNAVAILABLE, False, False)
    print("  [PASS] grades: PROVEN_ONLY · INCLUDES_ASSUMED (needs ack) · NV-only/superseded-only/empty → NO_SUPPORTED_BASIS · unreadable → UNAVAILABLE; superseded and unknown rules are never counted")


def test_a_stored_basis_cannot_be_quietly_edited():
    b = basis_for(["STR-001", "POE-003"])
    assert G.basis_intact(b)
    forged = json.loads(json.dumps(b))
    forged["rules"][0]["evidence_level"] = "PROVEN"
    assert not G.basis_intact(forged), "an evidence level edited after the fact must be detected"
    forged = json.loads(json.dumps(b)); forged["legal_conclusion_permitted"] = True; forged["grade"] = "PROVEN_ONLY"
    assert not G.basis_intact(forged)
    assert not G.basis_intact({"schema": G.BASIS_SCHEMA}) and not G.basis_intact(None) and not G.basis_intact("x")
    legacy = {"PROVEN": ["STR-001"], "NEEDS-VERIFICATION": ["RFI-001"]}
    assert G.basis_by_level(legacy) == legacy and G.basis_by_level(b) == b["by_evidence_level"] and G.basis_by_level(None) == {}
    print("  [PASS] basis_sha256 detects an edited stored basis; readers accept both the object and the v2 plain shape")


# ── reading the corpus: metadata only, fail-closed ───────────────────────────

def _boom(sql):
    raise RuntimeError("SQL access control error: Insufficient privileges to operate on table 'REGULATORY_CORPUS'")


def test_rule_basis_reads_metadata_not_rule_text_and_fails_closed():
    conn = FakeConn()
    b = CoPilotSkills(conn).rule_basis(["STR-001", "POE-003", "RFI-001"])
    sql = next(s for s in conn.log if "REGULATORY_CORPUS WHERE RULE_ID IN" in s)
    assert "RULE_TEXT" not in sql and "MY_SYNTHESIS" not in sql, "the basis needs governance metadata only — never rule text (NV text stays out)"
    assert b["grade"] == G.GRADE_INCLUDES_ASSUMED and b["corpus_version"] == "1.1.0" and b["snapshot_date"] == "2026-09-17"
    down = CoPilotSkills(FakeConn(responders=[("REGULATORY_CORPUS WHERE RULE_ID IN", _boom)])).rule_basis(["STR-001"])
    assert down["grade"] == G.GRADE_UNAVAILABLE and down["legal_conclusion_permitted"] is False and "Insufficient privileges" in down["error"]
    no_summary = CoPilotSkills(FakeConn(responders=[("COUNT(DISTINCT CORPUS_VERSION)", _boom)])).rule_basis(["STR-001"])
    assert no_summary["grade"] == G.GRADE_UNAVAILABLE, "if the corpus version cannot be established nothing may be concluded"
    assert CoPilotSkills(FakeConn()).rule_basis([])["grade"] == G.GRADE_NO_SUPPORTED_BASIS
    print("  [PASS] rule_basis selects governance columns only; an unreadable corpus → UNAVAILABLE (fail-closed, with the reason), never 'unknown'")


# ── the lookup: no legal conclusion without a supported basis ────────────────

ON_TOPIC = "An STR must be filed within seven working days; the filing deadline runs from the date suspicion is formed."


def _on_topic(rows):
    """Fixture rows say something about the question asked. The scope guard (skills/scope_guard.py) withholds rules whose text shares
    almost nothing with the question, so a row whose text is just "text PRV-1" would rightly be refused as an answer."""
    return [{**r, "RULE_TEXT": ON_TOPIC} if str(r.get("RULE_TEXT", "")).startswith("text ") else r for r in rows]


def _lookup(hits, replacing=(), by_id=(), q="What is the STR filing deadline?"):
    conn = FakeConn(responders=[("WHERE rc.RULE_ID =", _on_topic(by_id)), ("REPLACES IS NOT NULL", _on_topic(replacing)),
                                ("SEARCH_PREVIEW", _on_topic(hits)), ("CONTAINS(LOWER", [])])
    return CoPilotSkills(conn).regulatory_lookup_with_basis(q, limit=5)


def test_lookup_no_result_abstains_and_permits_no_legal_conclusion():
    res = _lookup([])
    assert res["rules"] == [] and res["legal_conclusion_permitted"] is False
    assert res["basis"]["grade"] == "NO_SOURCES" and "Abstain" in res["basis"]["warning"]
    assert res["abstain_reason"] == "no PROVEN or ASSUMED rule in the corpus matches the question"
    print("  [PASS] no-result: abstain, legal_conclusion_permitted=False, plain reason")


def test_lookup_assumed_results_permit_a_conclusion_only_with_the_warning():
    res = _lookup([rule_row("ASM-1", "ASSUMED"), rule_row("PRV-1", "PROVEN")])
    assert res["legal_conclusion_permitted"] is True and res["abstain_reason"] is None
    assert res["basis"]["grade"] == "INCLUDES_ASSUMED" and res["basis"]["warning"] and res["basis"]["can_state_as_proven"] is False
    only_proven = _lookup([rule_row("PRV-1", "PROVEN")])
    assert only_proven["basis"]["grade"] == "PROVEN_ONLY" and only_proven["basis"]["can_state_as_proven"] is True
    assert all(r["review"]["verified"] is False for r in res["rules"]), "nothing is shown as independently verified"
    print("  [PASS] ASSUMED: permitted with the mandatory warning and 'cannot be stated as proven'; PROVEN-only is the only clean grade")


def test_lookup_needs_verification_rules_are_never_returned_or_relied_on():
    res = _lookup([rule_row("NV-1", "NEEDS-VERIFICATION"), rule_row("NV-2", "NEEDS-VERIFICATION")])
    assert res["rules"] == [] and res["legal_conclusion_permitted"] is False, "NV rows (even if the database wrongly returned them) support nothing"
    mixed = _lookup([rule_row("NV-1", "NEEDS-VERIFICATION"), rule_row("PRV-1", "PROVEN")])
    assert [r["rule_id"] for r in mixed["rules"]] == ["PRV-1"]
    conn = FakeConn(responders=[("SEARCH_PREVIEW", [])])
    CoPilotSkills(conn).regulatory_lookup_with_basis("anything about money", limit=3)
    for sql in (s for s in conn.log if "REGULATORY_CORPUS" in s and "rc." in s):
        assert "EVIDENCE_LEVEL IN ('PROVEN', 'ASSUMED')" in sql, "every retrieval query excludes NEEDS-VERIFICATION in SQL as well"
    print("  [PASS] NEEDS-VERIFICATION: excluded in every query and again in code; if only NV rows match → no conclusion")


def test_lookup_superseded_rules_are_withheld_and_a_dead_end_abstains():
    res = _lookup([rule_row("OLD-1", "PROVEN", SUPERSEDED_BY="NEW-1")], by_id=[rule_row("NEW-1", "ASSUMED")])
    assert [r["rule_id"] for r in res["rules"]] == ["NEW-1"] and [s["rule_id"] for s in res["superseded"]] == ["OLD-1"]
    assert res["rules"][0]["surfaced_as_successor_of"] == "OLD-1" and res["legal_conclusion_permitted"]
    dead_end = _lookup([rule_row("OLD-1", "PROVEN", SUPERSEDED_BY="GONE")], by_id=[])
    assert dead_end["rules"] == [] and dead_end["legal_conclusion_permitted"] is False
    assert dead_end["abstain_reason"] == "every matching rule is superseded and no current successor exists"
    print("  [PASS] superseded: withheld, successor surfaced; a superseded rule with no current successor → abstain with that reason")


# ── at the decision: the recorder applies the same rules ─────────────────────

def test_filing_with_no_supported_basis_is_refused_and_a_closure_is_recorded_with_a_warning():
    conn = FakeConn()
    msg = _blocked(conn, rules_cited=["RFI-001"])
    assert "No PROVEN or ASSUMED" in msg and not conn.stmts("INSERT")
    out = CoPilotSkills(FakeConn()).alert_disposition_recorder(**recorder_kwargs(
        disposition="NOT_FILE", ai_recommendation="NOT_FILE", rules_cited=["RFI-001"], suspicion_formed_at=_recent(),
        rationale_text="Closed: documented family remittances explain the credits; no onward flow to flagged parties."))
    g = out["provenance"]["defensibility_gate"]
    assert "NO_SUPPORTED_BASIS_FOR_CLOSURE" in g["warning_codes"] and out["provenance"]["regulatory_basis"]["grade"] == "NO_SUPPORTED_BASIS"
    print("  [PASS] FILE on NV-only rules → refused (nothing written); NOT_FILE → recorded with NO_SUPPORTED_BASIS_FOR_CLOSURE and the empty basis stored")


def test_filing_on_a_superseded_only_basis_or_an_unreadable_corpus_is_refused():
    conn = FakeConn(responders=[("REGULATORY_CORPUS WHERE RULE_ID IN",
                                 lambda sql: [{"RULE_ID": "STR-001", "EVIDENCE_LEVEL": "PROVEN", "SOURCE_AUTHORITY": "STATUTE", "REVIEW_STATUS": "AUTHOR_ASSERTED",
                                               "CORPUS_VERSION": "1.1.0", "SNAPSHOT_DATE": "2026-09-11", "LAST_VERIFIED": None, "VERIFIED_BY": None, "SUPERSEDED_BY": "STR-099"}])])
    assert "No PROVEN or ASSUMED" in _blocked(conn, rules_cited=["STR-001"]) and not conn.stmts("INSERT")
    down = FakeConn(responders=[("REGULATORY_CORPUS WHERE RULE_ID IN", _boom)])
    msg = _blocked(down)
    assert "could not be established" in msg and not down.stmts("INSERT"), "an unreadable corpus must not let a filing through"
    print("  [PASS] FILE whose only basis is superseded → refused; FILE while the corpus is unreadable → refused (fail-closed)")


def test_assumed_acknowledgement_is_required_recorded_and_stored_with_the_basis_object():
    conn = FakeConn()
    msg = _blocked(conn, rules_cited=["STR-001", "POE-003"])
    assert "ASSUMED" in msg and "POE-003" in msg and not conn.stmts("INSERT")
    conn = FakeConn()
    out = CoPilotSkills(conn).alert_disposition_recorder(**recorder_kwargs(rules_cited=["STR-001", "POE-003", "RFI-001"], assumed_basis_acknowledged=True, suspicion_formed_at=_recent()))
    meta = out["provenance"]
    rb = meta["regulatory_basis"]
    assert G.basis_intact(rb) and rb["assumed_rule_ids"] == ["POE-003"] and rb["proven_rule_ids"] == ["STR-001"] and rb["excluded"][0]["rule_id"] == "RFI-001"
    assert meta["acknowledgements"]["assumed_basis"] is True and meta["acknowledgements"]["assumed_rule_ids"] == ["POE-003"]
    assert meta["corpus_version"] == rb["corpus_version"] == "1.1.0"
    print("  [PASS] ASSUMED filing: refused (naming the rules) → recorded once acknowledged; the intact basis object + the acknowledgement persist together")


def test_a_supplied_basis_is_compared_never_stored():
    sk = CoPilotSkills(FakeConn())
    good = sk.rule_basis(["STR-001", "RFI-001"])
    out = CoPilotSkills(FakeConn()).alert_disposition_recorder(**recorder_kwargs(regulatory_basis=good, suspicion_formed_at=_recent()))
    assert out["provenance"]["regulatory_basis"]["basis_sha256"] == good["basis_sha256"]
    forged = json.loads(json.dumps(good))
    forged["rules"] = [dict(r, evidence_level="PROVEN") for r in forged["rules"]]
    forged["basis_sha256"] = G._canonical_sha256({k: v for k, v in forged.items() if k != "basis_sha256"})        # an attacker recomputes the hash
    conn = FakeConn()
    msg = _blocked(conn, regulatory_basis=forged)
    assert "does not match the corpus" in msg and not conn.stmts("INSERT"), "a forged (self-consistent) basis must not be persisted"
    print("  [PASS] a supplied basis that does not equal the corpus-derived one (even with a recomputed hash) is refused; only the recorder's own build is stored")


def test_reconstruction_replays_the_basis_and_the_gate():
    sk = CoPilotSkills(FakeConn())
    out = sk.alert_disposition_recorder(**recorder_kwargs(suspicion_formed_at=_recent()))
    meta = dict(out["provenance"], written_by_role="FIU_APP_ROLE")      # the INSERT stamps CURRENT_ROLE() server-side
    row = {"DECISION_ID": "d1", "ALERT_ID": "ALERT-01", "DISPOSITION": "FILE", "RATIONALE_TEXT": "x", "SUSPICION_FORMED_AT": "2026-08-18",
           "META_TEXT": json.dumps(meta), "INTEGRITY_STATUS": "INTACT"}
    rec = CoPilotSkills(FakeConn(responders=[("JOIN FIU_COPILOT.AML.DECISION_LEDGER_INTEGRITY_V", [row])])).reconstruct_decision("d1")
    assert rec["checks"]["regulatory_basis_recorded"]["ok"] is True and rec["checks"]["defensibility_gate_recorded"]["ok"] is True, rec["checks"]
    bad = json.loads(json.dumps(meta)); bad["regulatory_basis"]["grade"] = "PROVEN_ONLY"; bad["regulatory_basis"]["rules"][0]["evidence_level"] = "PROVEN"
    row2 = dict(row, META_TEXT=json.dumps(bad))
    rec2 = CoPilotSkills(FakeConn(responders=[("JOIN FIU_COPILOT.AML.DECISION_LEDGER_INTEGRITY_V", [row2])])).reconstruct_decision("d1")
    assert rec2["checks"]["regulatory_basis_recorded"]["ok"] is False
    bad = json.loads(json.dumps(meta)); bad["defensibility_gate"]["status"] = "BLOCKED"
    rec3 = CoPilotSkills(FakeConn(responders=[("JOIN FIU_COPILOT.AML.DECISION_LEDGER_INTEGRITY_V", [dict(row, META_TEXT=json.dumps(bad))])])).reconstruct_decision("d1")
    assert rec3["checks"]["defensibility_gate_recorded"]["ok"] is False
    legacy = {k: v for k, v in meta.items() if k not in ("defensibility_gate", "acknowledgements")}
    legacy["schema_version"] = "2"; legacy["regulatory_basis"] = {"PROVEN": ["STR-001"]}
    rec4 = CoPilotSkills(FakeConn(responders=[("JOIN FIU_COPILOT.AML.DECISION_LEDGER_INTEGRITY_V", [dict(row, META_TEXT=json.dumps(legacy))])])).reconstruct_decision("d1")
    assert rec4["checks"]["regulatory_basis_recorded"]["ok"] is None and rec4["checks"]["defensibility_gate_recorded"]["ok"] is None
    assert rec4["checks"]["provenance_complete"]["ok"] is True, "a schema-2 row is complete as schema 2 — not reported as missing the v3 keys"
    print("  [PASS] reconstruction: basis + gate intact → ✅; edited basis / edited gate → ❌; a schema-2 row → ⚪ 'predates', still complete as v2")


TESTS = [
    test_basis_object_carries_every_required_field, test_basis_grades_for_every_path, test_a_stored_basis_cannot_be_quietly_edited,
    test_rule_basis_reads_metadata_not_rule_text_and_fails_closed, test_lookup_no_result_abstains_and_permits_no_legal_conclusion,
    test_lookup_assumed_results_permit_a_conclusion_only_with_the_warning, test_lookup_needs_verification_rules_are_never_returned_or_relied_on,
    test_lookup_superseded_rules_are_withheld_and_a_dead_end_abstains,
    test_filing_with_no_supported_basis_is_refused_and_a_closure_is_recorded_with_a_warning,
    test_filing_on_a_superseded_only_basis_or_an_unreadable_corpus_is_refused,
    test_assumed_acknowledgement_is_required_recorded_and_stored_with_the_basis_object, test_a_supplied_basis_is_compared_never_stored,
    test_reconstruction_replays_the_basis_and_the_gate,
]

if __name__ == "__main__":
    raise SystemExit(Runner("Regulatory confidence controls (offline)").run(TESTS))
