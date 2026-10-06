"""
Operational health / proof checks (scripts/health_check.py, deploy/06_health.sql) — offline, driven by a scripted fake database.

What is proven:
  * every check lands in exactly one of HEALTHY / UNAVAILABLE / UNVERIFIED, and the line between them is the one the documentation draws:
    a property shown to hold is HEALTHY; shown NOT to hold (drift, tampering, not ACTIVE, behind the source) is UNAVAILABLE; anything the
    check could not establish — a statement the role cannot run, legacy rows, a deletion witness that is not provisioned, a probe not
    asked for, what Snowsight rendered — is UNVERIFIED, and an UNVERIFIED result is NEVER summarised as HEALTHY;
  * the checks are READ-ONLY: one gate refuses anything but SELECT / SHOW / DESC / LIST / WITH and a fixed GET into a temp directory, and
    every statement issued across every scenario passes it;
  * what "least privilege" means is tied to the artifacts: the expected grant set equals deploy/03_grants.sql, and the SQL pack equals both.

Usage:  python3 tests/test_health.py     (or pytest)
"""

from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from _helpers import ROOT, Runner

sys.path.insert(0, str(ROOT / "scripts"))
import health_check as H  # noqa: E402
from skills import audit as A  # noqa: E402
from test_audit import row, _h  # noqa: E402

APP, ADMIN, DB, WH = H.APP, H.ADMIN, H.DB, H.WH
LIVE_URI = f"snow://streamlit/{DB}.AML.FIU_AML_COPILOT/versions/live/"
MANIFEST = yaml.safe_load((ROOT / "domain/corpus/manifest.yaml").read_text())


# ── a scripted fake database ─────────────────────────────────────────────────

class _Cur:
    def __init__(self, c):
        self.c, self.description, self._rows = c, None, []

    def execute(self, sql, *a):
        self.c.log.append(" ".join(sql.split()))
        self.description, self._rows = None, []
        if sql.lstrip().upper().startswith("GET "):
            m = re.search(r"file://(\S+)$", sql.strip())
            self.c.on_get(sql, m.group(1))
            self._rows = [("file", "DOWNLOADED")]
            return self
        for needle, value in self.c.script:
            if needle in sql:
                if isinstance(value, Exception):
                    raise value
                rows = value(sql) if callable(value) else value
                if rows:
                    self.description = [(k,) for k in rows[0]]
                    self._rows = [tuple(r.values()) for r in rows]
                else:
                    self.description = [("name",)]
                return self
        raise AssertionError(f"unexpected statement in a health check: {sql[:100]}")

    def fetchall(self):
        return self._rows

    def close(self):
        pass


class FakeDB:
    def __init__(self, script, files=None):
        self.script, self.log, self.files = script, [], files or {}

    def cursor(self, *a, **k):
        return _Cur(self)

    def on_get(self, sql, directory):
        if isinstance(self.files.get("__error__"), Exception):
            raise self.files["__error__"]
        if "SEMANTIC_STAGE" in sql:
            (Path(directory) / "semantic_model.yaml").write_bytes(self.files.get("semantic_model.yaml", (ROOT / "domain/corpus/export/semantic_model.yaml").read_bytes()))
            return
        for rel in H._app_files(ROOT):
            name = Path(rel).name if rel.startswith("skills/") else rel
            if self.files.get(name) == "ABSENT":
                continue
            (Path(directory) / name).write_bytes(self.files.get(name, (ROOT / rel).read_bytes()))
        (Path(directory) / "pyproject.toml").write_text("[project]\n")
        (Path(directory) / "config.toml").write_text("[server]\n")


PLATFORM = [("OWNERSHIP", "STREAMLIT", f"{DB}.AML.FIU_AML_COPILOT"), ("OWNERSHIP", "STAGE", f'{DB}.AML."Streamlit_internal_0000"'),
            ("USAGE", "SERVICE", f"{DB}.AML.STPLATSTREAMLIT1"), ("MONITOR", "SERVICE", f"{DB}.AML.STPLATSTREAMLIT1"),
            ("USAGE", "SERVICE ROLE", f"{DB}.AML.STPLATSTREAMLIT1.STREAMLIT_DEVELOPER"), ("USAGE", "SERVICE ROLE", f"{DB}.AML.STPLATSTREAMLIT1.STREAMLIT_VIEWER")]
SEC_NONE = '{"roles":"","value":""}'


