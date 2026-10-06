"""
health_check.py — READ-ONLY health / proof query set for a deployed FIU-IND AML Copilot environment.

Every check ends in exactly one of three states, and the difference matters more than the colour:

    HEALTHY      the check ran now and POSITIVELY showed the property holds (evidence attached)
    UNAVAILABLE  the check ran and showed the property does NOT hold (object missing, not ACTIVE, drifted, tampered)
    UNVERIFIED   the check could not establish the property either way — a capability that is not provisioned (the audit
                 export), evidence that does not exist (legacy rows with no hash), a probe that costs money and was not
                 asked for (--deep), a failure to look (no privilege), or a thing no query can see (what Snowsight RENDERED)

A report never turns UNVERIFIED into HEALTHY. Exit code: 0 = no UNAVAILABLE · 2 = at least one UNAVAILABLE · 3 = --strict and
at least one UNVERIFIED · 1 = could not connect.

Checks: session isolation · app-role grants (exact) · ledger grantees · Cortex Search service · Search serving probe ·
corpus version/counts · semantic-model file · ledger integrity census · latest reconciliation · deletion witness (audit export) ·
hosted application (owner, warehouse, bundle digest vs the local source) · [--deep] Cortex Complete probe · Cortex Analyst probe.

SAFETY: every statement goes through one gate that accepts only SELECT / SHOW / DESC(RIBE) / LIST / WITH, plus a fixed GET into a
temporary directory (a read of a stage). Nothing is written to Snowflake. tests/test_health.py asserts this for every check.

    python3 scripts/health_check.py                        # as FIU_APP_ROLE (secondary roles NONE), human-readable
    python3 scripts/health_check.py --json --out health.json
    python3 scripts/health_check.py --deep                 # also one Cortex Complete call and one Cortex Analyst question
    python3 scripts/health_check.py --profile cleanroom    # same checks against the clean-room names (renders the local reference)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

HEALTHY, UNAVAILABLE, UNVERIFIED = "HEALTHY", "UNAVAILABLE", "UNVERIFIED"
STATES = (HEALTHY, UNAVAILABLE, UNVERIFIED)

# A rendered copy of this file changes these literals (scripts/envprofile.py); --profile overrides them at run time.
ADMIN, APP, AUDIT = "FIU_ADMIN_ROLE", "FIU_APP_ROLE", "FIU_AUDIT_ROLE"
DB, SCHEMA, WH = "FIU_COPILOT", "AML", "FIU_WH"
APP_NAME = "FIU_AML_COPILOT"

_READ_ONLY = re.compile(r"^\s*(SELECT|SHOW|DESC|DESCRIBE|LIST|WITH)\b", re.I)
_GET_STAGE = re.compile(r"^GET (@[A-Za-z0-9_.\"$]+(?:/[A-Za-z0-9_.\-]+)?|'snow://[A-Za-z0-9_./\-]+/') file://[^\s']+/$")
_FORBIDDEN = re.compile(r"\b(INSERT|UPDATE|DELETE|MERGE|TRUNCATE|DROP|ALTER|CREATE|GRANT|REVOKE|PUT|COPY|CALL|EXECUTE|UNDROP|REMOVE|RM)\b", re.I)


class NotReadOnly(RuntimeError):
    pass


def assert_read_only(sql: str) -> None:
    """The single gate: a statement is run only if it is a read. (GET is allowed only in its fixed form, see Runner.get.)"""
    body = sql.strip().rstrip(";")
    if _GET_STAGE.match(body):
        return
    if not _READ_ONLY.match(body):
        raise NotReadOnly(f"not a read-only statement: {body[:60]}")
    # text inside string literals / quoted identifiers is data (e.g. LIKE 'CREATE…', a note containing ';'): strip it before looking
    # for a statement separator or a verb. A ';' OUTSIDE a literal is a second statement and is refused.
    bare = re.sub(r"'(?:[^'\\]|\\.|'')*'", "''", body)
    bare = re.sub(r'"[^"]*"', '""', bare)
    if ";" in bare:
        raise NotReadOnly(f"multi-statement text refused: {body[:60]}")
    hit = _FORBIDDEN.search(bare)
    if hit:
        raise NotReadOnly(f"{hit.group(1).upper()} in a health query: {body[:60]}")


class Runner:
    """Runs only reads. `cursor_factory` is injectable so tests can drive the checks with canned rows."""

    def __init__(self, conn):
        self.conn = conn
        self.log: list[str] = []

    def q(self, sql: str) -> list[dict]:
        assert_read_only(sql)
        self.log.append(" ".join(sql.split()))
        cur = self.conn.cursor()
        try:
            cur.execute(sql)
            if not cur.description:
                return []
            cols = [d[0].lower() for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
        finally:
            cur.close()

    def get(self, source: str, directory: str) -> list[tuple]:
        tmp_root, target = os.path.realpath(tempfile.gettempdir()), os.path.realpath(directory)
        if not (target == tmp_root or target.startswith(tmp_root + os.sep)):
            raise NotReadOnly(f"GET may only download into a temporary directory, not {directory}")
        sql = f"GET {source} file://{directory.rstrip('/')}/"
        assert_read_only(sql)
        self.log.append(sql)
        cur = self.conn.cursor()
        try:
            cur.execute(sql)
            return cur.fetchall()
        finally:
            cur.close()


# ── results ──────────────────────────────────────────────────────────────────
def result(cid: str, title: str, status: str, summary: str, evidence: dict | None = None, sql: list[str] | None = None) -> dict:
    assert status in STATES, status
    return {"id": cid, "title": title, "status": status, "summary": summary, "evidence": evidence or {}, "sql": sql or []}


def _unverified_on_error(cid: str, title: str, err: Exception, sql: list[str]) -> dict:
    """A statement that raised proves nothing about the property: Snowflake answers 'does not exist OR not authorized' for both."""
    first = " ".join(str(err).split())[:140] if not isinstance(err, NotReadOnly) else str(err)
    kind = "refused as not read-only" if isinstance(err, NotReadOnly) else "could not be run by this role"
    return result(cid, title, UNVERIFIED, f"the check {kind} — it establishes nothing either way.", {"error": first}, sql)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ── names ────────────────────────────────────────────────────────────────────
def expected_app_grants() -> set[tuple[str, str, str]]:
    """The exact data/privilege set deploy/03_grants.sql gives the app role: (privilege, granted_on, name)."""
    t = f"{DB}.{SCHEMA}"
    g = {("USAGE", "WAREHOUSE", WH), ("USAGE", "DATABASE", DB), ("USAGE", "SCHEMA", t),
         ("USAGE", "DATABASE_ROLE", "SNOWFLAKE.CORTEX_USER"), ("USAGE", "CORTEX_SEARCH_SERVICE", f"{t}.CORPUS_SEARCH"),
         ("READ", "STAGE", f"{t}.SEMANTIC_STAGE"),
         ("INSERT", "TABLE", f"{t}.DECISION_LEDGER"), ("SELECT", "TABLE", f"{t}.DECISION_LEDGER")}
    g |= {("SELECT", "TABLE", f"{t}.{n}") for n in ("REGULATORY_CORPUS", "ALERTS", "TRANSACTIONS")}
    g |= {("SELECT", "VIEW", f"{t}.{n}") for n in ("ALERT_TXN_SUMMARY", "ALERTS_CURRENT", "DECISION_LEDGER_INTEGRITY_V")}
    return g


def optional_app_grants() -> set[tuple[str, str, str]]:
    """Read access to the audit-export store that deploy/05_audit_export.sql gives the app role WHEN the (opt-in) store is provisioned.
    Allowed if present, never required; anything else on the audit schema is still 'beyond the least-privilege set'."""
    return {("USAGE", "SCHEMA", f"{DB}.AUDIT"), ("SELECT", "TABLE", f"{DB}.AUDIT.LEDGER_EXPORT"), ("SELECT", "TABLE", f"{DB}.AUDIT.DECISION_OUTCOMES")}


def is_platform_owned(privilege: str, granted_on: str, name: str) -> bool:
    """What owning a container-runtime Streamlit app adds to the owner role. These are objects the PLATFORM creates for the app
    (its service and internal stage); they are not data privileges and are accounted for separately in the report."""
    t = f"{DB}.{SCHEMA}"
    if granted_on == "STREAMLIT" and name == f"{t}.{APP_NAME}" and privilege == "OWNERSHIP":
        return True
    if granted_on == "STAGE" and name.startswith(f'{t}."Streamlit_internal_') and privilege == "OWNERSHIP":
        return True
    if granted_on in ("SERVICE", "SERVICE ROLE") and name.startswith(f"{t}.STPLATSTREAMLIT") and privilege in ("USAGE", "MONITOR"):
        return True
    return False


# ── the checks ───────────────────────────────────────────────────────────────
def check_session(r: Runner) -> dict:
    cid, title = "session", "Session is the app role with secondary roles NONE"
    sql = ["SELECT CURRENT_ROLE() AS R, CURRENT_SECONDARY_ROLES()::VARCHAR AS SEC, CURRENT_DATABASE() AS D, CURRENT_SCHEMA() AS S, CURRENT_WAREHOUSE() AS W"]
    try:
        row = r.q(sql[0])[0]
    except Exception as err:  # noqa: BLE001
        return _unverified_on_error(cid, title, err, sql)
    isolated = '"roles":""' in (row["sec"] or "")
    ev = {"role": row["r"], "secondary_roles": row["sec"], "database": row["d"], "schema": row["s"], "warehouse": row["w"]}
    if (row["r"] or "").upper() != APP.upper():
        return result(cid, title, UNVERIFIED, f"ran as {row['r']}, not {APP}: every 'what the app role can see' result below describes {row['r']}, not the app.", ev, sql)
    if not isolated:
        return result(cid, title, UNAVAILABLE, "secondary roles are active — the session carries more than the app role, so no least-privilege claim holds.", ev, sql)
    return result(cid, title, HEALTHY, f"role {APP}, secondary roles NONE, {row['d']}.{row['s']} on {row['w']}.", ev, sql)


def check_grants(r: Runner) -> dict:
    cid, title = "app_role_grants", "App role holds exactly the least-privilege grants"
    sql = [f"SHOW GRANTS TO ROLE {APP}"]
    try:
        rows = r.q(sql[0])
    except Exception as err:  # noqa: BLE001
        return _unverified_on_error(cid, title, err, sql)
    actual = {(g["privilege"], g["granted_on"], g["name"]) for g in rows}
    want = expected_app_grants()
    platform = {g for g in actual if is_platform_owned(*g)}
    optional = actual & optional_app_grants()
    missing, extra = sorted(want - actual), sorted(actual - want - platform - optional)
    ledger = sorted(p for p, on, n in actual if on == "TABLE" and n.endswith(".DECISION_LEDGER"))
    creates = sorted(p for p, _, _ in actual if p.startswith("CREATE"))
    ev = {"granted": len(actual), "expected_data_grants": len(want), "platform_owned_app_objects": len(platform),
          "audit_export_read_grants": len(optional), "ledger_privileges": ledger, "create_privileges": creates,
          "missing": [" ".join(m) for m in missing], "unexpected": [" ".join(e) for e in extra]}
    if missing or extra or ledger != ["INSERT", "SELECT"] or creates:
        why = []
        if missing:
            why.append(f"{len(missing)} required grant(s) missing")
        if extra:
            why.append(f"{len(extra)} grant(s) beyond the least-privilege set")
        if ledger != ["INSERT", "SELECT"]:
            why.append(f"ledger privileges are {ledger}, not exactly INSERT+SELECT")
        if creates:
            why.append(f"CREATE privilege(s) present: {creates}")
        return result(cid, title, UNAVAILABLE, "; ".join(why) + ".", ev, sql)
    return result(cid, title, HEALTHY,
                  f"{len(want)} data grants exactly as deploy/03_grants.sql (ledger INSERT+SELECT only, no CREATE privilege) plus "
                  f"{len(platform)} platform-owned objects of its own Streamlit app (ownership of the app and its internal stage, service usage)"
                  + (f" and {len(optional)} read grants on the audit-export store (provisioned, opt-in)" if optional else "") + ". Nothing else.", ev, sql)


def check_ledger_grantees(r: Runner) -> dict:
    cid, title = "ledger_grantees", "Nobody but the owner, the app role, ACCOUNTADMIN and (if provisioned) the audit reader holds a privilege on the ledger"
    sql = [f"SHOW GRANTS ON TABLE {DB}.{SCHEMA}.DECISION_LEDGER"]
    try:
        rows = r.q(sql[0])
    except Exception as err:  # noqa: BLE001
        return _unverified_on_error(cid, title, err, sql)
    by: dict[str, list[str]] = {}
    for g in rows:
        by.setdefault(g["grantee_name"], []).append(g["privilege"])
    by = {k: sorted(v) for k, v in by.items()}
    allowed = {ADMIN, APP, "ACCOUNTADMIN", AUDIT}
    stray = sorted(k for k in by if k not in allowed)
    ev = {"grantees": by}
    if stray:
        return result(cid, title, UNAVAILABLE, f"unexpected grantee(s) on the ledger: {stray}.", ev, sql)
    if AUDIT in by and by[AUDIT] != ["SELECT"]:
        return result(cid, title, UNAVAILABLE, f"the audit role may only SELECT the ledger (deploy/05_audit_export.sql), it holds {by[AUDIT]}.", ev, sql)
    if by.get(APP) != ["INSERT", "SELECT"] or "OWNERSHIP" not in by.get(ADMIN, []):
        return result(cid, title, UNAVAILABLE, f"grantee set is not as designed (owner {ADMIN}: {by.get(ADMIN)}, app {APP}: {by.get(APP)}).", ev, sql)
    return result(cid, title, HEALTHY, f"grantees: {', '.join(f'{k} {v}' for k, v in sorted(by.items()))} — no PUBLIC, no other role.", ev, sql)


def check_search_service(r: Runner, expected_rows: int | None) -> dict:
    cid, title = "search_service", "Cortex Search service CORPUS_SEARCH is ACTIVE and indexes the expected rows"
    sql = [f"SHOW CORTEX SEARCH SERVICES LIKE 'CORPUS_SEARCH' IN SCHEMA {DB}.{SCHEMA}"]
    try:
        rows = r.q(sql[0])
    except Exception as err:  # noqa: BLE001
        return _unverified_on_error(cid, title, err, sql)
    if not rows:
        return result(cid, title, UNAVAILABLE, "no CORPUS_SEARCH service is visible to this role.", {}, sql)
    s = rows[0]
    n = int(s.get("source_data_num_rows") or 0)
    ev = {"indexing_state": s.get("indexing_state"), "serving_state": s.get("serving_state"), "source_data_num_rows": n,
          "expected_rows": expected_rows, "target_lag": s.get("target_lag"), "warehouse": s.get("warehouse"), "embedding_model": s.get("embedding_model")}
    if s.get("indexing_state") != "ACTIVE" or s.get("serving_state") != "ACTIVE":
        return result(cid, title, UNAVAILABLE, f"indexing {s.get('indexing_state')}, serving {s.get('serving_state')}.", ev, sql)
    if expected_rows is None:
        return result(cid, title, UNVERIFIED, f"ACTIVE/ACTIVE with {n} rows, but the expected row count could not be read from the manifest.", ev, sql)
    if n != expected_rows:
        return result(cid, title, UNAVAILABLE, f"ACTIVE but indexes {n} rows, expected {expected_rows} (PROVEN + ASSUMED). ALTER CORTEX SEARCH SERVICE … REFRESH.", ev, sql)
    return result(cid, title, HEALTHY, f"indexing ACTIVE, serving ACTIVE, {n} rows indexed (= PROVEN + ASSUMED; NEEDS-VERIFICATION is excluded).", ev, sql)


def check_search_probe(r: Runner) -> dict:
    cid, title = "search_probe", "Cortex Search answers a query (serving, not just state)"
    q = json.dumps({"query": "STR filing deadline 7 working days", "columns": ["RULE_ID", "EVIDENCE_LEVEL"], "limit": 3})
    sql = [f"SELECT PARSE_JSON(SNOWFLAKE.CORTEX.SEARCH_PREVIEW('{DB}.{SCHEMA}.CORPUS_SEARCH', '{q}')):results AS RESULTS"]
    try:
        rows = r.q(sql[0])
    except Exception as err:  # noqa: BLE001
        return _unverified_on_error(cid, title, err, sql)
    try:
        res = json.loads(rows[0]["results"]) if isinstance(rows[0]["results"], str) else rows[0]["results"]
    except Exception:  # noqa: BLE001
        res = None
    if not res:
        return result(cid, title, UNAVAILABLE, "the service returned no results for a query the corpus must answer.", {}, sql)
    levels = sorted({x.get("EVIDENCE_LEVEL") for x in res})
    ev = {"top_rules": [f"{x.get('RULE_ID')}:{x.get('EVIDENCE_LEVEL')}" for x in res]}
    if set(levels) - {"PROVEN", "ASSUMED"}:
        return result(cid, title, UNAVAILABLE, f"a result carries an evidence level the index must exclude: {levels}.", ev, sql)
    return result(cid, title, HEALTHY, f"served {len(res)} results ({', '.join(ev['top_rules'])}); none is NEEDS-VERIFICATION.", ev, sql)


def check_corpus(r: Runner, manifest: dict | None) -> dict:
    cid, title = "corpus", "Corpus version and counts match the manifest"
    sql = [f"SELECT EVIDENCE_LEVEL, COUNT(*) AS N FROM {DB}.{SCHEMA}.REGULATORY_CORPUS GROUP BY 1 ORDER BY 1",
           f"SELECT COUNT(DISTINCT CORPUS_VERSION) AS NV, MAX(CORPUS_VERSION) AS V, COUNT_IF(SOURCE_AUTHORITY IS NULL OR REVIEW_STATUS IS NULL OR OWNER IS NULL) AS NULLS FROM {DB}.{SCHEMA}.REGULATORY_CORPUS"]
    try:
        counts = {x["evidence_level"]: int(x["n"]) for x in r.q(sql[0])}
        ver = r.q(sql[1])[0]
    except Exception as err:  # noqa: BLE001
        return _unverified_on_error(cid, title, err, sql)
    ev = {"counts": counts, "corpus_versions": int(ver["nv"]), "version": ver["v"], "governance_nulls": int(ver["nulls"]), "total": sum(counts.values())}
    if not manifest:
        return result(cid, title, UNVERIFIED, f"corpus v{ver['v']} has {sum(counts.values())} rules {counts}, but no local manifest to compare with.", ev, sql)
    want = {"PROVEN": manifest["counts"]["PROVEN"], "ASSUMED": manifest["counts"]["ASSUMED"], "NEEDS-VERIFICATION": manifest["counts"]["NEEDS-VERIFICATION"]}
    ev["expected"] = want
    ev["expected_version"] = manifest.get("corpus_version")
    if counts != want or int(ver["nv"]) != 1 or ver["v"] != manifest.get("corpus_version") or int(ver["nulls"]):
        return result(cid, title, UNAVAILABLE, f"corpus v{ver['v']} {counts} differs from the manifest v{manifest.get('corpus_version')} {want} "
                      f"(or governance columns are NULL: {ver['nulls']}). Re-run: python3 scripts/load_corpus.py --upsert", ev, sql)
    return result(cid, title, HEALTHY, f"corpus v{ver['v']}: {counts} = {sum(counts.values())} rules, one version, governance columns populated, identical to the manifest.", ev, sql)


def check_semantic_file(r: Runner, local: Path | None) -> dict:
    cid, title = "semantic_model_file", "Semantic model is on the stage and byte-identical to the repository's"
    stage = f"@{DB}.{SCHEMA}.SEMANTIC_STAGE"
    sql = [f"LIST {stage}"]
    try:
        files = r.q(sql[0])
    except Exception as err:  # noqa: BLE001
        return _unverified_on_error(cid, title, err, sql)
    hit = [f for f in files if f["name"].endswith("semantic_model.yaml")]
    if not hit:
        return result(cid, title, UNAVAILABLE, "semantic_model.yaml is not on the stage. Re-run: python3 scripts/upload_semantic_model.py", {"files": [f["name"] for f in files]}, sql)
    ev = {"stage_listing_bytes": hit[0]["size"], "last_modified": hit[0]["last_modified"],
          "note": "LIST reports the ENCRYPTED size/md5 of the stored object, so identity is checked on the downloaded bytes"}
    if local is None or not local.exists():
        return result(cid, title, UNVERIFIED, "the file is on the stage, but there is no local copy to compare it with.", ev, sql)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            r.get(f"{stage}/semantic_model.yaml", tmp)
            got = Path(tmp) / "semantic_model.yaml"
            stage_sha = sha256_file(got)
        except Exception as err:  # noqa: BLE001
            return _unverified_on_error(cid, title, err, sql)
    want = sha256_file(local)
    ev.update({"stage_sha256": stage_sha[:16], "local_sha256": want[:16]})
    if stage_sha != want:
        return result(cid, title, UNAVAILABLE, "the stage copy DIFFERS from the repository's semantic model (re-upload: python3 scripts/upload_semantic_model.py).", ev, sql)
    return result(cid, title, HEALTHY, f"present and byte-identical to the repository's file (sha256 {want[:12]}…).", ev, sql)


def check_census(r: Runner) -> dict:
    cid, title = "ledger_census", "Ledger integrity census (per-row hashes)"
    sql = [f"SELECT INTEGRITY_STATUS, COUNT(*) AS N FROM {DB}.{SCHEMA}.DECISION_LEDGER_INTEGRITY_V GROUP BY 1 ORDER BY 1"]
    try:
        census = {x["integrity_status"]: int(x["n"]) for x in r.q(sql[0])}
    except Exception as err:  # noqa: BLE001
        return _unverified_on_error(cid, title, err, sql)
    total = sum(census.values())
    ev = {"census": census, "total": total}
    if census.get("TAMPERED"):
        return result(cid, title, UNAVAILABLE, f"{census['TAMPERED']} row(s) read TAMPERED — the stored hash does not match the stored row.", ev, sql)
    unknown = {k: v for k, v in census.items() if k not in ("INTACT", "LEGACY_UNHASHED", "TAMPERED")}
    if unknown:
        return result(cid, title, UNVERIFIED, f"unrecognised integrity status {unknown}.", ev, sql)
    if census.get("LEGACY_UNHASHED"):
        return result(cid, title, UNVERIFIED, f"{census.get('INTACT', 0)} INTACT, 0 TAMPERED, but {census['LEGACY_UNHASHED']} legacy row(s) predate ROW_HASH: "
                      "nothing can be said about their content — only that they exist.", ev, sql)
    if total == 0:
        return result(cid, title, HEALTHY, "the ledger is empty: nothing to verify, nothing tampered (the integrity view answers).", ev, sql)
    return result(cid, title, HEALTHY, f"{census.get('INTACT', 0)} of {total} row(s) INTACT, 0 TAMPERED, 0 legacy.", ev, sql)


def check_reconciliation(r: Runner, skills=None) -> list[dict]:
    """Latest whole-ledger reconciliation (skills/audit.py via CoPilotSkills) → two results: the reconciliation and the deletion witness."""
    t1, t2 = "Latest ledger reconciliation (read-only)", "Deletion witness: audit export reconciles with the ledger"
    sql = ["(skills.audit.fetch_ledger_rows + fetch_anchor: SELECT-only, see skills/audit.py)"]
    try:
        if skills is None:
            from skills import CoPilotSkills
            skills = CoPilotSkills(r.conn)
        rep = skills.ledger_reconciliation()
    except Exception as err:  # noqa: BLE001
        e = _unverified_on_error("reconciliation", t1, err, sql)
        return [e, {**e, "id": "deletion_witness", "title": t2}]
    verdict = rep["verdict"]
    ev = {"verdict": verdict, "ledger_rows": rep["ledger_rows"], "by_integrity": rep["by_integrity"], "findings": [f.get("code", str(f))[:60] for f in rep.get("findings", [])][:8],
          "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")}
    if verdict == "COMPROMISED":
        a = result("reconciliation", t1, UNAVAILABLE, f"COMPROMISED: {ev['findings']}", ev, sql)
    elif verdict == "CONSISTENT":
        a = result("reconciliation", t1, HEALTHY, f"CONSISTENT over {rep['ledger_rows']} row(s): {rep['by_integrity']}.", ev, sql)
    else:
        a = result("reconciliation", t1, UNVERIFIED, f"ATTENTION over {rep['ledger_rows']} row(s) {rep['by_integrity']}: findings {ev['findings']} — nothing is broken, but not everything can be verified.", ev, sql)
    anchor = rep["anchor"]
    wev = {"audit_export_present": bool(anchor["present"]), "deletion_detectable": bool(rep["deletion_detectable"]), "reason": anchor.get("reason"),
           "deleted_ids": rep.get("deleted_ids", []), "limits": list(rep.get("limits", []))[:2]}
    if rep.get("deleted_ids") or verdict == "COMPROMISED" and anchor["present"]:
        b = result("deletion_witness", t2, UNAVAILABLE, f"the export and the ledger DISAGREE (deleted: {wev['deleted_ids'] or 'see findings'}).", wev, sql)
    elif not anchor["present"]:
        b = result("deletion_witness", t2, UNVERIFIED, "no audit export exists: DELETION OF LEDGER ROWS BY THE OWNER ROLE WOULD NOT BE DETECTED. "
                   f"({anchor.get('reason')}). Provision it: python3 scripts/audit_ledger.py provision", wev, sql)
    elif rep["deletion_detectable"]:
        b = result("deletion_witness", t2, HEALTHY, "an audit export exists, its chain is intact and it reconciles with the ledger (a witness, not WORM storage — "
                   "ACCOUNTADMIN or a holder of both roles could alter both).", wev, sql)
    else:
        b = result("deletion_witness", t2, UNVERIFIED, "an audit export exists but deletion is not reliably detectable yet (rows awaiting export or chain not verifiable).", wev, sql)
    return [a, b]


def _app_files(base: Path) -> list[str]:
    import yaml
    cfg = yaml.safe_load((base / "snowflake.yml").read_text())["streamlit"]
    return [cfg["main_file"], *cfg.get("additional_source_files", [])]


def bundle_digest(files: dict[str, str]) -> str:
    """The deployment version: sha256 over 'path:sha256' lines of the code files, sorted. Same function for local and hosted."""
    return hashlib.sha256("\n".join(f"{p}:{h}" for p, h in sorted(files.items())).encode()).hexdigest()


def check_app(r: Runner, base: Path, profile=None) -> dict:
    cid, title = "application", "Hosted Streamlit app: owner, warehouse and deployed code version"
    fq = f"{DB}.{SCHEMA}.{APP_NAME}"
    sql = [f"SHOW STREAMLITS LIKE '{APP_NAME}' IN SCHEMA {DB}.{SCHEMA}", f"DESC STREAMLIT {fq}"]
    try:
        rows = r.q(sql[0])
    except Exception as err:  # noqa: BLE001
        return _unverified_on_error(cid, title, err, sql)
    if not rows:
        return result(cid, title, UNAVAILABLE, f"no Streamlit app {APP_NAME} is visible to {APP} in {DB}.{SCHEMA}.", {}, sql)
    app = rows[0]
    ev = {"owner": app.get("owner"), "query_warehouse": app.get("query_warehouse"), "url_id": app.get("url_id"), "created_on": str(app.get("created_on"))[:19],
          "rendered_in_snowsight": "NOT VERIFIED — no query can see what the browser rendered"}
    problems = []
    if (app.get("owner") or "").upper() != APP.upper():
        problems.append(f"owner is {app.get('owner')}, not {APP} (the app would run with the owner's privileges)")
    if (app.get("query_warehouse") or "").upper() != WH.upper():
        problems.append(f"query warehouse is {app.get('query_warehouse')}, not {WH}")
    try:
        desc = r.q(sql[1])[0]
        ev["runtime"] = desc.get("runtime_name")
        ev["compute_pool"] = desc.get("compute_pool")
        uri = desc.get("live_version_location_uri")
    except Exception as err:  # noqa: BLE001
        uri = None
        ev["desc_error"] = " ".join(str(err).split())[:100]
    local_files = {}
    try:
        for rel in _app_files(base):
            text = (base / rel).read_text(encoding="utf-8")
            local_files[Path(rel).name if rel.startswith("skills/") else rel] = hashlib.sha256((profile.render_text(text) if profile else text).encode()).hexdigest()
    except Exception as err:  # noqa: BLE001
        ev["local_error"] = " ".join(str(err).split())[:100]
    if not uri or not local_files:
        st = UNAVAILABLE if problems else UNVERIFIED
        return result(cid, title, st, ("; ".join(problems) + "; " if problems else "") + "the deployed code could not be compared with the local source.", ev, sql)
    hosted: dict[str, str] = {}
    with tempfile.TemporaryDirectory() as tmp:
        try:
            r.get(f"'{uri.rstrip('/')}/'", tmp)
        except Exception as err:  # noqa: BLE001
            ev["get_error"] = " ".join(str(err).split())[:100]
        for p in Path(tmp).rglob("*"):
            if p.is_file() and p.name not in ("pyproject.toml", "config.toml"):       # platform-generated, not in the repo
                hosted[p.name] = sha256_file(p)
    if not hosted:
        st = UNAVAILABLE if problems else UNVERIFIED
        return result(cid, title, st, ("; ".join(problems) + "; " if problems else "") + "the live version's files could not be downloaded to compare.", ev, sql)
    same = sorted(k for k in local_files if hosted.get(k) == local_files[k])
    differ = sorted(k for k in local_files if k in hosted and hosted[k] != local_files[k])
    absent = sorted(k for k in local_files if k not in hosted)
    ev.update({"local_bundle": bundle_digest(local_files)[:16], "hosted_bundle": bundle_digest({k: hosted[k] for k in local_files if k in hosted})[:16],
               "files_identical": len(same), "files_total": len(local_files), "differ": differ, "missing_on_hosted": absent})
    if differ or absent:
        problems.append(f"deployed code is behind/ahead of the source: {len(same)}/{len(local_files)} files identical; differ {differ}; missing {absent}. Redeploy: snow streamlit deploy --replace")
    if problems:
        return result(cid, title, UNAVAILABLE, "; ".join(problems) + ".", ev, sql)
    return result(cid, title, HEALTHY, f"owner {APP}, warehouse {WH}, {len(same)}/{len(local_files)} code files byte-identical to the source "
                  f"(bundle {ev['local_bundle']}…). What Snowsight rendered is NOT verified by this check.", ev, sql)


def check_complete_probe(r: Runner, skills, deep: bool) -> dict:
    cid, title = "complete_probe", "Cortex Complete answers (one call)"
    if not deep:
        return result(cid, title, UNVERIFIED, "not exercised: one real model call (≈13 s, billed). Run with --deep.", {}, [])
    try:
        out = skills._cortex_complete("Reply with the single word OK")
    except Exception as err:  # noqa: BLE001
        return result(cid, title, UNAVAILABLE, "Cortex Complete raised: " + " ".join(str(err).split())[:120], {}, [])
    if "ok" in str(out).lower():
        return result(cid, title, HEALTHY, f"answered by {getattr(skills, 'last_model_used', '?')}.", {"model": getattr(skills, "last_model_used", None)}, [])
    return result(cid, title, UNAVAILABLE, "Cortex Complete returned an unexpected answer.", {}, [])


def check_analyst_probe(r: Runner, deep: bool) -> dict:
    cid, title = "analyst_probe", "Cortex Analyst answers over the semantic model (one question)"
    if not deep:
        return result(cid, title, UNVERIFIED, "not exercised: one Analyst REST call over the stage model. Run with --deep.", {}, [])
    try:
        from skills import CorpusAnalyst
        res = CorpusAnalyst(r.conn).ask("How many alerts are there in each status?")
    except Exception as err:  # noqa: BLE001
        return result(cid, title, UNAVAILABLE, "Cortex Analyst raised: " + " ".join(str(err).split())[:120], {}, [])
    if res.get("available") and res.get("generated_sql") and res.get("rows"):
        return result(cid, title, HEALTHY, f"answered with SQL and {len(res['rows'])} row(s).", {"rows": res["rows"][:4]}, [])
    return result(cid, title, UNAVAILABLE, f"Analyst unavailable: {str(res.get('warnings'))[:120]}", {}, [])


# ── orchestration ────────────────────────────────────────────────────────────
def load_manifest(base: Path) -> dict | None:
    try:
        import yaml
        m = yaml.safe_load((base / "domain/corpus/manifest.yaml").read_text())
        m["counts"]  # noqa: B018 — must exist
        return m
    except Exception:  # noqa: BLE001
        return None


def run_checks(conn, base: Path = ROOT, deep: bool = False, skills=None, profile=None) -> dict:
    r = Runner(conn)
    manifest = load_manifest(base)
    expected_rows = manifest["counts"].get("search_indexed") if manifest else None
    if skills is None and deep:
        from skills import CoPilotSkills
        skills = CoPilotSkills(conn)
    checks = [check_session(r), check_grants(r), check_ledger_grantees(r), check_search_service(r, expected_rows), check_search_probe(r),
              check_corpus(r, manifest), check_semantic_file(r, base / "domain/corpus/export/semantic_model.yaml"), check_census(r),
              *check_reconciliation(r, skills), check_app(r, base, profile),
              check_complete_probe(r, skills, deep), check_analyst_probe(r, deep)]
    summary = {s: sum(1 for c in checks if c["status"] == s) for s in STATES}
    return {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "environment": {"database": DB, "schema": SCHEMA, "warehouse": WH, "app_role": APP},
            "read_only": True, "statements_run": len(r.log), "summary": summary, "checks": checks,
            "overall": UNAVAILABLE if summary[UNAVAILABLE] else (UNVERIFIED if summary[UNVERIFIED] else HEALTHY)}


GLYPH = {HEALTHY: "✔ HEALTHY    ", UNAVAILABLE: "✘ UNAVAILABLE", UNVERIFIED: "? UNVERIFIED "}


def render(report: dict) -> str:
    env = report["environment"]
    out = [f"HEALTH — {env['database']}.{env['schema']} · warehouse {env['warehouse']} · app role {env['app_role']} · {report['generated_at']} · read-only ({report['statements_run']} statements)", ""]
    for c in report["checks"]:
        out.append(f"{GLYPH[c['status']]}  {c['title']}")
        out.append(f"{'':15s}{c['summary']}")
    s = report["summary"]
    out += ["", f"OVERALL {report['overall']}: {s[HEALTHY]} healthy · {s[UNAVAILABLE]} unavailable · {s[UNVERIFIED]} unverified",
            "HEALTHY = shown to hold now · UNAVAILABLE = shown NOT to hold · UNVERIFIED = no evidence either way (never read as healthy)"]
    return "\n".join(out)


def main() -> int:
    global ADMIN, APP, AUDIT, DB, WH
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--role", help=f"role to connect as (default {APP}); anything else makes the grant checks UNVERIFIED")
    ap.add_argument("--deep", action="store_true", help="also make one Cortex Complete call and one Cortex Analyst call (billed)")
    ap.add_argument("--json", action="store_true", help="print JSON instead of text")
    ap.add_argument("--out", help="also write the JSON report to this file")
    ap.add_argument("--strict", action="store_true", help="exit 3 when any check is UNVERIFIED")
    ap.add_argument("--profile", choices=["default", "cleanroom"], default="default")
    ap.add_argument("--suffix", default="CR")
    args = ap.parse_args()
    from skills.connection import SnowflakeConfigError, SnowflakeConnectError, connect_from_env, load_env, missing_config, redact
    load_env(ROOT)
    profile = None
    if args.profile != "default":
        import envprofile
        profile = envprofile.get_profile(args.profile, args.suffix)
        ADMIN, APP, AUDIT, DB, WH = profile.admin_role, profile.app_role, profile.audit_role, profile.database, profile.warehouse
        os.environ.update(profile.scope_env())
    if missing_config():
        print("ERROR: missing Snowflake configuration: " + ", ".join(missing_config()) + " (copy .env.example to .env).", file=sys.stderr)
        return 1
    try:
        conn = connect_from_env(role=args.role or APP)
    except (SnowflakeConfigError, SnowflakeConnectError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    try:
        report = run_checks(conn, ROOT, deep=args.deep, profile=profile)
    finally:
        conn.close()
    text = json.dumps(report, indent=2, default=str)
    text = redact(text)
    if args.out:
        Path(args.out).write_text(text + "\n")
    print(text if args.json else redact(render(report)))
    if report["summary"][UNAVAILABLE]:
        return 2
    return 3 if args.strict and report["summary"][UNVERIFIED] else 0


if __name__ == "__main__":
    raise SystemExit(main())
