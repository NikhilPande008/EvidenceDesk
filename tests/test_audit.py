"""
Ledger resilience (skills/audit.py, scripts/audit_ledger.py, deploy/05_audit_export.sql).

Database RBAC stays the primary protection. These tests cover the NON-DESTRUCTIVE reconciliation and the append-only,
hash-chained audit export, for: LEGACY rows · INTACT rows · TAMPERED rows · missing provenance · DELETED records ·
rows modified-and-rehashed after export · a broken or truncated export chain — and they pin the plain statement of
residual risk (owner-role deletion is NOT claimed impossible).

Offline (pure functions, a scripted fake database, the CLI in plan-only mode).
Usage:  python3 tests/test_audit.py     (or pytest)
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

from _helpers import FakeConn, ROOT, Runner, recorder_kwargs, scan_sql

from skills import CoPilotSkills
from skills import audit as A


def _h(x: str) -> str:
    return hashlib.sha256(x.encode()).hexdigest()


def _complete_meta() -> dict:
    sf = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta = CoPilotSkills(FakeConn()).alert_disposition_recorder(**recorder_kwargs(suspicion_formed_at=sf))["provenance"]
    return dict(meta, written_by_role="FIU_APP_ROLE")


META_OK = json.dumps(_complete_meta())


def row(i: int, *, legacy=False, tampered=False, meta=META_OK, alert="ALERT-01") -> dict:
    if meta is META_OK:                      # successive decisions on one alert know about each other: prior_count rises (equal counts would be a race)
        m = json.loads(META_OK)
        m["decision_sequence"] = {"prior_count": i}
        meta = json.dumps(m)
    stored = None if legacy else _h(f"row-{i}")
    computed = None if legacy else (_h(f"EDITED-{i}") if tampered else stored)
    return {"DECISION_ID": f"d{i}", "ALERT_ID": alert, "DISPOSITION": "FILE", "DECISION_MADE_AT_UTC": f"2026-09-30T10:00:{i:02d}.000000",
            "STORED_HASH": stored, "COMPUTED_HASH": computed, "META_TEXT": None if legacy else meta}


def ids(report, code):
    return next((f["ids"] for f in report["findings"] if f["code"] == code), [])


# ── classification + reconciliation (no export) ──────────────────────────────

def test_classification_legacy_intact_tampered_and_missing_provenance():
    assert A.classify_row(row(1))["integrity"] == A.INTACT and A.classify_row(row(1))["provenance_missing"] == []
    leg = A.classify_row(row(2, legacy=True))
    assert leg["integrity"] == A.LEGACY and leg["provenance_missing"] is None, "legacy rows predate provenance: disclosed, not 'missing'"
    assert A.classify_row(row(3, tampered=True))["integrity"] == A.TAMPERED
    thin = json.loads(META_OK); del thin["defensibility_gate"]; del thin["regulatory_basis"]
    c = A.classify_row(row(4, meta=json.dumps(thin)))
    assert c["integrity"] == A.INTACT and set(c["provenance_missing"]) == {"defensibility_gate", "regulatory_basis"}
    assert A.classify_row(row(5, meta="not json"))["provenance_missing"], "unparseable provenance counts as missing, not as fine"
    both = dict(row(6), COMPUTED_HASH=None)
    assert A.classify_row(both)["integrity"] == A.UNKNOWN, "a hash the view could not recompute is reported, never assumed intact"
    lying = dict(row(7), STORED_HASH=_h("a"), COMPUTED_HASH=_h("b"))
    assert A.classify_row(lying)["integrity"] == A.TAMPERED, "the status follows from the hashes, not from a label"
    print("  [PASS] classification: INTACT · LEGACY_UNHASHED (no 'missing provenance' false alarm) · TAMPERED · incomplete provenance · UNKNOWN")


def test_reconcile_without_an_export_is_honest_about_what_it_cannot_see():
    ok = A.reconcile([row(1), row(2)])
    assert ok["verdict"] == A.VERDICT_CONSISTENT and ok["by_integrity"] == {A.INTACT: 2}
    assert ok["deletion_detectable"] is False and ok["anchor"]["present"] is False, "no export ⇒ deletion is NOT detectable, and the report says so"
    assert any("deleted" in limit.lower() and "export" in limit.lower() for limit in ok["limits"]) and any("not make owner-role deletion impossible" in l for l in ok["limits"])
    legacy = A.reconcile([row(1), row(2, legacy=True)])
    assert legacy["verdict"] == A.VERDICT_ATTENTION and ids(legacy, "LEGACY_UNHASHED_ROWS") == ["d2"]
    tampered = A.reconcile([row(1), row(2, tampered=True)])
    assert tampered["verdict"] == A.VERDICT_COMPROMISED and tampered["tampered_ids"] == ["d2"] and ids(tampered, "TAMPERED_ROW") == ["d2"]
    thin = json.loads(META_OK); del thin["gos"]
    incomplete = A.reconcile([row(1, meta=json.dumps(thin))])
    assert incomplete["verdict"] == A.VERDICT_ATTENTION and incomplete["provenance_incomplete"] == [{"decision_id": "d1", "missing": ["gos"]}]
    empty = A.reconcile([])
    assert empty["verdict"] == A.VERDICT_CONSISTENT and empty["ledger_rows"] == 0
    print("  [PASS] no export: CONSISTENT / ATTENTION (legacy, incomplete provenance) / COMPROMISED (tampered) — and 'deletion not detectable' + residual-risk limits are always stated")


# ── the export chain ─────────────────────────────────────────────────────────

def test_export_chain_is_deterministic_incremental_and_verifiable():
    rows = [row(1), row(2, legacy=True), row(3)]
    first = A.export_records(rows)
    assert [r["SEQ"] for r in first] == [1, 2, 3] and first[0]["PREV_CHAIN_HASH"] == A.GENESIS
    assert first[1]["ROW_HASH"] is None and first[1]["CONTENT_ANCHORED"] is False and first[0]["CONTENT_ANCHORED"] is True
    assert A.export_records(rows) == first, "deterministic"
    assert A.verify_chain(first) == []
    more = rows + [row(4), row(5)]
    second = A.export_records([r for r in more if r["DECISION_ID"] not in {x["DECISION_ID"] for x in first}], previous=first[-1])
    assert [r["SEQ"] for r in second] == [4, 5] and second[0]["PREV_CHAIN_HASH"] == first[-1]["CHAIN_HASH"]
    assert A.verify_chain(first + second) == [], "two export runs form ONE verifiable chain"
    assert A.export_records(more) == first + second, "exporting everything at once gives the identical chain"
    man = A.build_manifest(first + second, exported_by="FIU_AUDIT_ROLE", exported_at="2026-10-01T00:00:00+00:00")
    assert man["count"] == 5 and man["head_chain_hash"] == second[-1]["CHAIN_HASH"] and man["existence_only"] == 1 and man["content_anchored"] == 4
    nd = A.to_ndjson(first + second, man).splitlines()
    assert json.loads(nd[0])["manifest"]["format"] == A.EXPORT_FORMAT and len(nd) == 6
    print("  [PASS] export: deterministic, incremental (two runs = one chain = the same bytes as one run), legacy rows anchored by existence only")


def test_a_tampered_or_truncated_export_is_detected():
    chain = A.export_records([row(i) for i in range(1, 6)])
    edited = json.loads(json.dumps(chain)); edited[2]["DECISION_ID"] = "d-forged"
    assert any("altered" in e for e in A.verify_chain(edited)), "a record edited in place"
    gap = [r for r in chain if r["SEQ"] != 3]
    assert any("sequence gap" in e for e in A.verify_chain(gap)), "a record removed from the middle"
    relinked = json.loads(json.dumps(chain)); relinked[3]["PREV_CHAIN_HASH"] = A.GENESIS
    assert any("does not chain" in e for e in A.verify_chain(relinked))
    assert A.verify_chain(chain[:3]) == [], "a truncated TAIL is internally consistent — it is caught by the ledger comparison (rows 'not yet exported'), not by the chain"
    print("  [PASS] export tamper detection: edited record · removed middle record · broken link; a truncated tail is flagged by reconciliation instead")


# ── reconciliation against the export ────────────────────────────────────────

def test_deleted_modified_and_unexported_records_are_detected_against_the_export():
    ledger = [row(1), row(2, legacy=True), row(3), row(4)]
    anchor = A.export_records(ledger)
    assert A.reconcile(ledger, anchor)["verdict"] == A.VERDICT_ATTENTION       # legacy row present; nothing else wrong
    clean = A.reconcile([r for r in ledger if r["DECISION_ID"] != "d2"] + [], anchor)
    assert clean["deleted_ids"] == ["d2"] and clean["verdict"] == A.VERDICT_COMPROMISED and ids(clean, "DELETED_RECORD") == ["d2"], "a deleted LEGACY row is detected too (existence is anchored)"
    deleted = A.reconcile([ledger[0], ledger[1], ledger[3]], anchor)
    assert deleted["deleted_ids"] == ["d3"] and deleted["verdict"] == A.VERDICT_COMPROMISED and deleted["deletion_detectable"] is True
    # the owner edits a row AND recomputes ROW_HASH so the view says INTACT — only the export can see it
    forged = dict(ledger[2], STORED_HASH=_h("forged"), COMPUTED_HASH=_h("forged"))
    assert A.classify_row(forged)["integrity"] == A.INTACT, "the per-row hash alone is fooled by a re-hashed edit"
    rehashed = A.reconcile([ledger[0], ledger[1], forged, ledger[3]], anchor)
    assert rehashed["modified_since_export_ids"] == ["d3"] and rehashed["verdict"] == A.VERDICT_COMPROMISED
    assert ids(rehashed, "MODIFIED_SINCE_EXPORT") == ["d3"]
    newer = A.reconcile(ledger + [row(5)], anchor)
    assert newer["not_yet_exported_ids"] == ["d5"] and newer["verdict"] == A.VERDICT_ATTENTION and ids(newer, "NOT_YET_EXPORTED") == ["d5"]
    bad_chain = json.loads(json.dumps(anchor)); bad_chain[1]["DECISION_ID"] = "d-forged"
    broken = A.reconcile(ledger, bad_chain)
    assert broken["verdict"] == A.VERDICT_COMPROMISED and broken["deletion_detectable"] is False and ids(broken, "EXPORT_CHAIN_BROKEN") == []
    assert broken["anchor"]["chain_valid"] is False, "an altered export is itself a COMPROMISED finding and is not trusted to prove deletion"
    empty_export = A.reconcile(ledger, [])
    assert empty_export["anchor"]["present"] is True and empty_export["not_yet_exported_ids"] == ["d1", "d2", "d3", "d4"]
    unavailable = A.reconcile(ledger, None, anchor_error="audit export table not available: does not exist")
    assert unavailable["anchor"] == {"present": False, "records": 0, "chain_valid": None, "head": None, "reason": "audit export table not available: does not exist"}
    print("  [PASS] against the export: deleted (incl. legacy) · re-hashed edit (INTACT to the view, caught by the export) · not-yet-exported · altered export · empty export · table unavailable")


# ── SQL ──────────────────────────────────────────────────────────────────────

def test_export_sql_is_insert_only_and_injection_safe():
    from skills.core import _lit
    hostile = "'; DROP TABLE FIU_COPILOT.AUDIT.LEDGER_EXPORT; --"
    recs = A.export_records([dict(row(1), ALERT_ID=hostile), row(2, legacy=True)])
    stmts = A.export_insert_sql(recs, "exp-1", _lit)
    assert len(stmts) == 2 and all(s.startswith("INSERT INTO FIU_COPILOT.AUDIT.LEDGER_EXPORT") for s in stmts)
    n, lits = scan_sql(stmts[0])
    assert n == 1 and hostile in lits, "a hostile alert id round-trips as ONE statement and one literal"
    assert "NULL" in stmts[1] and "FALSE" in stmts[1], "a legacy row is exported with a NULL hash and CONTENT_ANCHORED = FALSE"
    for sql in (A.LEDGER_ROWS_SQL, A.ANCHOR_SQL):
        assert sql.lstrip().upper().startswith("SELECT") and ";" not in sql
    ddl = (ROOT / "deploy/05_audit_export.sql").read_text()
    assert "GRANT SELECT ON TABLE  FIU_COPILOT.AUDIT.LEDGER_EXPORT TO ROLE FIU_APP_ROLE" in ddl
    assert not any(w in ddl.upper() for w in ("GRANT INSERT", "GRANT ALL", "TO ROLE FIU_ADMIN_ROLE")), "only the audit role writes; the ledger owner has no privilege here"
    assert "not WORM" in ddl or "Not WORM" in ddl, "the DDL says plainly what it is not"
    print("  [PASS] export SQL: INSERT-only, hostile values safe, legacy rows NULL-hashed; read queries are single SELECTs; DDL grants the app role SELECT only")


def test_skills_reconciliation_issues_only_selects_and_survives_a_missing_audit_table():
    ledger = [row(1), row(2, legacy=True)]

    def no_table(sql):
        raise RuntimeError("SQL compilation error: Object 'FIU_COPILOT.AUDIT.LEDGER_EXPORT' does not exist or not authorized.")

    conn = FakeConn(responders=[("FROM FIU_COPILOT.AUDIT.LEDGER_EXPORT", no_table), ("LEFT JOIN FIU_COPILOT.AML.DECISION_LEDGER_INTEGRITY_V", ledger)])
    rep = CoPilotSkills(conn).ledger_reconciliation()
    assert rep["verdict"] == A.VERDICT_ATTENTION and rep["anchor"]["present"] is False and "not available" in rep["anchor"]["reason"]
    assert "SQL compilation error" not in rep["anchor"]["reason"], "a raw database error must not be dumped into the report"
    other = CoPilotSkills(FakeConn(responders=[("FROM FIU_COPILOT.AUDIT.LEDGER_EXPORT", lambda s: (_ for _ in ()).throw(RuntimeError("network timeout after 60s " + "x" * 400))),
                                               ("LEFT JOIN FIU_COPILOT.AML.DECISION_LEDGER_INTEGRITY_V", ledger)])).ledger_reconciliation()
    assert other["anchor"]["reason"].startswith("audit export table could not be read") and len(other["anchor"]["reason"]) < 140
    assert conn.log and all(s.lstrip().upper().startswith("SELECT") for s in conn.log), conn.log
    anchor = A.export_records(ledger)
    conn2 = FakeConn(responders=[("FROM FIU_COPILOT.AUDIT.LEDGER_EXPORT", anchor), ("LEFT JOIN FIU_COPILOT.AML.DECISION_LEDGER_INTEGRITY_V", [ledger[0]])])
    assert CoPilotSkills(conn2).ledger_reconciliation()["deleted_ids"] == ["d2"]
    print("  [PASS] CoPilotSkills.ledger_reconciliation(): SELECT-only; a missing audit table is reported (not hidden); a deleted row is found through the real code path")


# ── the CLI ──────────────────────────────────────────────────────────────────

def test_audit_cli_cannot_mutate_the_ledger_and_is_plan_only_by_default():
    src = (ROOT / "scripts/audit_ledger.py").read_text()
    tree = ast.parse(src)
    literals = {a.value for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "execute"
                for a in n.args if isinstance(a, ast.Constant) and isinstance(a.value, str)}
    assert literals <= {"BEGIN", "COMMIT", "ROLLBACK"}, f"the CLI may only run builder-made SELECT/INSERT plus transaction control: {literals}"
    assert "DECISION_LEDGER" not in "".join(n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.lstrip().upper().startswith(("UPDATE", "DELETE", "INSERT")))
    env = {k: v for k, v in os.environ.items() if not k.startswith("SNOWFLAKE_")}
    env["FIU_SKIP_DOTENV"] = "1"
    run = lambda *a: subprocess.run([sys.executable, str(ROOT / "scripts/audit_ledger.py"), *a], capture_output=True, text=True, env=env, cwd=ROOT, timeout=60)  # noqa: E731
    plan = run("provision")
    assert plan.returncode == 0 and "PLAN ONLY" in plan.stdout and "--apply" in plan.stdout
    for cmd in (("report",), ("export",), ("export", "--apply")):
        r = run(*cmd)
        out = r.stdout + r.stderr
        assert r.returncode != 0 and "Missing Snowflake configuration" in out, (cmd, out[:200])
        assert "Traceback" not in out, "a missing configuration is one sentence, not a stack trace"
    print("  [PASS] audit CLI: executes only builder SELECT/INSERT + transaction control; 'provision' is plan-only; without credentials every command fails with one secret-free sentence")


def test_two_decisions_written_against_the_same_earlier_state_are_reported_as_concurrent_and_nothing_else_is():
    def seq(i, alert, prior, **kw):
        m = json.loads(META_OK)
        m["decision_sequence"] = {"prior_count": prior}
        return row(i, alert=alert, meta=json.dumps(m), **kw)
    race = [seq(1, "ALERT-01", 0), seq(2, "ALERT-01", 0), seq(3, "ALERT-02", 0)]
    assert A.find_concurrent_decisions(race) == [{"alert_id": "ALERT-01", "prior_count": 0, "decision_ids": ["d1", "d2"]}]
    rep = A.reconcile(race)
    f = next(f for f in rep["findings"] if f["code"] == "CONCURRENT_DECISIONS")
    assert f["severity"] == "ATTENTION" and f["ids"] == ["d1", "d2"] and "cannot prevent" in f["detail"] and rep["verdict"] == A.VERDICT_ATTENTION
    ordered = [seq(1, "ALERT-01", 0), seq(2, "ALERT-01", 1), seq(3, "ALERT-01", 2)]
    assert A.find_concurrent_decisions(ordered) == [] and "CONCURRENT_DECISIONS" not in {f["code"] for f in A.reconcile(ordered)["findings"]}
    legacy_like = [row(1, meta=json.dumps({"schema_version": "3"})), row(2, meta=json.dumps({"schema_version": "3"}))]
    assert A.find_concurrent_decisions(legacy_like) == [], "rows from before the field existed are never grouped: a legacy ledger of repeat decisions is not a race"
    assert A.find_concurrent_decisions([{"ALERT_ID": "A", "DECISION_ID": "x", "META_TEXT": "{not json"}, {"ALERT_ID": "A", "DECISION_ID": "y", "META_TEXT": None}]) == []
    print("  [PASS] two rows of one alert with the same prior_count are CONCURRENT_DECISIONS (attention); rising counts, legacy rows and unreadable metadata are not")


def test_the_recorder_writes_the_decision_sequence_into_every_new_row():
    from skills import CoPilotSkills
    first = CoPilotSkills(FakeConn()).alert_disposition_recorder(**recorder_kwargs())["provenance"]
    assert first["decision_sequence"] == {"prior_count": 0}
    prior = [{"DECISION_ID": "earlier", "DISPOSITION": "NOT_FILE", "DECISION_MAKER_ID": "PO-1", "DECISION_MADE_AT": "2026-09-30"}]
    second = CoPilotSkills(FakeConn([("FROM FIU_COPILOT.AML.DECISION_LEDGER WHERE ALERT_ID", prior)])).alert_disposition_recorder(
        **recorder_kwargs(supersede_reason="The documents produced on 2026-09-30 contradict the earlier closure."))["provenance"]
    assert second["decision_sequence"] == {"prior_count": 1} and second["supersession"]["supersedes_decision_id"] == "earlier"
    print("  [PASS] a first decision records prior_count 0, a decision that follows one records 1: this is what lets the reconciliation see a race")


TESTS = [
    test_classification_legacy_intact_tampered_and_missing_provenance, test_reconcile_without_an_export_is_honest_about_what_it_cannot_see,
    test_export_chain_is_deterministic_incremental_and_verifiable, test_a_tampered_or_truncated_export_is_detected,
    test_deleted_modified_and_unexported_records_are_detected_against_the_export, test_export_sql_is_insert_only_and_injection_safe,
    test_skills_reconciliation_issues_only_selects_and_survives_a_missing_audit_table,
    test_audit_cli_cannot_mutate_the_ledger_and_is_plan_only_by_default,
    test_two_decisions_written_against_the_same_earlier_state_are_reported_as_concurrent_and_nothing_else_is,
    test_the_recorder_writes_the_decision_sequence_into_every_new_row,
]

if __name__ == "__main__":
    raise SystemExit(Runner("Ledger resilience: reconciliation + audit export (offline)").run(TESTS))