def healthy_script() -> dict:
    grants = [{"privilege": p, "granted_on": on, "name": n} for p, on, n in sorted(H.expected_app_grants()) + PLATFORM]
    return {
        "CURRENT_ROLE()": [{"r": APP, "sec": SEC_NONE, "d": DB, "s": "AML", "w": WH}],
        f"SHOW GRANTS TO ROLE {APP}": grants,
        "SHOW GRANTS ON TABLE": [{"grantee_name": ADMIN, "privilege": "OWNERSHIP"}, {"grantee_name": APP, "privilege": "INSERT"}, {"grantee_name": APP, "privilege": "SELECT"},
                                 {"grantee_name": "ACCOUNTADMIN", "privilege": "INSERT"}, {"grantee_name": "ACCOUNTADMIN", "privilege": "SELECT"}],
        "SHOW CORTEX SEARCH SERVICES": [{"indexing_state": "ACTIVE", "serving_state": "ACTIVE", "source_data_num_rows": MANIFEST["counts"]["search_indexed"],
                                          "target_lag": "1 hour", "warehouse": WH, "embedding_model": "m"}],
        "SEARCH_PREVIEW": [{"results": json.dumps([{"RULE_ID": "STR-002", "EVIDENCE_LEVEL": "PROVEN"}, {"RULE_ID": "INS-001", "EVIDENCE_LEVEL": "ASSUMED"}])}],
        "REGULATORY_CORPUS GROUP BY": [{"evidence_level": k, "n": MANIFEST["counts"][k]} for k in ("ASSUMED", "NEEDS-VERIFICATION", "PROVEN")],
        "COUNT(DISTINCT CORPUS_VERSION)": [{"nv": 1, "v": MANIFEST["corpus_version"], "nulls": 0}],
        "LIST @": [{"name": "semantic_stage/semantic_model.yaml", "size": 27328, "md5": "x", "last_modified": "Wed, 30 Sep 2026"}],
        "DECISION_LEDGER_INTEGRITY_V GROUP BY": [{"integrity_status": "INTACT", "n": 2}],
        "SHOW STREAMLITS": [{"owner": APP, "query_warehouse": WH, "url_id": "abc123", "created_on": "2026-10-01 06:42:31"}],
        "DESC STREAMLIT": [{"live_version_location_uri": LIVE_URI, "runtime_name": "SYSTEM$ST_CONTAINER_RUNTIME_PY3_11", "compute_pool": "SYSTEM_COMPUTE_POOL_CPU"}],
    }


class StubSkills:
    """Stands in for CoPilotSkills: a reconciliation built from the REAL audit.reconcile over given rows / anchor."""

    def __init__(self, rows=None, anchor=None, anchor_error="audit export table not available (not provisioned, or not readable by this role)"):
        self.rows = rows if rows is not None else [row(1), row(2)]
        self.anchor, self.anchor_error, self.last_model_used = anchor, anchor_error, "llama3.3-70b"

    def ledger_reconciliation(self):
        return A.reconcile(self.rows, self.anchor, anchor_error=None if self.anchor is not None else self.anchor_error)

    def _cortex_complete(self, prompt):
        return "OK"


def run(script=None, files=None, skills=None, deep=False, mutate=None):
    s = copy.deepcopy(healthy_script())
    if mutate:
        mutate(s)
    if script:
        s.update(script)
    db = FakeDB(list(s.items()), files)
    rep = H.run_checks(db, ROOT, deep=deep, skills=skills or StubSkills())
    return rep, db


def by_id(rep) -> dict:
    return {c["id"]: c for c in rep["checks"]}


def status(rep) -> dict:
    return {c["id"]: c["status"] for c in rep["checks"]}


ALL_LOGS: list[str] = []


def go(**kw):
    rep, db = run(**kw)
    ALL_LOGS.extend(db.log)
    return rep


# ── the gate ─────────────────────────────────────────────────────────────────

def test_the_read_only_gate_accepts_reads_and_refuses_everything_else():
    ok = ["SELECT 1", "  select * from t", "SHOW GRANTS TO ROLE X", "DESC STREAMLIT a.b.c", "DESCRIBE TABLE t", f"LIST @{DB}.AML.SEMANTIC_STAGE",
          "WITH g AS (SELECT 1) SELECT * FROM g", "SHOW STAGES LIKE 'CREATE_DROP_TABLE'", "SELECT 'DELETE FROM x' AS S", "SELECT 'a; b' AS NOTE", "SELECT 'it''s; fine' AS N",
          f"GET @{DB}.AML.SEMANTIC_STAGE/semantic_model.yaml file:///tmp/x/", f"GET '{LIVE_URI}' file:///tmp/x/"]
    for s in ok:
        H.assert_read_only(s)
    bad = ["INSERT INTO t VALUES (1)", "UPDATE t SET a=1", "DELETE FROM t", "MERGE INTO t USING s ON 1=1 WHEN MATCHED THEN DELETE", "TRUNCATE TABLE t", "DROP TABLE t",
           "ALTER TABLE t ADD COLUMN c INT", "CREATE TABLE t (a INT)", "GRANT SELECT ON t TO ROLE r", "REVOKE SELECT ON t FROM ROLE r", "PUT file:///tmp/a @s", "COPY INTO t FROM @s",
           "CALL p()", "EXECUTE IMMEDIATE 'select 1'", "UNDROP TABLE t", "USE ROLE ACCOUNTADMIN", "SELECT 1; DROP TABLE t", "WITH x AS (SELECT 1) DELETE FROM t",
           "SELECT * FROM t; SELECT 2", "SELECT 'a'; DROP TABLE t", "SELECT '\\'; x'; DELETE FROM t", "SELECT 1 UNION SELECT (DROP TABLE t)", "GET @s file:///tmp/x", "-- c\nDROP TABLE t", ""]
    for s in bad:
        try:
            H.assert_read_only(s)
            raise AssertionError(f"the gate must refuse: {s!r}")
        except H.NotReadOnly:
            pass
    db = FakeDB([])
    r = H.Runner(db)
    for s in ("DROP TABLE x", "INSERT INTO t VALUES (1)", "SELECT 1; DELETE FROM t"):
        try:
            r.q(s)
            raise AssertionError("Runner.q must refuse")
        except H.NotReadOnly:
            pass
    assert db.log == [], "a refused statement must never reach the cursor"
    print(f"  [PASS] the gate accepts {len(ok)} read forms and refuses {len(bad)} writes/DDL/grants/multi-statements; a refused statement never reaches the cursor")


