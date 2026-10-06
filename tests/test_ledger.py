"""
Ledger integrity, provenance and write-path enforcement (Critical finding #2).

Offline: a recording FakeConn captures every SQL statement the recorder issues.
Live proof of the same properties (denied UPDATE/DELETE, hash reproducibility on the STORED row):
tests/test_live_e2e.py + deploy/04_verify_ledger_rbac.sql.

Usage:  python3 tests/test_ledger.py     (or pytest)
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from _helpers import (FakeConn, Runner, ROOT, case_context, fixture, recorder_kwargs, skills)

DDL = (ROOT / "domain/corpus/export/ddl/regulatory_corpus.sql").read_text()


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _sk(conn=None, **kw):
    from skills import CoPilotSkills
    return CoPilotSkills(conn or FakeConn(**kw))


def _blocked(conn, **over):
    from skills.ledger import LedgerBlocked
    try:
        _sk(conn).alert_disposition_recorder(**recorder_kwargs(**over))
    except LedgerBlocked as e:
        return str(e)
    raise AssertionError("expected LedgerBlocked")


# ── hash definition ──────────────────────────────────────────────────────────

def test_hash_expression_is_verbatim_in_the_ddl_view():
    from skills.ledger import INTEGRITY_VIEW_SQL
    assert _norm(INTEGRITY_VIEW_SQL) in _norm(DDL), "DDL integrity view diverged from skills/ledger.py"
    print("  [PASS] DECISION_LEDGER_INTEGRITY_V in the DDL is byte-for-byte the view the code defines")


def test_insert_embeds_the_same_hash_expression():
    from skills.ledger import HASH_EXPR
    conn = FakeConn()
    _sk(conn).alert_disposition_recorder(**recorder_kwargs())
    insert = _norm(conn.stmts("INSERT")[0])
    assert _norm(HASH_EXPR) in insert, "INSERT must compute ROW_HASH with the shared HASH_EXPR"
    assert "ROW_HASH" in insert and "METADATA_JSON" in insert
    print("  [PASS] recorder INSERT computes ROW_HASH with the same expression the integrity view uses")


def test_hash_covers_every_decision_column():
    from skills.ledger import HASH_EXPR
    body = DDL[DDL.index("CREATE TABLE IF NOT EXISTS DECISION_LEDGER"):]
    body = body[:body.index("PK_DECISION_LEDGER")]
    cols = {m.group(1).upper() for m in re.finditer(r"^\s{4}([A-Z_]+)\s+(?:VARCHAR|TIMESTAMP_TZ|NUMBER|TEXT|VARIANT)", body, re.M)}
    excluded = {"CREATED_AT", "ROW_HASH"}
    missing = [c for c in sorted(cols - excluded) if c not in HASH_EXPR]
    assert cols and not missing, f"decision columns not covered by the row hash: {missing}"
    print(f"  [PASS] row hash covers all {len(cols - excluded)} decision columns (excludes only CREATED_AT, ROW_HASH)")


def test_python_only_hash_is_gone():
    from skills import CoPilotSkills
    assert not hasattr(CoPilotSkills, "_decision_row_hash")
    assert "SHA2(\n--" not in DDL and "-- SELECT\n--     DECISION_ID" not in DDL, "old commented, irreproducible tamper query must be gone"
    print("  [PASS] irreproducible Python hash + commented SQL tamper query removed")


# ── write path ───────────────────────────────────────────────────────────────

def test_recorder_is_insert_only_and_transactional():
    conn = FakeConn()
    out = _sk(conn).alert_disposition_recorder(**recorder_kwargs())
    kinds = [s.lstrip().split()[0].upper() for s in conn.log]
    assert kinds.index("BEGIN") < kinds.index("INSERT") < len(kinds) - 2 and kinds[-1] == "COMMIT", kinds
    assert kinds[-2] == "SELECT", "integrity re-check (hash recomputed from the STORED row) runs before COMMIT"
    assert not any(k in ("UPDATE", "DELETE", "TRUNCATE", "DROP", "ALTER", "MERGE") for k in kinds), kinds
    assert out["status"] == "recorded" and len(out["row_hash"]) == 64
    print(f"  [PASS] recorder statements {kinds}: INSERT only, hash re-checked from stored row before COMMIT")


def test_hash_mismatch_rolls_back_and_raises():
    from skills.ledger import LedgerWriteError
    conn = FakeConn(integrity="TAMPERED")
    try:
        _sk(conn).alert_disposition_recorder(**recorder_kwargs())
        raise AssertionError("must raise")
    except LedgerWriteError as e:
        assert "rolled back" in str(e)
    kinds = [s.lstrip().split()[0].upper() for s in conn.log]
    assert "ROLLBACK" in kinds and "COMMIT" not in kinds, kinds
    conn2 = FakeConn(integrity=None)     # row not found after insert
    try:
        _sk(conn2).alert_disposition_recorder(**recorder_kwargs())
        raise AssertionError("must raise")
    except LedgerWriteError:
        pass
    print("  [PASS] hash not reproducible from the stored row → ROLLBACK, never COMMIT")


def test_db_error_is_not_swallowed_and_rolls_back():
    from skills.ledger import LedgerWriteError

    class Boom(FakeConn):
        def respond(self, sql):
            if sql.lstrip().upper().startswith("INSERT"):
                raise RuntimeError("SQL access control error: Insufficient privileges to operate on table 'DECISION_LEDGER'")
            return super().respond(sql)
    conn = Boom()
    try:
        _sk(conn).alert_disposition_recorder(**recorder_kwargs())
        raise AssertionError("must raise")
    except LedgerWriteError as e:
        assert "Insufficient privileges" in str(e)
    assert "ROLLBACK" in [s.lstrip().split()[0].upper() for s in conn.log]
    assert len(conn.stmts("INSERT")) == 1, "no silent second attempt / degraded fallback insert"
    print("  [PASS] insert error surfaces (no silent metadata-less fallback insert) and rolls back")


def test_joins_caller_transaction_instead_of_committing_it():
    conn = FakeConn(in_txn=True)
    _sk(conn).alert_disposition_recorder(**recorder_kwargs())
    kinds = [s.lstrip().split()[0].upper() for s in conn.log]
    assert "BEGIN" not in kinds and "COMMIT" not in kinds and "ROLLBACK" not in kinds, kinds
    print("  [PASS] inside a caller's transaction the recorder neither BEGINs nor COMMITs (test rollback works)")


def test_app_never_updates_alerts_or_ledger():
    """No UPDATE/DELETE/MERGE/TRUNCATE SQL anywhere in the runtime code."""
    pat = re.compile(r"""["'`]\s*(?:UPDATE|DELETE\s+FROM|MERGE\s+INTO|TRUNCATE)\b|\n\s*(?:UPDATE|DELETE\s+FROM|TRUNCATE\s+TABLE)\s+\S""", re.I)
    for f in ("skills/core.py", "skills/ledger.py", "skills/governance.py", "skills/grounding.py", "streamlit_app.py"):
        text = (ROOT / f).read_text()
        hits = [m.group(0).strip()[:40] for m in pat.finditer(text)]
        assert not hits, f"{f}: mutating SQL found: {hits}"
    print("  [PASS] no UPDATE/DELETE/MERGE/TRUNCATE SQL in runtime code (ALERT_STATUS is derived, not updated)")


