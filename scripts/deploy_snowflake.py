"""
deploy_snowflake.py — one command to reproduce the Snowflake side of the deployment.

Runs the executable artifacts in order, each as the role it is meant for:

    preflight   ACCOUNTADMIN     (read-only)                 clean-room only: proves the target namespace is EMPTY
    bootstrap   ACCOUNTADMIN     deploy/00_bootstrap.sql     warehouse, database, schema
    roles       ACCOUNTADMIN     deploy/01_roles.sql         FIU_ADMIN_ROLE + FIU_APP_ROLE (+ grants to you)
    ownership   ACCOUNTADMIN     (generated)                 transfer pre-existing objects to FIU_ADMIN_ROLE
    ddl         FIU_ADMIN_ROLE   domain/corpus/export/ddl/*  tables, views, Cortex Search service, ledger
    data        FIU_ADMIN_ROLE   scripts/load_corpus.py, setup_alerts.py, upload_semantic_model.py
    grants      ACCOUNTADMIN     deploy/03_grants.sql        app role: ledger INSERT+SELECT only, Cortex
    verify      FIU_APP_ROLE     deploy/04_verify_ledger_rbac.sql   PROVES UPDATE/DELETE denied (TRUNCATE/DROP/ALTER proven from grants)
    app         FIU_APP_ROLE     snow streamlit deploy       hosted app, CREATED by the app role (temporary CREATE STREAMLIT grant)
    health      FIU_APP_ROLE     scripts/health_check.py     read-only HEALTHY / UNAVAILABLE / UNVERIFIED report
    test        owner + app role pytest -m live              the live suites against THIS environment
    audit       ACCOUNTADMIN → FIU_AUDIT_ROLE → FIU_APP_ROLE   OPTIONAL (never a default): provision the audit-export witness, export, reconcile
    replay      FIU_APP_ROLE     scripts/eval_live_replay.py OPTIONAL (never a default; costs Cortex credits): the real model over every seeded alert
    teardown    ACCOUNTADMIN     (clean-room only, explicit)  drops the clean-room environment; never part of a default run

Nothing is changed unless you pass --apply. Without it the script prints the plan and exits 0.

    python3 scripts/deploy_snowflake.py                                  # plan only (production profile)
    python3 scripts/deploy_snowflake.py --apply                          # production: bootstrap → verify (the original 7 steps)
    python3 scripts/deploy_snowflake.py --apply --step verify            # just the RBAC proof

    python3 scripts/deploy_snowflake.py --profile cleanroom              # plan: the same path into a suffixed, isolated namespace
    python3 scripts/deploy_snowflake.py --profile cleanroom --apply      # preflight → … → app → health → test, from a RENDERED copy

A clean-room profile renders a copy of the repository in which the five account-level identifiers carry a suffix
(scripts/envprofile.py), so it shares no named object with production, and runs every step from that copy.
Production objects are never touched by a clean-room run; each connection is checked against the profile's scope.

Credentials come from .env (see .env.example). The connecting user must be able to USE ROLE ACCOUNTADMIN for the
bootstrap / roles / ownership / grants steps. Errors are redacted (no passwords / tokens / account / statement data).
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
from skills.connection import (  # noqa: E402
    SnowflakeConfigError, SnowflakeConnectError, connect_from_env, load_env, missing_config, redact,
)
import envprofile  # noqa: E402

# These literals are what a RENDERED copy of this file changes (scripts/envprofile.py); main() overrides them for a profile.
ADMIN, APP, AUDIT = "FIU_ADMIN_ROLE", "FIU_APP_ROLE", "FIU_AUDIT_ROLE"
DB, SCHEMA, WH = "FIU_COPILOT", "AML", "FIU_WH"
DDL_ORDER = ["regulatory_corpus.sql", "alerts.sql", "eval_labels.sql", "transactions.sql", "views.sql"]
OWNED_OBJECTS = [("TABLE", "REGULATORY_CORPUS"), ("TABLE", "ALERTS"), ("TABLE", "TRANSACTIONS"),
                 ("TABLE", "DECISION_LEDGER"), ("VIEW", "ALERT_TXN_SUMMARY"), ("VIEW", "ALERTS_CURRENT"),
                 ("VIEW", "DECISION_LEDGER_INTEGRITY_V"), ("STAGE", "SEMANTIC_STAGE")]
ORIGINAL_STEPS = ["bootstrap", "roles", "ownership", "ddl", "data", "grants", "verify"]
ALL_STEPS = ["preflight"] + ORIGINAL_STEPS + ["app", "health", "test", "audit", "replay", "teardown"]
CLEANROOM_DEFAULT_STEPS = ["preflight"] + ORIGINAL_STEPS + ["app", "health", "test"]
STEPS = ORIGINAL_STEPS          # kept for callers that import it
DDL_ROLE = None                 # set in main(); "current" = the connection's own role (accounts where the roles do not exist yet)
BASE = ROOT                     # where SQL / scripts / the app are read from: the repository, or the rendered copy
PROFILE = envprofile.DEFAULT
OPTS = argparse.Namespace(reuse=False, snow_connection="fiu-copilot", confirm_teardown=None, audit_out=None)


def split_sql(text: str) -> list[str]:
    from snowflake.connector.util_text import split_statements
    out = []
    for stmt, _ in split_statements(io.StringIO(text), remove_comments=True):
        stmt = stmt.strip().rstrip(";").strip()
        if stmt:
            out.append(stmt)
    return out


def run_statements(conn, statements: list[str], label: str, quiet: bool = False) -> list:
    cur = conn.cursor()
    results = []
    try:
        for i, stmt in enumerate(statements, 1):
            head = " ".join(stmt.split())[:90]
            try:
                cur.execute(stmt)
                rows = cur.fetchall() if cur.description else []
                results.append(rows)
                if not quiet:
                    print(f"    [{i:02d}/{len(statements):02d}] ok   {head}")
            except Exception as err:  # noqa: BLE001
                print(f"    [{i:02d}/{len(statements):02d}] FAIL {head}\n           {redact(str(err)).splitlines()[0][:220]}")
                raise SystemExit(f"{label}: statement {i} failed — stopping.")
    finally:
        cur.close()
    return results


def sql_file(name: str, subs: dict | None = None) -> list[str]:
    path = BASE / name if not Path(name).is_absolute() else Path(name)
    text = path.read_text()
    for k, v in (subs or {}).items():
        text = text.replace("{{" + k + "}}", v)
    return split_sql(text)


def _scope_ok(conn) -> None:
    """A clean-room connection must never have PRODUCTION as its current database / warehouse (a stale .env could do that)."""
    cur = conn.cursor()
    try:
        cur.execute("SELECT CURRENT_DATABASE(), CURRENT_WAREHOUSE()")
        db, wh = cur.fetchone()
    finally:
        cur.close()
    if (db and db.upper() != DB.upper()) or (wh and wh.upper() != WH.upper()):
        conn.close()
        raise SystemExit(f"ERROR: this connection's scope is database={db} warehouse={wh}, but the profile "
                         f"'{PROFILE.name}' is {DB} / {WH}. Refusing to continue (a stale SNOWFLAKE_DATABASE / SNOWFLAKE_WAREHOUSE?).")


def connect(role: str | None):
    try:
        conn = connect_from_env(role=role)
    except (SnowflakeConfigError, SnowflakeConnectError) as err:
        raise SystemExit(f"ERROR: {err}")
    _scope_ok(conn)
    return conn


def _show(conn, sql: str) -> list[dict]:
    cur = conn.cursor()
    try:
        cur.execute(sql)
        cols = [d[0].lower() for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        cur.close()


def _scrub(text: str) -> str:
    """redact() + the org/account path segments of a Snowsight URL (which the identifier redaction does not catch)."""
    text = redact(text)
    return re.sub(r"(app\.snowflake\.com/)[^/\s]+/[^/\s]+/", r"\1<org>/<account>/", text)


# ── steps ────────────────────────────────────────────────────────────────────
def step_preflight(apply: bool):
    print(f"  profile {PROFILE.name}: database {DB}, warehouse {WH}, roles {ADMIN} / {APP} / {AUDIT}")
    if PROFILE.is_default:
        print("  production profile — nothing is asserted absent (the steps are idempotent)")
        return
    prod = set(envprofile.PROD_NAMES)
    if {DB, WH, ADMIN, APP, AUDIT} & prod:
        raise SystemExit("preflight: a clean-room profile must not reuse a production name — refusing.")
    if not apply:
        print(f"  would assert, read-only as ACCOUNTADMIN, that no database {DB}, warehouse {WH} or role {ADMIN}/{APP}/{AUDIT} exists")
        return
    conn = connect("ACCOUNTADMIN")
    existing = []
    for kind, name in (("DATABASES", DB), ("WAREHOUSES", WH), ("ROLES", ADMIN), ("ROLES", APP), ("ROLES", AUDIT)):
        rows = _show(conn, f"SHOW {kind} LIKE '{name}'")
        hit = [r["name"] for r in rows if r["name"].upper() == name.upper()]
        print(f"    {kind[:-1].lower():10s} {name:22s} {'PRESENT' if hit else 'absent'}")
        existing += hit
    conn.close()
    if existing and not OPTS.reuse:
        raise SystemExit(f"preflight: the clean-room namespace is NOT empty ({', '.join(existing)}). A clean-room run needs an empty "
                         "namespace; pass --reuse to re-run the (idempotent) steps against what already exists, or tear it down first.")
    print("  ✓ namespace is empty" if not existing else "  (re-using an existing clean-room environment: --reuse)")


def step_bootstrap(apply: bool):
    stmts = sql_file("deploy/00_bootstrap.sql")
    print(f"  as ACCOUNTADMIN: {len(stmts)} statements (warehouse {WH}, database {DB}, schema {SCHEMA})")
    if apply:
        run_statements(connect("ACCOUNTADMIN"), stmts, "bootstrap")


def step_roles(apply: bool):
    print(f"  as ACCOUNTADMIN: create {ADMIN}, {APP}; grant both to the connecting user")
    if not apply:
        return
    conn = connect("ACCOUNTADMIN")
    user = conn.cursor().execute("SELECT CURRENT_USER()").fetchone()[0]
    stmts = sql_file("deploy/01_roles.sql", {"DEPLOY_USER": f'"{user}"'})
    run_statements(conn, stmts, "roles")


def step_ownership(apply: bool):
    print(f"  as ACCOUNTADMIN: GRANT OWNERSHIP of pre-existing objects to {ADMIN} (only those owned by another role)")
    if not apply:
        return
    conn = connect("ACCOUNTADMIN")
    cur = conn.cursor()
    todo = []
    for kind, name in OWNED_OBJECTS:
        fq = f"{DB}.{SCHEMA}.{name}"
        try:
            if kind == "STAGE":
                cur.execute(f"SHOW STAGES LIKE 'SEMANTIC_STAGE' IN SCHEMA {DB}.{SCHEMA}")
                rows = cur.fetchall()
                cols = [d[0].lower() for d in cur.description]
                owner = rows[0][cols.index("owner")] if rows else None
            else:
                cur.execute(f"SELECT TABLE_OWNER FROM {DB}.INFORMATION_SCHEMA.TABLES "
                            f"WHERE TABLE_SCHEMA='{SCHEMA}' AND TABLE_NAME='{name}'")
                rows = cur.fetchall()
                owner = rows[0][0] if rows else None
        except Exception:
            owner = None
        if owner is None:
            print(f"    - {kind} {name}: not present yet (created by {ADMIN} in the ddl step)")
        elif owner != ADMIN:
            todo.append(f"GRANT OWNERSHIP ON {kind} {fq} TO ROLE {ADMIN} COPY CURRENT GRANTS")
        else:
            print(f"    - {kind} {name}: already owned by {ADMIN}")
    cur.close()
    if todo:
        run_statements(conn, todo, "ownership")


def _role_arg() -> str | None:
    return None if (DDL_ROLE or ADMIN).lower() == "current" else (DDL_ROLE or ADMIN)


def step_ddl(apply: bool):
    for name in DDL_ORDER:
        stmts = sql_file(f"domain/corpus/export/ddl/{name}")
        print(f"  as {DDL_ROLE or ADMIN}: {name} ({len(stmts)} statements)")
        if apply:
            conn = connect(_role_arg())
            run_statements(conn, [f"USE DATABASE {DB}", f"USE SCHEMA {SCHEMA}", f"USE WAREHOUSE {WH}"] + stmts, name, quiet=True)
            print("      ok")


def _child_env(role: str | None) -> dict:
    env = {**os.environ, **PROFILE.scope_env()} if not PROFILE.is_default else {**os.environ}
    if role:
        env["SNOWFLAKE_ROLE"] = role
    return env


def step_data(apply: bool):
    scripts = [["scripts/load_corpus.py", "--upsert"], ["scripts/setup_alerts.py"], ["scripts/upload_semantic_model.py"]]
    for cmd in scripts:
        print(f"  as {DDL_ROLE or ADMIN}: python3 {' '.join(cmd)}")
        if apply:
            r = subprocess.run([sys.executable, *cmd], cwd=BASE, env=_child_env(_role_arg()), capture_output=True, text=True)
            tail = "\n".join(_scrub(r.stdout + r.stderr).strip().splitlines()[-4:])
            print("      " + tail.replace("\n", "\n      "))
            if r.returncode:
                raise SystemExit(f"data step failed: {' '.join(cmd)}")
    print(f"  as {DDL_ROLE or ADMIN}: ALTER CORTEX SEARCH SERVICE CORPUS_SEARCH REFRESH  (index the freshly loaded corpus now, not at the next TARGET_LAG)")
    if apply:
        conn = connect(_role_arg())
        run_statements(conn, [f"USE DATABASE {DB}", f"USE SCHEMA {SCHEMA}",
                              f"ALTER CORTEX SEARCH SERVICE {DB}.{SCHEMA}.CORPUS_SEARCH REFRESH"], "search refresh", quiet=True)
        print("      refresh requested — SHOW CORTEX SEARCH SERVICES shows source_data_num_rows = 36 once indexing completes")


def step_grants(apply: bool):
    stmts = sql_file("deploy/03_grants.sql")
    print(f"  as ACCOUNTADMIN: {len(stmts)} grants — {APP}: ledger SELECT+INSERT only; Cortex; read-only reference data")
    if apply:
        run_statements(connect("ACCOUNTADMIN"), stmts, "grants")


def step_verify(apply: bool) -> bool:
    print(f"  as {APP} (secondary roles NONE): SELECT, INSERT(rolled back), UPDATE/DELETE WHERE 1=0 (must be denied); "
          "TRUNCATE/DROP/ALTER proven from grants, NEVER executed")
    if not apply:
        return True
    stmts = sql_file("deploy/04_verify_ledger_rbac.sql")
    conn = connect(APP)
    # The file begins with USE ROLE; the connection is already that role, so run everything.
    results = run_statements(conn, stmts, "verify", quiet=True)
    payload = None
    for rows in results:
        for row in rows:
            if row and isinstance(row[0], str) and row[0].lstrip().startswith("{") and "overall" in row[0]:
                payload = json.loads(row[0])
    if not payload:
        print("    FAIL: verification script returned no result object")
        return False
    for k in ("isolated", "select_ok", "insert_ok", "update_denied", "delete_denied", "ledger_privileges",
              "privileges_are_exactly_insert_select", "app_role_is_not_owner", "answer_key_read_denied", "answer_key_grants_to_app_role"):
        print(f"    {k:38s} {payload.get(k)}")
    for k in ("update_msg", "delete_msg", "answer_key_msg"):
        if payload.get(k):
            print(f"    {k:38s} {payload[k]}")
    print(f"    {'truncate_drop_alter':38s} {payload.get('truncate_drop_alter')}")
    print(f"    role={payload.get('role')}  overall={payload.get('overall')}")
    return payload.get("overall") == "PASS"


def _streamlit_owner(conn) -> str | None:
    rows = _show(conn, f"SHOW STREAMLITS LIKE 'FIU_AML_COPILOT' IN SCHEMA {DB}.{SCHEMA}")
    return rows[0]["owner"] if rows else None


def _snow_cmd(replace: bool) -> list[str]:
    cmd = ["snow", "streamlit", "deploy"] + (["--replace"] if replace else []) + [
        "--connection", OPTS.snow_connection, "--database", DB, "--schema", SCHEMA, "--warehouse", WH,
        "--role", APP, "--secondary-roles", "NONE"]
    return cmd


def step_app(apply: bool):
    """Create / update the hosted app AS the app role (Streamlit-in-Snowflake runs with its owner's privileges and
    GRANT OWNERSHIP ON STREAMLIT is unsupported, error 391811 — so the app must be created by FIU_APP_ROLE)."""
    print(f"  as {APP}: snow streamlit deploy  (first creation needs a TEMPORARY CREATE STREAMLIT grant, revoked in a finally)")
    print("      " + " ".join(_snow_cmd(replace=False)))
    if not apply:
        return
    admin = connect("ACCOUNTADMIN")
    owner = _streamlit_owner(admin)
    if owner is not None and owner.upper() != APP.upper():
        raise SystemExit(f"app: {DB}.{SCHEMA}.FIU_AML_COPILOT already exists and is owned by {owner}, not {APP}. Only its owner can drop it "
                         f"(ownership cannot be transferred) — drop it deliberately, then re-run. Nothing was changed.")
    mode = "create" if owner is None else "replace"
    print(f"  existing app: {'none → create' if owner is None else f'owned by {owner} → --replace (no temporary grant needed)'}")
    granted = False
    try:
        if mode == "create":
            run_statements(admin, [f"GRANT CREATE STREAMLIT ON SCHEMA {DB}.{SCHEMA} TO ROLE {APP}"], "temporary grant")
            granted = True
        r = subprocess.run(_snow_cmd(replace=(mode == "replace")), cwd=BASE, env={**os.environ, **PROFILE.scope_env()},
                           capture_output=True, text=True)
        out = _scrub(r.stdout + r.stderr).strip()
        print("      " + "\n      ".join(out.splitlines()[-14:]))
        if r.returncode:
            raise SystemExit(f"app: snow streamlit deploy failed (exit {r.returncode})")
    finally:
        if granted:
            run_statements(admin, [f"REVOKE CREATE STREAMLIT ON SCHEMA {DB}.{SCHEMA} FROM ROLE {APP}"], "revoke temporary grant")
    own = _streamlit_owner(admin)
    grants = _show(admin, f"SHOW GRANTS TO ROLE {APP}")
    creates = sorted(g["privilege"] for g in grants if g["privilege"].startswith("CREATE"))
    print(f"  after: app owner = {own}; {APP} CREATE privileges = {creates or 'none'}")
    admin.close()
    if (own or "").upper() != APP.upper() or creates:
        raise SystemExit("app: post-conditions failed (the app role must own the app and hold no CREATE privilege)")


def _scripted(name: str, extra: list[str], role: str | None) -> int:
    env = _child_env(role)
    r = subprocess.run([sys.executable, name, *extra], cwd=BASE, env=env, capture_output=True, text=True)
    print("      " + _scrub(r.stdout + r.stderr).strip().replace("\n", "\n      "))
    return r.returncode


def step_health(apply: bool):
    print(f"  as {APP} (read-only): python3 scripts/health_check.py — HEALTHY / UNAVAILABLE / UNVERIFIED per check")
    if apply and _scripted("scripts/health_check.py", ["--role", APP], APP) == 2:
        raise SystemExit("health: at least one check is UNAVAILABLE")


def step_test(apply: bool):
    owner_cmd = ["python3", "-m", "pytest", "tests/test_skills_smoke.py", "tests/test_live_e2e.py", "-m", "live", "-v", "-s", "-p", "no:cacheprovider"]
    app_cmd = owner_cmd + ["-k", "not integrity_view_detects"]
    print(f"  as {ADMIN}: {' '.join(owner_cmd[1:])}")
    print(f"  as {APP}:   {' '.join(app_cmd[1:])}   (the tamper test edits a row and needs the owner role by design)")
    if not apply:
        return
    failed = []
    for who, cmd in ((ADMIN, owner_cmd), (APP, app_cmd)):
        print(f"\n  ── live suites as {who} " + "─" * 40, flush=True)
        r = subprocess.run([sys.executable, *cmd[1:]], cwd=BASE, env=_child_env(who), capture_output=True, text=True)
        print("      " + _scrub(r.stdout + r.stderr).strip().replace("\n", "\n      "), flush=True)
        if r.returncode:
            failed.append(who)
    if failed:
        raise SystemExit(f"test: live suites failed as {', '.join(failed)}")


def step_audit(apply: bool):
    """Optional deletion witness (deploy/05_audit_export.sql + scripts/audit_ledger.py). Never part of a default run: it creates a role and a schema."""
    out = ["--out", OPTS.audit_out] if OPTS.audit_out else []
    plan = [("provision", ["provision", "--apply"], None), ("export (append the not-yet-exported rows)", ["export", "--apply"] + out, AUDIT),
            ("reconcile (read-only)", ["report"], APP)]
    for label, args, role in plan:
        print(f"  {label}: python3 scripts/audit_ledger.py {' '.join(args)}" + (f"   as {role}" if role else "   as ACCOUNTADMIN"))
    if apply:
        for label, args, role in plan:
            print(f"\n  ── {label}", flush=True)
            if _scripted("scripts/audit_ledger.py", args, role) not in (0,):
                raise SystemExit(f"audit: {label} failed")


def step_replay(apply: bool):
    """Optional (never a default): the real model over every seeded alert, as the app role. Read-only; writes evidence/live-replay/ in the repository, not the build copy."""
    print(f"  as {APP}: python3 scripts/eval_live_replay.py  (assessment + draft per alert; Cortex Complete calls; nothing is recorded to the ledger)")
    if not apply:
        return
    out = ROOT / "evidence" / "live-replay"
    extra = os.environ.get("EVAL_REPLAY_ARGS", "").split()          # e.g. EVAL_REPLAY_ARGS="--alerts ALERT-01,ALERT-16 --no-draft"
    r = subprocess.run([sys.executable, "scripts/eval_live_replay.py", "--write", *extra], cwd=BASE, env={**_child_env(APP), "EVAL_GIT_DIR": str(ROOT)}, capture_output=True, text=True)
    print("      " + _scrub(r.stdout + r.stderr).strip().replace("\n", "\n      "))
    # the script wrote into the build copy (BASE); bring the evidence back to the repository so it is not lost with the temp directory
    produced = BASE / "evidence" / "live-replay"
    if produced.exists() and produced != out:
        import shutil
        shutil.copytree(produced, out, dirs_exist_ok=True)
        print(f"      copied {produced} -> {out}")
    if r.returncode:
        raise SystemExit("replay: the evaluation failed")


def step_teardown(apply: bool):
    if PROFILE.is_default:
        raise SystemExit("teardown: refuses the production profile")
    stmts = [f"DROP STREAMLIT IF EXISTS {DB}.{SCHEMA}.FIU_AML_COPILOT", f"DROP DATABASE IF EXISTS {DB}", f"DROP WAREHOUSE IF EXISTS {WH}",
             f"DROP ROLE IF EXISTS {AUDIT}", f"DROP ROLE IF EXISTS {APP}", f"DROP ROLE IF EXISTS {ADMIN}"]
    assert all(not re.search(rf"\b({'|'.join(envprofile.PROD_NAMES)})\b", s) for s in stmts), "teardown must never name a production object"
    print(f"  as ACCOUNTADMIN: {len(stmts)} statements, clean-room objects only:")
    for s in stmts:
        print(f"      {s}")
    print("  DESTRUCTIVE: the clean-room database (and its ledger) is dropped; Time Travel keeps it for the retention period.")
    if not apply:
        return
    if OPTS.confirm_teardown != DB:
        raise SystemExit(f"teardown: pass --confirm-teardown {DB} to confirm (this drops that database).")
    run_statements(connect("ACCOUNTADMIN"), stmts, "teardown")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="execute (default: print the plan only)")
    ap.add_argument("--step", choices=ALL_STEPS, action="append", help="run only these steps (repeatable)")
    ap.add_argument("--profile", choices=["default", "cleanroom"], default="default",
                    help="default = the production names; cleanroom = a suffixed, isolated namespace deployed from a rendered copy")
    ap.add_argument("--suffix", default=envprofile.DEFAULT_SUFFIX, help="clean-room name suffix, appended to each of the five identifiers with an underscore (default CR)")
    ap.add_argument("--build-dir", help="where the clean-room copy is rendered (default: <tmp>/fiu-copilot-build/cleanroom; must be outside the repo)")
    ap.add_argument("--reuse", action="store_true", help="clean room: allow the target namespace to exist already (idempotent re-run)")
    ap.add_argument("--snow-connection", default="fiu-copilot", help="name of the Snowflake CLI connection used by the app step")
    ap.add_argument("--audit-out", help="audit step: also write the exported records to this LOCAL file (copy it to write-once storage outside the account)")
    ap.add_argument("--confirm-teardown", help="teardown only: the database name to drop (must equal the profile's database)")
    ap.add_argument("--ddl-role", default=None,
                    help="role for the ddl/data steps (default: the profile's owner role; 'current' = the connection's own role, "
                         "for accounts where the roles are not provisioned yet)")
    args = ap.parse_args()
    global DDL_ROLE, BASE, PROFILE, ADMIN, APP, AUDIT, DB, WH
    load_env(ROOT)
    PROFILE = envprofile.get_profile(args.profile, args.suffix)
    if not PROFILE.is_default:
        build = Path(args.build_dir) if args.build_dir else envprofile.default_build_dir(PROFILE)
        report = envprofile.render_tree(PROFILE, ROOT, build)
        BASE = build
        ADMIN, APP, AUDIT, DB, WH = PROFILE.admin_role, PROFILE.app_role, PROFILE.audit_role, PROFILE.database, PROFILE.warehouse
        os.environ.update(PROFILE.scope_env())          # beat whatever .env says: a clean-room run must never inherit production's scope
        print(f"RENDERED  {report['files']} files ({report['text_files']} text, {report['files_changed']} changed, "
              f"{report['substitutions']} identifier substitutions, 0 production identifiers left) → {build}")
        print(f"          tree sha256 {report['tree_sha256'][:16]}…   names: " + ", ".join(f"{k}→{v}" for k, v in report["names"].items()))
    DDL_ROLE = args.ddl_role
    OPTS.reuse, OPTS.snow_connection, OPTS.confirm_teardown, OPTS.audit_out = args.reuse, args.snow_connection, args.confirm_teardown, args.audit_out
    if args.apply and missing_config():
        print("ERROR: missing Snowflake configuration: " + ", ".join(missing_config()) + " (copy .env.example to .env).", file=sys.stderr)
        return 1
    steps = args.step or (ORIGINAL_STEPS if PROFILE.is_default else CLEANROOM_DEFAULT_STEPS)
    print("MODE:", "APPLY" if args.apply else "PLAN ONLY (pass --apply to execute)", f"· profile {PROFILE.name} · {DB}.{SCHEMA} · warehouse {WH}")
    ok = True
    for name in ALL_STEPS:
        if name not in steps:
            continue
        print(f"\n== {name} ==")
        res = globals()[f"step_{name}"](args.apply)
        if name == "verify" and res is False:
            ok = False
    print("\n" + ("DONE" if ok else "VERIFICATION FAILED — the app role can mutate the ledger. Do not demo."))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