def test_get_may_only_download_into_a_temporary_directory():
    db = FakeDB([])
    for bad in ("/etc/cron.d", str(Path.home()), "/"):
        try:
            H.Runner(db).get(f"@{DB}.AML.SEMANTIC_STAGE/semantic_model.yaml", bad)
            raise AssertionError(f"GET into {bad} must be refused")
        except H.NotReadOnly:
            pass
    assert db.log == []
    with tempfile.TemporaryDirectory() as tmp:
        db2 = FakeDB([], files={})
        H.Runner(db2).get(f"@{DB}.AML.SEMANTIC_STAGE/semantic_model.yaml", tmp)
        assert db2.log and (Path(tmp) / "semantic_model.yaml").exists()
    print("  [PASS] GET downloads only into a temporary directory (a path outside it is refused before reaching the database)")


# ── the states ───────────────────────────────────────────────────────────────

def test_healthy_path_proves_each_property_and_still_reports_what_it_cannot_prove():
    rep = go()
    s = status(rep)
    assert [k for k, v in s.items() if v == H.HEALTHY] == ["session", "app_role_grants", "ledger_grantees", "search_service", "search_probe", "corpus",
                                                          "semantic_model_file", "ledger_census", "reconciliation", "application"], s
    assert [k for k, v in s.items() if v == H.UNVERIFIED] == ["deletion_witness", "complete_probe", "analyst_probe"], s
    assert rep["overall"] == H.UNVERIFIED and rep["summary"] == {H.HEALTHY: 10, H.UNAVAILABLE: 0, H.UNVERIFIED: 3} and rep["read_only"] is True
    app = by_id(rep)["application"]
    bundle = yaml.safe_load((ROOT / "snowflake.yml").read_text())["streamlit"]    # the bundle size is whatever snowflake.yml lists, not a number to keep in step by hand
    expected_files = 1 + len(bundle["additional_source_files"])
    assert "NOT VERIFIED" in app["evidence"]["rendered_in_snowsight"] and app["evidence"]["files_identical"] == app["evidence"]["files_total"] == expected_files
    assert app["evidence"]["local_bundle"] == app["evidence"]["hosted_bundle"]
    assert "platform-owned" in by_id(rep)["app_role_grants"]["summary"]
    assert "DELETION OF LEDGER ROWS BY THE OWNER ROLE WOULD NOT BE DETECTED" in by_id(rep)["deletion_witness"]["summary"]
    print("  [PASS] 10 properties HEALTHY with evidence; the deletion witness and the two billed probes are UNVERIFIED; overall is UNVERIFIED, not HEALTHY; the hosted render is stated as not verified")


def test_with_a_valid_audit_export_and_the_deep_probes_everything_can_be_healthy():
    rows = [row(1), row(2)]
    anchor = A.export_records(rows)
    import skills
    real = skills.CorpusAnalyst

    class Analyst:
        def __init__(self, conn): pass
        def ask(self, q): return {"available": True, "generated_sql": "SELECT 1", "rows": [{"ALERT_STATUS": "OPEN", "ALERT_COUNT": 14}], "warnings": []}
    skills.CorpusAnalyst = Analyst
    try:
        rep = go(skills=StubSkills(rows, anchor), deep=True)
    finally:
        skills.CorpusAnalyst = real
    assert rep["overall"] == H.HEALTHY and all(v == H.HEALTHY for v in status(rep).values()), status(rep)
    assert "a witness, not WORM storage" in by_id(rep)["deletion_witness"]["summary"]
    print("  [PASS] with a valid hash-chained audit export and --deep, all 13 checks are HEALTHY (and the witness is described as not WORM storage)")