# ── enforcement at the write layer ───────────────────────────────────────────

def test_file_requires_case_context_and_runs_gate_on_recorded_text():
    conn = FakeConn()
    msg = _blocked(conn, case_context=None)
    assert "case_context" in msg and conn.log == [], "blocked before touching the database"
    bad = fixture("gos_hallucination.txt")
    msg = _blocked(conn, rationale_text=bad)
    assert "evidence gate" in msg and "amount" in msg and conn.log == []
    print("  [PASS] FILE without case_context / with fabricated facts → blocked at the recorder, 0 SQL issued")


def test_non_ready_gos_needs_written_override_and_it_is_recorded():
    conn = FakeConn()
    q = {"status": "NEEDS_MANUAL_REVIEW", "quality_score": 0, "hard_gate_passed": False, "ai_output_valid": False}
    msg = _blocked(conn, gos_quality=q)
    assert "override_reason" in msg and conn.log == []
    out = _sk(conn).alert_disposition_recorder(**recorder_kwargs(
        gos_quality=q, override_reason="AI quality check unavailable; I reviewed every fact against the statement myself."))
    meta = out["provenance"]
    assert meta["override_reason"].startswith("AI quality check") and meta["gos"]["status"] == "NEEDS_MANUAL_REVIEW"
    print("  [PASS] non-READY GoS: FILE needs a written override_reason; status + reason land in the ledger")