def test_unavailable_means_shown_not_to_hold():
    cases = {
        "search not ACTIVE": (dict(mutate=lambda s: s.update({"SHOW CORTEX SEARCH SERVICES": [{"indexing_state": "SUSPENDED", "serving_state": "ACTIVE", "source_data_num_rows": 36}]})), "search_service"),
        "search indexes 35 rows": (dict(mutate=lambda s: s.update({"SHOW CORTEX SEARCH SERVICES": [{"indexing_state": "ACTIVE", "serving_state": "ACTIVE", "source_data_num_rows": 35}]})), "search_service"),
        "search service not visible": (dict(mutate=lambda s: s.update({"SHOW CORTEX SEARCH SERVICES": []})), "search_service"),
        "probe leaks a NEEDS-VERIFICATION rule": (dict(mutate=lambda s: s.update({"SEARCH_PREVIEW": [{"results": json.dumps([{"RULE_ID": "RFI-001", "EVIDENCE_LEVEL": "NEEDS-VERIFICATION"}])}]})), "search_probe"),
        "probe returns nothing": (dict(mutate=lambda s: s.update({"SEARCH_PREVIEW": [{"results": "[]"}]})), "search_probe"),
        "corpus count differs": (dict(mutate=lambda s: s.update({"REGULATORY_CORPUS GROUP BY": [{"evidence_level": "PROVEN", "n": 14}, {"evidence_level": "ASSUMED", "n": 21}, {"evidence_level": "NEEDS-VERIFICATION", "n": 13}]})), "corpus"),
        "two corpus versions": (dict(mutate=lambda s: s.update({"COUNT(DISTINCT CORPUS_VERSION)": [{"nv": 2, "v": MANIFEST["corpus_version"], "nulls": 0}]})), "corpus"),
        "governance columns NULL": (dict(mutate=lambda s: s.update({"COUNT(DISTINCT CORPUS_VERSION)": [{"nv": 1, "v": MANIFEST["corpus_version"], "nulls": 3}]})), "corpus"),
        "corpus version differs": (dict(mutate=lambda s: s.update({"COUNT(DISTINCT CORPUS_VERSION)": [{"nv": 1, "v": "0.9.0", "nulls": 0}]})), "corpus"),
        "semantic model not on the stage": (dict(mutate=lambda s: s.update({"LIST @": []})), "semantic_model_file"),
        "semantic model differs": (dict(files={"semantic_model.yaml": b"tables: []\n"}), "semantic_model_file"),
        "a row is TAMPERED": (dict(mutate=lambda s: s.update({"DECISION_LEDGER_INTEGRITY_V GROUP BY": [{"integrity_status": "INTACT", "n": 1}, {"integrity_status": "TAMPERED", "n": 1}]})), "ledger_census"),
        "reconciliation COMPROMISED": (dict(skills=StubSkills([row(1), row(2, tampered=True)])), "reconciliation"),
        "the export shows a deleted row": (dict(skills=StubSkills([row(2)], A.export_records([row(1), row(2)]))), "deletion_witness"),
        "the app is not visible": (dict(mutate=lambda s: s.update({"SHOW STREAMLITS": []})), "application"),
        "the app is owned by another role": (dict(mutate=lambda s: s.update({"SHOW STREAMLITS": [{"owner": "ACCOUNTADMIN", "query_warehouse": WH, "url_id": "x", "created_on": ""}]})), "application"),
        "the app uses another warehouse": (dict(mutate=lambda s: s.update({"SHOW STREAMLITS": [{"owner": APP, "query_warehouse": "SOME_WH", "url_id": "x", "created_on": ""}]})), "application"),
        "one hosted file is behind the source": (dict(files={"streamlit_app.py": b"# an older build\n"}), "application"),
        "a hosted module is missing": (dict(files={"po_copy.py": "ABSENT"}), "application"),
        "secondary roles are active": (dict(mutate=lambda s: s.update({"CURRENT_ROLE()": [{"r": APP, "sec": '{"roles":"FIU_ADMIN_ROLE","value":"ALL"}', "d": DB, "s": "AML", "w": WH}]})), "session"),
    }
    for label, (kw, cid) in cases.items():
        got = by_id(go(**kw))[cid]
        assert got["status"] == H.UNAVAILABLE, f"{label}: expected UNAVAILABLE for {cid}, got {got['status']} — {got['summary']}"
    print(f"  [PASS] {len(cases)} failure scenarios (not ACTIVE, 35 rows, leaked NV rule, count/version/NULL drift, missing/different semantic model, TAMPERED, COMPROMISED, deleted row, "
          "foreign-owned app, wrong warehouse, hosted code behind, missing module, secondary roles) → UNAVAILABLE")