def test_ai_disagreement_requires_override_reason():
    conn = FakeConn()
    msg = _blocked(conn, disposition="NOT_FILE", ai_recommendation="FILE",
                   rationale_text="Closing: customer documented all credits as family remittances (invoice on file).")
    assert "differs from the AI recommendation" in msg and conn.log == []
    out = _sk(conn).alert_disposition_recorder(**recorder_kwargs(
        disposition="NOT_FILE", ai_recommendation="FILE",
        rationale_text="Closing: customer documented all credits as family remittances (invoice on file).",
        override_reason="Hospital invoice and KYC-linked family senders verified; no flagged counterparty."))
    assert out["provenance"]["override"] is True
    ok = _sk(conn).alert_disposition_recorder(**recorder_kwargs(
        disposition="DEFERRED", ai_recommendation="FILE", rationale_text="Awaiting re-KYC documents from branch."))
    assert ok["provenance"]["override"] is False
    print("  [PASS] contradicting the AI needs a written reason (recorded); DEFERRED is never an override")


def test_unverified_assertions_need_acknowledgement():
    conn = FakeConn()
    text = fixture("gos_good.txt") + "\nThe beneficiary has known links to organised crime networks."
    msg = _blocked(conn, rationale_text=text)
    assert "cannot be verified" in msg and conn.log == []
    out = _sk(conn).alert_disposition_recorder(**recorder_kwargs(rationale_text=text, unverified_claims_acknowledged=True))
    assert out["provenance"]["unverified_claims_acknowledged"] is True
    assert out["provenance"]["gos"]["unverified_assertions"], "the labelled assertions are stored with the decision"
    print("  [PASS] unverifiable third-party assertions block FILE until acknowledged; acknowledgement is recorded")


# ── provenance completeness ──────────────────────────────────────────────────

def test_every_row_carries_full_reconstruction_provenance():
    from skills.ledger import REQUIRED_PROVENANCE_KEYS
    conn = FakeConn()
    out = _sk(conn).alert_disposition_recorder(**recorder_kwargs(
        evidence_txn_ids=None, model_name="llama3.3-70b"))
    meta = out["provenance"]
    missing = [k for k in REQUIRED_PROVENANCE_KEYS if k != "written_by_role" and meta.get(k) is None]
    assert not missing, f"provenance keys missing/null: {missing}"
    rb = meta["regulatory_basis"]
    assert meta["corpus_version"] == "1.1.0" and rb["by_evidence_level"].get("PROVEN") == ["STR-001"]
    assert rb["by_evidence_level"].get("NEEDS-VERIFICATION") == ["RFI-001"], "NV citations are labelled, not hidden"
    assert rb["schema"] == "regulatory_basis/1" and rb["corpus_version"] == "1.1.0" and rb["legal_conclusion_permitted"] is True
    assert meta["schema_version"] == "3" and meta["defensibility_gate"]["status"] in ("PASS", "PASS_WITH_WARNINGS"), meta["defensibility_gate"]["status"]
    assert len(meta["evidence_snapshot_sha256"]) == 64 and meta["model_name"] == "llama3.3-70b"
    assert meta["evidence_txn_ids"] == ["TXN-001"], meta["evidence_txn_ids"]      # cited by triggered factors ∩ real txns
    assert "written_by_role" in _norm(conn.stmts("INSERT")[0]), "role is stamped server-side via CURRENT_ROLE()"
    print("  [PASS] provenance complete: AI rec, override, corpus version, PROVEN/ASSUMED/NV basis, model, "
          "prompts, evidence IDs + snapshot hash, GoS gate result, server-side role")


def test_no_ai_run_is_recorded_explicitly_not_as_null():
    conn = FakeConn()
    out = _sk(conn).alert_disposition_recorder(**recorder_kwargs(
        disposition="DEFERRED", ai_recommendation=None, poe_assessment=[], gos_quality=None,
        rationale_text="Awaiting re-KYC documents from branch before deciding.", case_context=None))
    meta = out["provenance"]
    assert meta["ai_recommendation"] == "NOT_RUN" and meta["model_name"] == "NOT_RUN"
    print("  [PASS] decisions made without AI record ai_recommendation/model_name = NOT_RUN (no silent nulls)")