def test_least_privilege_drift_is_unavailable_and_names_the_drift():
    extra = [{"privilege": "UPDATE", "granted_on": "TABLE", "name": f"{DB}.AML.DECISION_LEDGER"}]
    cases = {
        "UPDATE on the ledger": (lambda s: s.update({f"SHOW GRANTS TO ROLE {APP}": s[f"SHOW GRANTS TO ROLE {APP}"] + extra}), "ledger privileges"),
        "write on another table": (lambda s: s.update({f"SHOW GRANTS TO ROLE {APP}": s[f"SHOW GRANTS TO ROLE {APP}"] + [{"privilege": "INSERT", "granted_on": "TABLE", "name": f"{DB}.AML.ALERTS"}]}), "beyond the least-privilege set"),
        "CREATE STREAMLIT left behind": (lambda s: s.update({f"SHOW GRANTS TO ROLE {APP}": s[f"SHOW GRANTS TO ROLE {APP}"] + [{"privilege": "CREATE STREAMLIT", "granted_on": "SCHEMA", "name": f"{DB}.AML"}]}), "CREATE privilege"),
        "OWNERSHIP of the ledger": (lambda s: s.update({f"SHOW GRANTS TO ROLE {APP}": s[f"SHOW GRANTS TO ROLE {APP}"] + [{"privilege": "OWNERSHIP", "granted_on": "TABLE", "name": f"{DB}.AML.DECISION_LEDGER"}]}), "ledger privileges"),
        "a required grant is missing": (lambda s: s.update({f"SHOW GRANTS TO ROLE {APP}": [g for g in s[f"SHOW GRANTS TO ROLE {APP}"] if g["name"] != f"{DB}.AML.SEMANTIC_STAGE"]}), "missing"),
        "an unexpected role object": (lambda s: s.update({f"SHOW GRANTS TO ROLE {APP}": s[f"SHOW GRANTS TO ROLE {APP}"] + [{"privilege": "OWNERSHIP", "granted_on": "TABLE", "name": f"{DB}.AML.NEW_TABLE"}]}), "beyond the least-privilege set"),
    }
    for label, (mut, needle) in cases.items():
        got = by_id(go(mutate=mut))["app_role_grants"]
        assert got["status"] == H.UNAVAILABLE and needle in got["summary"], f"{label}: {got['status']} — {got['summary']}"
    public = lambda s: s.update({"SHOW GRANTS ON TABLE": s["SHOW GRANTS ON TABLE"] + [{"grantee_name": "PUBLIC", "privilege": "SELECT"}]})  # noqa: E731
    got = by_id(go(mutate=public))["ledger_grantees"]
    assert got["status"] == H.UNAVAILABLE and "PUBLIC" in got["summary"]
    appwrite = lambda s: s.update({"SHOW GRANTS ON TABLE": [g for g in s["SHOW GRANTS ON TABLE"] if g["grantee_name"] != APP] + [{"grantee_name": APP, "privilege": "SELECT"}]})  # noqa: E731
    assert by_id(go(mutate=appwrite))["ledger_grantees"]["status"] == H.UNAVAILABLE
    print(f"  [PASS] {len(cases)} grant-drift scenarios + a PUBLIC grantee + a missing INSERT → UNAVAILABLE, each naming what drifted; platform-owned app objects are accounted for, not flagged")


def test_a_provisioned_audit_export_is_healthy_but_anything_beyond_it_is_not():
    """Found by the clean-room run: provisioning the opt-in audit export (deploy/05_audit_export.sql) adds read grants for the app role and a
    SELECT-only grantee on the ledger. The check must treat exactly those as healthy — and nothing more."""
    audit_grants = [{"privilege": "USAGE", "granted_on": "SCHEMA", "name": f"{DB}.AUDIT"}, {"privilege": "SELECT", "granted_on": "TABLE", "name": f"{DB}.AUDIT.LEDGER_EXPORT"}]
    ledger = [{"grantee_name": H.AUDIT, "privilege": "SELECT"}]
    prov = lambda s: s.update({f"SHOW GRANTS TO ROLE {APP}": s[f"SHOW GRANTS TO ROLE {APP}"] + audit_grants, "SHOW GRANTS ON TABLE": s["SHOW GRANTS ON TABLE"] + ledger})  # noqa: E731
    rep = go(mutate=prov)
    st = status(rep)
    assert st["app_role_grants"] == st["ledger_grantees"] == H.HEALTHY, (by_id(rep)["app_role_grants"]["summary"], by_id(rep)["ledger_grantees"]["summary"])
    assert "audit-export store" in by_id(rep)["app_role_grants"]["summary"] and by_id(rep)["app_role_grants"]["evidence"]["audit_export_read_grants"] == 2
    beyond = {
        "INSERT on the export table": lambda s: (prov(s), s.update({f"SHOW GRANTS TO ROLE {APP}": s[f"SHOW GRANTS TO ROLE {APP}"] + [{"privilege": "INSERT", "granted_on": "TABLE", "name": f"{DB}.AUDIT.LEDGER_EXPORT"}]})),
        "another object in the audit schema": lambda s: (prov(s), s.update({f"SHOW GRANTS TO ROLE {APP}": s[f"SHOW GRANTS TO ROLE {APP}"] + [{"privilege": "SELECT", "granted_on": "TABLE", "name": f"{DB}.AUDIT.OTHER"}]})),
    }
    for label, mut in beyond.items():
        assert by_id(go(mutate=mut))["app_role_grants"]["status"] == H.UNAVAILABLE, label
    wide = lambda s: (prov(s), s.update({"SHOW GRANTS ON TABLE": s["SHOW GRANTS ON TABLE"] + [{"grantee_name": H.AUDIT, "privilege": "DELETE"}]}))  # noqa: E731
    got = by_id(go(mutate=wide))["ledger_grantees"]
    assert got["status"] == H.UNAVAILABLE and "may only SELECT" in got["summary"]
    print("  [PASS] with the audit export provisioned the grants read HEALTHY (2 read grants for the app role, SELECT-only audit grantee); INSERT on the export, another object in the audit schema, or a non-SELECT audit grant → UNAVAILABLE")