def test_evidence_snapshot_detects_changed_transactions():
    from skills.ledger import evidence_snapshot_sha256
    t = case_context()["transactions"]
    h = evidence_snapshot_sha256(t)
    assert h == evidence_snapshot_sha256(list(reversed(t))), "order-insensitive"
    t2 = [dict(x) for x in t]; t2[0]["amount_inr"] += 1
    assert evidence_snapshot_sha256(t2) != h
    print("  [PASS] evidence snapshot hash is order-insensitive and changes if any transaction changes")


def test_provenance_model_is_the_model_that_actually_answered():
    calls = []

    class Conn(FakeConn):
        def respond(self, sql):
            calls.append(sql)
            if "SNOWFLAKE.CORTEX.COMPLETE('llama3.3-70b'" in sql:
                raise RuntimeError("model llama3.3-70b is not supported in this region")
            if "SNOWFLAKE.CORTEX.COMPLETE" in sql:
                return [{"RESPONSE": "ok"}]
            return super().respond(sql)
    sk = _sk(Conn())
    assert sk._cortex_complete("hi") == "ok"
    assert sk.last_model_used == "llama3.1-8b", sk.last_model_used
    print("  [PASS] fallback model use is recorded truthfully (last_model_used = llama3.1-8b)")


# ── SLA ──────────────────────────────────────────────────────────────────────

def test_sla_counts_working_days_not_calendar_proxy():
    from skills.ledger import sla_days_remaining, working_days_elapsed
    fri, mon = "2026-09-25T10:00:00+05:30", "2026-09-28T10:00:00+05:30"
    assert working_days_elapsed(fri, mon) == 1                      # Fri→Mon is ONE working day
    assert working_days_elapsed("2026-09-26", "2026-09-28") == 1    # Sat→Mon
    assert sla_days_remaining(fri, fri) == 7
    assert sla_days_remaining("2026-09-14", "2026-09-24") == -1     # 8 WD elapsed → overdue by 1
    assert sla_days_remaining(datetime(2026, 9, 1, tzinfo=timezone.utc), datetime(2026, 9, 3, tzinfo=timezone.utc)) == 5
    print("  [PASS] SLA = 7 − elapsed Mon–Fri working days (replaces ceil(days×5/7) proxy)")


def test_verification_never_executes_destructive_statements():
    """INCIDENT 2026-09-30: a verification that ran TRUNCATE + DROP as 'FIU_APP_ROLE' truncated and dropped the live
    ledger, because default secondary roles (ALL) made the session also hold the owner role. Verification must only
    use statements that are harmless even when the check FAILS."""
    import re
    def strip_sql_comments(t):
        return re.sub(r"--[^\n]*", "", t)
    verify = strip_sql_comments((ROOT / "deploy/04_verify_ledger_rbac.sql").read_text())
    assert not re.search(r"\b(TRUNCATE|DROP|ALTER)\s+(TABLE|VIEW|SCHEMA|DATABASE)\b", verify, re.I), "verify SQL must not execute TRUNCATE/DROP/ALTER"
    for m in re.finditer(r"\b(UPDATE\s+\S+\s+SET[^;]*|DELETE\s+FROM\s+\S+[^;]*);", verify, re.I | re.S):
        assert re.search(r"WHERE\s+1\s*=\s*0", m.group(0), re.I), f"mutation in verify SQL must be a no-op (WHERE 1 = 0): {m.group(0)[:60]}"
    assert "USE SECONDARY ROLES NONE" in verify and "'%\"roles\":\"\"%'" in verify, "verify must isolate the app role and FAIL if secondary roles are active"
    live = strip_sql_comments((ROOT / "tests/test_live_e2e.py").read_text() + (ROOT / "tests/test_skills_smoke.py").read_text())
    assert not re.search(r"[\"']\s*(TRUNCATE\s+TABLE|DROP\s+TABLE|ALTER\s+TABLE)[^\"']*DECISION_LEDGER", live, re.I), \
        "live tests must not execute TRUNCATE/DROP/ALTER against the ledger"
    print("  [PASS] RBAC verification (SQL + pytest) executes only harmless statements: no TRUNCATE/DROP/ALTER; UPDATE/DELETE are WHERE 1=0; secondary roles must be NONE")


def test_explicit_role_isolates_secondary_roles():
    """connect_from_env(role=…) must issue USE SECONDARY ROLES NONE; without an explicit role it must not."""
    import os
    import snowflake.connector as sc
    from skills import connection as c
    executed = []

    class Cur:
        def execute(self, s): executed.append(s)
        def close(self): pass

    class Conn:
        def cursor(self): return Cur()
        def close(self): executed.append("<closed>")
    real = sc.connect
    sc.connect = lambda **kw: Conn()
    from _helpers import scoped_env
    try:
        with scoped_env(SNOWFLAKE_ACCOUNT="a", SNOWFLAKE_USER="u", SNOWFLAKE_PASSWORD="p", SNOWFLAKE_ROLE=None):
            c.connect_from_env(role="FIU_APP_ROLE")
            assert executed == ["USE SECONDARY ROLES NONE"], executed
            executed.clear()
            c.connect_from_env()
            assert executed == [], "no explicit role → the user's default behaviour is left alone"
            os.environ["SNOWFLAKE_ROLE"] = "FIU_APP_ROLE"
            c.connect_from_env()
            assert executed == ["USE SECONDARY ROLES NONE"], "SNOWFLAKE_ROLE counts as an explicit role"
    finally:
        sc.connect = real
    print("  [PASS] an explicit role (arg or SNOWFLAKE_ROLE) issues USE SECONDARY ROLES NONE — least privilege cannot be silently widened")

PRIOR_ROW = {"DECISION_ID": "prev-1", "DISPOSITION": "FILE", "DECISION_MAKER_ID": "PO-A", "DECISION_MADE_AT": "2026-08-18 10:00:00"}
PRIOR_SQL = "FROM FIU_COPILOT.AML.DECISION_LEDGER WHERE ALERT_ID"


def test_a_second_decision_on_an_alert_needs_a_reason_and_both_rows_stay():
    first = _sk(FakeConn()).alert_disposition_recorder(**recorder_kwargs())
    assert "supersession" not in first["provenance"] and "REPEAT_DECISION_NEEDS_REASON" not in [c["code"] for c in first["gate"]["conditions"]]
    conn = FakeConn(responders=[(PRIOR_SQL, [PRIOR_ROW])])
    msg = _blocked(conn)
    assert "already has 1 recorded decision" in msg and not conn.stmts("INSERT"), "refused: nothing was written"
    out = _sk(conn).alert_disposition_recorder(**recorder_kwargs(supersede_reason="New KYC documents received on 2026-08-20 change the assessment."))
    sup = out["provenance"]["supersession"]
    assert (sup["prior_count"], sup["supersedes_decision_id"], sup["prior_decision_ids"], sup["prior_dispositions"]) == (1, "prev-1", ["prev-1"], ["FILE"])
    assert sup["reason"] == "New KYC documents received on 2026-08-20 change the assessment."
    assert out["gate"]["acknowledgements"]["supersede_reason_recorded"] is True and len(conn.stmts("INSERT")) == 1
    assert not conn.stmts("UPDATE") and not conn.stmts("DELETE"), "the earlier decision is never touched"
    print("  [PASS] ledger: a repeat decision is refused without a reason (nothing written); with one it records the earlier decision ids and the reason; no UPDATE/DELETE")


def test_the_earlier_decisions_are_read_by_the_recorder_never_taken_from_the_caller():
    import inspect
    params = inspect.signature(_sk().alert_disposition_recorder).parameters
    assert "prior_decisions" not in params and "supersede_reason" in params, "the caller supplies a reason, not the fact that there is an earlier decision"
    # a caller that says nothing about earlier decisions is still held to the ledger's own record
    assert "already has" in _blocked(FakeConn(responders=[(PRIOR_SQL, [PRIOR_ROW, {**PRIOR_ROW, "DECISION_ID": "prev-0", "DISPOSITION": "DEFERRED"}])]))
    print("  [PASS] ledger: the recorder reads earlier decisions itself; the caller can only supply the reason")