def test_unverified_means_no_evidence_either_way_and_a_failure_to_look_is_never_a_finding():
    denied = Exception("002003 (02000): SQL compilation error: Object does not exist, or operation cannot be performed.")
    for needle, cid in ((f"SHOW GRANTS TO ROLE {APP}", "app_role_grants"), ("SHOW GRANTS ON TABLE", "ledger_grantees"), ("SHOW CORTEX SEARCH SERVICES", "search_service"),
                        ("SEARCH_PREVIEW", "search_probe"), ("REGULATORY_CORPUS GROUP BY", "corpus"), ("LIST @", "semantic_model_file"),
                        ("DECISION_LEDGER_INTEGRITY_V GROUP BY", "ledger_census"), ("SHOW STREAMLITS", "application")):
        got = by_id(go(script={needle: denied}))[cid]
        assert got["status"] == H.UNVERIFIED and "establishes nothing" in got["summary"], f"{cid}: a statement that raised must be UNVERIFIED, got {got['status']}"
        assert "Traceback" not in json.dumps(got)
    # the session as another role: every 'what the app role can see' claim is about someone else
    other = by_id(go(mutate=lambda s: s.update({"CURRENT_ROLE()": [{"r": "ACCOUNTADMIN", "sec": SEC_NONE, "d": DB, "s": "AML", "w": WH}]})))["session"]
    assert other["status"] == H.UNVERIFIED and "not " + APP in other["summary"]
    # legacy rows: nothing can be said about their content
    legacy = [{"integrity_status": "LEGACY_UNHASHED", "n": 12}]
    cen = by_id(go(mutate=lambda s: s.update({"DECISION_LEDGER_INTEGRITY_V GROUP BY": legacy}), skills=StubSkills([row(i, legacy=True) for i in range(12)])))
    assert cen["ledger_census"]["status"] == H.UNVERIFIED and "predate ROW_HASH" in cen["ledger_census"]["summary"]
    assert cen["reconciliation"]["status"] == H.UNVERIFIED and "ATTENTION" in cen["reconciliation"]["summary"]
    # the files cannot be downloaded: the check could not compare, so it must not say identical OR different
    for files, cid in (({"__error__": Exception("002003 not authorized")}, "semantic_model_file"), ({"__error__": Exception("002003 not authorized")}, "application")):
        assert by_id(go(files=files))[cid]["status"] == H.UNVERIFIED, cid
    # an empty ledger: the integrity view answers, nothing to verify, nothing tampered
    empty = by_id(go(mutate=lambda s: s.update({"DECISION_LEDGER_INTEGRITY_V GROUP BY": []}), skills=StubSkills([])))["ledger_census"]
    assert empty["status"] == H.HEALTHY and "empty" in empty["summary"]
    # an unrecognised integrity status is not silently counted as fine
    weird = by_id(go(mutate=lambda s: s.update({"DECISION_LEDGER_INTEGRITY_V GROUP BY": [{"integrity_status": "SOMETHING_NEW", "n": 1}]})))["ledger_census"]
    assert weird["status"] == H.UNVERIFIED
    print("  [PASS] a statement the role cannot run → UNVERIFIED (never UNAVAILABLE, never HEALTHY); other role → UNVERIFIED; legacy rows → UNVERIFIED; undownloadable files → UNVERIFIED; empty ledger → HEALTHY; unknown status → UNVERIFIED")


def test_overall_is_the_worst_state_and_unverified_is_never_summarised_as_healthy():
    scenarios = [go(), go(mutate=lambda s: s.update({"SHOW STREAMLITS": []})),
                 go(skills=StubSkills([row(i, legacy=True) for i in range(3)]), mutate=lambda s: s.update({"DECISION_LEDGER_INTEGRITY_V GROUP BY": [{"integrity_status": "LEGACY_UNHASHED", "n": 3}]}))]
    for rep in scenarios:
        s = rep["summary"]
        assert sum(s.values()) == len(rep["checks"])
        worst = H.UNAVAILABLE if s[H.UNAVAILABLE] else (H.UNVERIFIED if s[H.UNVERIFIED] else H.HEALTHY)
        assert rep["overall"] == worst
        if s[H.UNVERIFIED]:
            assert rep["overall"] != H.HEALTHY, "an UNVERIFIED check must prevent an overall HEALTHY"
        text = H.render(rep)
        assert f"OVERALL {worst}" in text and "never read as healthy" in text
    print("  [PASS] overall = the worst state across checks; any UNVERIFIED prevents HEALTHY; the printed legend says UNVERIFIED is never read as healthy")


def test_every_statement_issued_in_every_scenario_is_read_only():
    assert len(ALL_LOGS) > 150, f"too few statements recorded ({len(ALL_LOGS)}): the scenario tests must run first (and in the same process)"
    for sql in ALL_LOGS:
        H.assert_read_only(sql)
        assert not re.search(r"\b(INSERT|UPDATE|DELETE|MERGE|TRUNCATE|DROP|ALTER|CREATE|GRANT|REVOKE|PUT|COPY|CALL|UNDROP)\b", re.sub(r"'[^']*'", "''", sql), re.I), sql
    kinds = {sql.split()[0].upper() for sql in ALL_LOGS}
    assert kinds <= {"SELECT", "SHOW", "DESC", "LIST", "GET"}, kinds
    print(f"  [PASS] {len(ALL_LOGS)} statements issued across every scenario: all {sorted(kinds)}, none writes")


# ── tie to the artifacts ─────────────────────────────────────────────────────

def _grant_file_set() -> set[tuple[str, str, str]]:
    out = set()
    for line in (ROOT / "deploy/03_grants.sql").read_text().splitlines():
        m = re.match(rf"GRANT\s+(.+?)\s+ON\s+(WAREHOUSE|DATABASE|SCHEMA|TABLE|VIEW|CORTEX SEARCH SERVICE|STAGE)\s+(\S+)\s+TO ROLE {APP};", line.strip())
        if m:
            for p in [x.strip() for x in m.group(1).split(",")]:
                out.add((p, m.group(2).replace(" ", "_"), m.group(3)))
        m = re.match(rf"GRANT DATABASE ROLE (\S+) TO ROLE {APP};", line.strip())
        if m:
            out.add(("USAGE", "DATABASE_ROLE", m.group(1)))
    return out


def test_the_expected_grant_set_equals_the_grant_file_and_the_sql_pack():
    from_file = _grant_file_set()
    assert from_file == H.expected_app_grants(), (sorted(from_file - H.expected_app_grants()), sorted(H.expected_app_grants() - from_file))
    pack = (ROOT / "deploy/06_health.sql").read_text()
    from_sql = set(re.findall(r"\('([A-Z_]+)','([A-Z_]+)','([A-Za-z0-9_.$]+)'\)", pack))
    assert from_sql == H.expected_app_grants() | H.optional_app_grants(), (sorted(from_sql ^ (H.expected_app_grants() | H.optional_app_grants())))
    audit_sql = (ROOT / "deploy/05_audit_export.sql").read_text() + (ROOT / "deploy/07_decision_outcomes.sql").read_text()
    for priv, on, name in H.optional_app_grants():                     # the optional grants are exactly what 05_audit_export.sql and 07_decision_outcomes.sql give the app role
        assert f"GRANT {priv}" in audit_sql and name.replace("FIU_COPILOT.", "FIU_COPILOT.") in audit_sql and "TO ROLE FIU_APP_ROLE" in audit_sql, (priv, name)
    revoke = (ROOT / "deploy/03_grants.sql").read_text()
    assert re.search(r"REVOKE UPDATE, DELETE, TRUNCATE, REFERENCES ON TABLE \S+\.DECISION_LEDGER FROM ROLE", revoke)
    print(f"  [PASS] the {len(from_file)} expected grants = deploy/03_grants.sql = the grant tuples in deploy/06_health.sql (so 'least privilege' has one definition)")


def test_the_sql_pack_is_read_only_and_its_expectations_come_from_the_manifest():
    sys.path.insert(0, str(ROOT / "scripts"))
    import deploy_snowflake as d
    stmts = d.split_sql((ROOT / "deploy/06_health.sql").read_text())
    assert len(stmts) >= 20
    for s in stmts:
        if re.match(r"USE (ROLE FIU_APP_ROLE|SECONDARY ROLES NONE|WAREHOUSE FIU_WH)$", s.strip(), re.I):
            continue
        H.assert_read_only(s)
    pack = (ROOT / "deploy/06_health.sql").read_text()
    c = MANIFEST["counts"]
    assert f'"source_data_num_rows" = {c["search_indexed"]}' in pack
    assert f"= '{MANIFEST['corpus_version']}'" in pack
    for level in ("PROVEN", "ASSUMED", "NEEDS-VERIFICATION"):
        assert re.search(rf"EVIDENCE_LEVEL = '{level}'\) = {c[level]}\b", pack), f"the SQL pack's expected {level} count must equal the manifest's {c[level]}"
    for state in H.STATES:
        assert f"'{state}'" in pack
    assert "'HEALTHY', 'UNVERIFIED')" not in pack.replace("'UNVERIFIED', 'UNVERIFIED'", ""), "section 9 must not branch to the same state"
    print(f"  [PASS] {len(stmts)} SQL statements: only USE (the app role) and reads; expectations (36 indexed, v{MANIFEST['corpus_version']}, {c['PROVEN']}/{c['ASSUMED']}/{c['NEEDS-VERIFICATION']}) equal the manifest")


def test_bundle_digest_is_deterministic_and_changes_with_any_file():
    a = {"streamlit_app.py": "1" * 64, "core.py": "2" * 64}
    assert H.bundle_digest(a) == H.bundle_digest(dict(reversed(list(a.items()))))
    assert H.bundle_digest(a) != H.bundle_digest({**a, "core.py": "3" * 64}) and H.bundle_digest(a) != H.bundle_digest({"streamlit_app.py": "1" * 64})
    print("  [PASS] the deployment version (bundle digest) is order-independent and changes with any file")


def _fp_script():
    h = healthy_script()
    return [("COUNT(*) AS N, HASH_AGG(*) AS H FROM " + f"{DB}.AML.DECISION_LEDGER", [{"n": 12, "h": -7680837812696820876}]),
            ("COUNT(*) AS N, HASH_AGG(*)", [{"n": 5, "h": 111}]),
            ("DECISION_LEDGER_INTEGRITY_V GROUP BY", [{"integrity_status": "LEGACY_UNHASHED", "n": 12}]),
            ("COUNT(*) AS N FROM", [{"n": 7}]),
            (f"SHOW GRANTS TO ROLE {APP}", h[f"SHOW GRANTS TO ROLE {APP}"]), ("SHOW GRANTS ON TABLE", h["SHOW GRANTS ON TABLE"]),
            ("SHOW STREAMLITS", h["SHOW STREAMLITS"]),
            ("SHOW CORTEX SEARCH SERVICES", [{"created_on": "2026-09-24", "source_data_num_rows": 36, "indexing_state": "ACTIVE", "serving_state": "ACTIVE", "warehouse": WH}]),
            ("SHOW DATABASES", [{"name": DB, "created_on": "2026-09-15"}]), ("SHOW WAREHOUSES", [{"name": WH, "created_on": "2026-09-15"}]),
            ("SHOW ROLES", [{"name": ADMIN, "created_on": "2026-09-29"}, {"name": APP, "created_on": "2026-09-29"}])]