def test_an_unreadable_ledger_blocks_the_write_instead_of_assuming_there_is_no_earlier_decision():
    def boom(sql):
        raise RuntimeError("SQL access control error: Insufficient privileges on 'DECISION_LEDGER'")
    conn = FakeConn(responders=[(PRIOR_SQL, boom)])
    msg = _blocked(conn)
    assert "could not be read" in msg and "Insufficient" not in msg and "DECISION_LEDGER" not in msg, "plain message, no SQL or object names"
    assert not conn.stmts("INSERT")
    print("  [PASS] ledger: if earlier decisions cannot be read, nothing is recorded and the message names no object or SQL")

def test_recording_the_ai_draft_unchanged_needs_adoption_and_an_edited_draft_does_not():
    from skills.ledger import text_sha256
    text = fixture("gos_good.txt").strip()                    # the recorder strips the text it hashes, and so does the UI before it sends the draft's fingerprint
    unchanged = {"ai_draft_generated": True, "ai_draft_sha256": text_sha256(text)}
    conn = FakeConn()
    msg = _blocked(conn, feedback=unchanged, rationale_text=text)
    assert "AI's draft, unchanged" in msg and not conn.stmts("INSERT")
    padded = _sk(FakeConn()).alert_disposition_recorder(**recorder_kwargs(feedback=unchanged, rationale_text="  " + text + "\n", ai_draft_adoption_acknowledged=True))
    assert padded["provenance"]["feedback"]["ai_draft"]["adopted_verbatim"] is True, "leading/trailing whitespace is not an edit"
    out = _sk(conn).alert_disposition_recorder(**recorder_kwargs(feedback=unchanged, rationale_text=text, ai_draft_adoption_acknowledged=True))
    assert out["provenance"]["feedback"]["ai_draft"] == {"generated": True, "adopted_verbatim": True}
    assert out["gate"]["acknowledgements"]["ai_draft_adoption"] is True
    edited = _sk(FakeConn()).alert_disposition_recorder(**recorder_kwargs(feedback={"ai_draft_generated": True, "ai_draft_sha256": text_sha256(text + " (edited)")}, rationale_text=text))
    assert edited["provenance"]["feedback"]["ai_draft"]["adopted_verbatim"] is False and "ai_draft_adoption" not in edited["gate"]["acknowledgements"]
    claimed_only = _sk(FakeConn()).alert_disposition_recorder(**recorder_kwargs(feedback={"ai_draft_generated": True}, rationale_text=text))
    assert claimed_only["provenance"]["feedback"]["ai_draft"]["adopted_verbatim"] is None, "no fingerprint, no claim of verbatim adoption"
    print("  [PASS] ledger: the AI's draft recorded unchanged needs the officer's adoption and is stored as adopted verbatim; an edited draft is not")


TESTS = [
    test_hash_expression_is_verbatim_in_the_ddl_view, test_insert_embeds_the_same_hash_expression,
    test_hash_covers_every_decision_column, test_python_only_hash_is_gone,
    test_recorder_is_insert_only_and_transactional, test_hash_mismatch_rolls_back_and_raises,
    test_db_error_is_not_swallowed_and_rolls_back, test_joins_caller_transaction_instead_of_committing_it,
    test_app_never_updates_alerts_or_ledger,
    test_file_requires_case_context_and_runs_gate_on_recorded_text,
    test_non_ready_gos_needs_written_override_and_it_is_recorded,
    test_ai_disagreement_requires_override_reason, test_unverified_assertions_need_acknowledgement,
    test_every_row_carries_full_reconstruction_provenance, test_no_ai_run_is_recorded_explicitly_not_as_null,
    test_evidence_snapshot_detects_changed_transactions, test_provenance_model_is_the_model_that_actually_answered,
    test_sla_counts_working_days_not_calendar_proxy,
    test_verification_never_executes_destructive_statements, test_explicit_role_isolates_secondary_roles,
    test_a_second_decision_on_an_alert_needs_a_reason_and_both_rows_stay, test_the_earlier_decisions_are_read_by_the_recorder_never_taken_from_the_caller,
    test_an_unreadable_ledger_blocks_the_write_instead_of_assuming_there_is_no_earlier_decision,
    test_recording_the_ai_draft_unchanged_needs_adoption_and_an_edited_draft_does_not,
]

if __name__ == "__main__":
    raise SystemExit(Runner("Ledger integrity / provenance / write-path tests (no Snowflake required)").run(TESTS))