def test_environment_fingerprint_detects_any_change_ignores_timestamps_and_is_read_only():
    import env_fingerprint as F
    db = FakeDB(_fp_script())
    a = F.fingerprint(db)
    assert a["tables"]["DECISION_LEDGER"] == {"rows": 12, "hash_agg": "-7680837812696820876"} and a["ledger_integrity"] == {"LEGACY_UNHASHED": 12}
    assert a["named_objects"][f"ROLE {H.AUDIT}"] == "absent", "a role that does not exist is recorded as absent, not as an error"
    for sql in db.log:
        H.assert_read_only(sql)
    assert F.compare(a, {**a, "taken_at": "2099-01-01T00:00:00Z", "statements_run": 999}) == [], "when it was taken and how many statements it needed are not changes"
    for mutate, needle in ((lambda f: f["tables"]["DECISION_LEDGER"].update(rows=13), "tables.DECISION_LEDGER.rows"),
                           (lambda f: f["tables"]["ALERTS"].update(hash_agg="999"), "tables.ALERTS.hash_agg"),
                           (lambda f: f["app_role_grants"].update(sha256="x"), "app_role_grants.sha256"),
                           (lambda f: f["streamlit"][0].update(owner="ACCOUNTADMIN"), "streamlit"),
                           (lambda f: f["named_objects"].update({f"ROLE {H.AUDIT}": "2026-10-02"}), "named_objects.ROLE")):
        b = json.loads(json.dumps(a))
        mutate(b)
        diff = F.compare(a, b)
        assert diff and any(needle.split(".")[0] in d for d in diff), (needle, diff)
    assert F.compare(a, {k: v for k, v in a.items() if k != "streamlit"}) and any("disappeared" in d for d in F.compare(a, {k: v for k, v in a.items() if k != "streamlit"}))
    print("  [PASS] the fingerprint changes when ANY row value, grant, app property or named object changes; its own timestamp is ignored; every statement it issues is read-only")


def test_environment_fingerprint_records_counts_and_hashes_never_row_values():
    import env_fingerprint as F
    secret_row = {"n": 3, "h": 42, "RATIONALE_TEXT": "customer Asha Verma PAN ABCDE1234F"}
    script = [("COUNT(*) AS N, HASH_AGG(*)", [secret_row])] + _fp_script()[2:]
    text = json.dumps(F.fingerprint(FakeDB(script)))
    assert "Asha" not in text and "ABCDE" not in text and "RATIONALE" not in text, "only counts and hashes may be recorded"
    print("  [PASS] the fingerprint carries counts and an aggregate hash per table — a row's content never reaches it")


def test_cli_without_credentials_fails_with_one_sentence_and_lists_no_secrets():
    env = {k: v for k, v in os.environ.items() if not k.startswith(("SNOWFLAKE_", "FIU_"))}
    env["FIU_SKIP_DOTENV"] = "1"
    r = subprocess.run([sys.executable, str(ROOT / "scripts/health_check.py")], capture_output=True, text=True, env=env, cwd=ROOT, timeout=60)
    out = r.stdout + r.stderr
    assert r.returncode == 1 and "issing Snowflake configuration" in out and "Traceback" not in out, out[:300]
    print("  [PASS] without credentials the CLI exits 1 with one sentence and no stack trace")


TESTS = [
    test_the_read_only_gate_accepts_reads_and_refuses_everything_else, test_get_may_only_download_into_a_temporary_directory,
    test_healthy_path_proves_each_property_and_still_reports_what_it_cannot_prove, test_with_a_valid_audit_export_and_the_deep_probes_everything_can_be_healthy,
    test_unavailable_means_shown_not_to_hold, test_least_privilege_drift_is_unavailable_and_names_the_drift, test_a_provisioned_audit_export_is_healthy_but_anything_beyond_it_is_not,
    test_unverified_means_no_evidence_either_way_and_a_failure_to_look_is_never_a_finding,
    test_overall_is_the_worst_state_and_unverified_is_never_summarised_as_healthy, test_every_statement_issued_in_every_scenario_is_read_only,
    test_the_expected_grant_set_equals_the_grant_file_and_the_sql_pack, test_the_sql_pack_is_read_only_and_its_expectations_come_from_the_manifest,
    test_bundle_digest_is_deterministic_and_changes_with_any_file, test_environment_fingerprint_detects_any_change_ignores_timestamps_and_is_read_only,
    test_environment_fingerprint_records_counts_and_hashes_never_row_values, test_cli_without_credentials_fails_with_one_sentence_and_lists_no_secrets,
]

if __name__ == "__main__":
    raise SystemExit(Runner("Operational health / proof checks (offline)").run(TESTS))
