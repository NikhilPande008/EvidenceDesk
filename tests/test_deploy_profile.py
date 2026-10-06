"""
Clean-room deployment profile + deploy driver (offline: no Snowflake, no network).

What is proven here, and why it matters for the clean-room claim:
  * the clean room is deployed from a RENDERED COPY of the shipped files, and the ONLY difference between the copy and the source is
    five identifiers (rendering is reversible, byte for byte) — so "the clean room deployed the real artifacts" is a checkable statement;
  * no production identifier survives in the copy (a leftover would address production from a clean-room run);
  * the driver refuses, before it touches anything, to: wipe a directory it did not create, run a clean room in a non-empty namespace,
    connect with production's database / warehouse in scope, or tear down without an explicit confirmation or against production;
  * the app step revokes its temporary CREATE STREAMLIT grant even when the deploy fails, and never touches an app owned by another role.

Usage:  python3 tests/test_deploy_profile.py     (or pytest)
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from _helpers import ROOT, Runner, scoped_env

sys.path.insert(0, str(ROOT / "scripts"))
import deploy_snowflake as d  # noqa: E402
import envprofile  # noqa: E402

PROD = envprofile.PROD_NAMES
CR = envprofile.cleanroom("CR")
_TREE: dict = {}


def rendered() -> tuple[Path, dict]:
    """Render the real repository once and share it."""
    if not _TREE:
        tmp = Path(tempfile.mkdtemp(prefix="fiu-render-test-")) / "build"
        _TREE["dir"], _TREE["report"] = tmp, envprofile.render_tree(CR, ROOT, tmp)
    return _TREE["dir"], _TREE["report"]


@contextmanager
def patched(mod, **kw):
    old = {k: getattr(mod, k) for k in kw}
    try:
        for k, v in kw.items():
            setattr(mod, k, v)
        yield
    finally:
        for k, v in old.items():
            setattr(mod, k, v)


class _Cur:
    def __init__(self, c):
        self.c, self.description, self._rows = c, None, []

    def execute(self, sql, *a):
        self.c.log.append(" ".join(sql.split()))
        self.description, self._rows = None, []
        if sql.lstrip().upper().startswith("SELECT CURRENT_DATABASE()"):
            self.description, self._rows = [("A",), ("B",)], [self.c.scope]
            return self
        for needle, queue in self.c.show.items():
            if needle in sql:
                rows = queue.pop(0) if len(queue) > 1 else queue[0]
                cols = list(rows[0]) if rows else ["name"]
                self.description, self._rows = [(k,) for k in cols], [tuple(r[k] for k in cols) for r in rows]
                break
        return self

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass


class FakeSF:
    """A connection that records statements and answers SHOW … from canned queues (needle → [rows, rows, …], last one repeats)."""

    def __init__(self, show=None, scope=(None, None)):
        self.log, self.show, self.scope, self.closed = [], {k: list(v) for k, v in (show or {}).items()}, scope, False

    def cursor(self, *a, **k):
        return _Cur(self)

    def close(self):
        self.closed = True


def _cleanroom_driver():
    return patched(d, PROFILE=CR, ADMIN=CR.admin_role, APP=CR.app_role, AUDIT=CR.audit_role, DB=CR.database, WH=CR.warehouse)


# ── the profile ──────────────────────────────────────────────────────────────

def test_default_profile_is_the_identity_and_names_are_production_names():
    p = envprofile.DEFAULT
    sample = "USE DATABASE FIU_COPILOT; GRANT USAGE ON WAREHOUSE FIU_WH TO ROLE FIU_APP_ROLE; -- FIU_ADMIN_ROLE FIU_AUDIT_ROLE"
    assert p.render_text(sample) == sample and p.is_default and p.leftovers(sample) == []
    assert (p.database, p.warehouse, p.admin_role, p.app_role, p.audit_role) == ("FIU_COPILOT", "FIU_WH", "FIU_ADMIN_ROLE", "FIU_APP_ROLE", "FIU_AUDIT_ROLE")
    for bad in (lambda: envprofile.Profile("default", "CR"), lambda: envprofile.Profile("cleanroom", ""), lambda: envprofile.Profile("cleanroom", "cr"),
                lambda: envprofile.Profile("cleanroom", "1X"), lambda: envprofile.get_profile("nope")):
        try:
            bad()
            raise AssertionError("an invalid profile must be refused")
        except envprofile.ProfileError:
            pass
    try:
        envprofile.render_tree(p, ROOT, Path(tempfile.mkdtemp()) / "x")
        raise AssertionError("the default profile must not be rendered")
    except envprofile.ProfileError:
        pass
    print("  [PASS] the default profile renders nothing and keeps the production names; invalid profiles (no suffix, lower-case, default+suffix) are refused")


def test_every_account_level_name_changes_and_none_collides_with_production():
    names = CR.names()
    assert set(names) == set(PROD) and all(v == f"{k}_CR" for k, v in names.items()), names
    assert not (set(names.values()) & set(PROD)), "a clean-room name equals a production name"
    assert CR.scope_env() == {"SNOWFLAKE_DATABASE": "FIU_COPILOT_CR", "SNOWFLAKE_SCHEMA": "AML", "SNOWFLAKE_WAREHOUSE": "FIU_WH_CR", "SNOWFLAKE_APP_ROLE": "FIU_APP_ROLE_CR"}
    assert CR.streamlit_fqn == "FIU_COPILOT_CR.AML.FIU_AML_COPILOT"
    print(f"  [PASS] five names → {', '.join(names.values())}; none equals a production name")


def test_rendering_respects_token_boundaries_and_is_idempotent():
    s = ("FIU_COPILOT.AML.ALERTS fiu_copilot.aml.alerts_current \"FIU_WH\" 'FIU_APP_ROLE' FIU_ADMIN_ROLE, FIU_AUDIT_ROLE;\n"
         "SNOWFLAKE_APP_ROLE FIU_AML_COPILOT XFIU_WH FIU_WH_X FIU_COPILOTX my_fiu_wh FIU_COPILOT_CR_X")
    out = CR.render_text(s)
    assert out.splitlines()[0] == ("FIU_COPILOT_CR.AML.ALERTS fiu_copilot_cr.aml.alerts_current \"FIU_WH_CR\" 'FIU_APP_ROLE_CR' FIU_ADMIN_ROLE_CR, FIU_AUDIT_ROLE_CR;"), out
    assert out.splitlines()[1] == s.splitlines()[1], "SNOWFLAKE_APP_ROLE / FIU_AML_COPILOT / XFIU_WH / FIU_WH_X / FIU_COPILOTX / my_fiu_wh must be left alone"
    assert CR.render_text(out) == out, "rendering an already-rendered text must not suffix twice"
    assert CR.unrender_text(out.splitlines()[0]) == s.splitlines()[0]
    print("  [PASS] whole-token only (SNOWFLAKE_APP_ROLE, FIU_AML_COPILOT, XFIU_WH untouched), case-preserving, idempotent, reversible")


# ── the rendered copy of the real repository ─────────────────────────────────

def test_rendered_copy_differs_from_the_source_only_in_the_five_identifiers():
    build, rep = rendered()
    assert rep["files_changed"] > 20 and rep["substitutions"] > 100 and all(n > 0 for n in rep["per_identifier"].values()), rep
    checked = 0
    for path in sorted(build.rglob("*")):
        if not path.is_file() or path.name == envprofile.MARKER:
            continue
        rel = path.relative_to(build)
        src = ROOT / rel
        assert src.exists(), f"{rel} exists in the copy but not in the source"
        if str(rel) in envprofile.VERBATIM or path.suffix.lower() not in envprofile.TEXT_SUFFIXES:
            assert path.read_bytes() == src.read_bytes(), f"{rel} must be a byte-for-byte copy"
        else:
            text = path.read_text(encoding="utf-8")
            assert CR.unrender_text(text) == src.read_text(encoding="utf-8"), f"{rel}: the copy differs from the source by more than the identifiers"
            assert CR.leftovers(text) == [], f"{rel}: a production identifier survived rendering"
        checked += 1
    assert checked == rep["files"]
    print(f"  [PASS] {checked} files rendered; un-rendering every text file gives the source byte-for-byte ({rep['substitutions']} identifier substitutions); 0 production identifiers left")


def test_rendered_copy_excludes_secrets_caches_docs_and_backups():
    build, _ = rendered()
    rels = {str(p.relative_to(build)) for p in build.rglob("*") if p.is_file()}
    assert ".env" not in rels and not any(r.endswith(".md") for r in rels) and not any("__pycache__" in r or ".pytest_cache" in r or ".bak" in r for r in rels), sorted(rels)[:5]
    assert not any(r.startswith(("design/", ".claude/", ".github/", "output/")) for r in rels)
    for must in ("streamlit_app.py", "snowflake.yml", "deploy/00_bootstrap.sql", "deploy/06_health.sql", "domain/corpus/export/semantic_model.yaml",
                 "domain/corpus/manifest.yaml", "scripts/deploy_snowflake.py", "scripts/health_check.py", "skills/ledger.py", "tests/test_live_e2e.py", ".env.example"):
        assert must in rels, f"{must} missing from the rendered copy"
    print(f"  [PASS] {len(rels)} files copied; no .env, caches, backups, documentation or design files; every deployable file present")


def test_rendered_artifacts_address_only_the_clean_room():
    build, _ = rendered()
    rd = lambda p: (build / p).read_text()  # noqa: E731
    assert "FIU_COPILOT_CR.AML.DECISION_LEDGER" in rd("skills/ledger.py") and "FIU_COPILOT_CR.AML" in rd("skills/core.py")
    assert "FIU_COPILOT_CR.AUDIT.LEDGER_EXPORT" in rd("skills/audit.py")
    assert rd("snowflake.yml").count("FIU_WH_CR") == 1 and "query_warehouse: FIU_WH_CR" in rd("snowflake.yml")
    assert rd("domain/corpus/export/semantic_model.yaml").count("database: FIU_COPILOT_CR") == 4
    conn = rd("skills/connection.py")
    assert '"SNOWFLAKE_WAREHOUSE": "FIU_WH_CR", "SNOWFLAKE_DATABASE": "FIU_COPILOT_CR"' in conn, "the connection defaults must point at the clean room"
    assert "FIU_APP_ROLE_CR" in rd("tests/conftest.py"), "the app-role fixture's default must be the clean-room app role"
    assert 'ADMIN, APP, AUDIT = "FIU_ADMIN_ROLE_CR", "FIU_APP_ROLE_CR", "FIU_AUDIT_ROLE_CR"' in rd("scripts/deploy_snowflake.py")
    grants = rd("deploy/03_grants.sql")
    assert "TO ROLE FIU_APP_ROLE_CR" in grants and not re.search(r"FIU_APP_ROLE(?!_CR)", grants)
    streamlit = rd("streamlit_app.py")
    assert "FIU_COPILOT_CR.AML.DECISION_LEDGER" in streamlit and not re.search(r"FIU_COPILOT(?!_CR)\.AML", streamlit)
    print("  [PASS] the rendered app, ledger module, audit module, connection defaults, semantic model, manifest, grants and driver all name only the clean room")


def test_rendered_python_compiles_and_sql_keeps_its_statement_structure():
    build, _ = rendered()
    n = 0
    for p in sorted(build.rglob("*.py")):
        compile(p.read_text(encoding="utf-8"), str(p), "exec")       # syntax check without writing a .pyc
        n += 1
    for name in ("deploy/00_bootstrap.sql", "deploy/01_roles.sql", "deploy/03_grants.sql", "deploy/04_verify_ledger_rbac.sql", "deploy/05_audit_export.sql",
                 "deploy/06_health.sql", "domain/corpus/export/ddl/regulatory_corpus.sql", "domain/corpus/export/ddl/views.sql"):
        assert len(d.split_sql((build / name).read_text())) == len(d.split_sql((ROOT / name).read_text())), name
    print(f"  [PASS] {n} rendered Python files compile; every deployment SQL file splits into the same number of statements as its source")


# ── render safety ────────────────────────────────────────────────────────────

def test_the_renderer_only_wipes_directories_it_made_and_stays_out_of_the_repo():
    tmp = Path(tempfile.mkdtemp(prefix="fiu-render-safety-"))
    foreign = tmp / "somebody-elses-work"
    foreign.mkdir()
    (foreign / "precious.txt").write_text("keep me")
    for dst, why in ((foreign, "a non-empty directory without the marker"), (ROOT, "the repository itself"), (ROOT / "scripts" / "build", "inside the repository"), (ROOT.parent, "a parent of the repository")):
        try:
            envprofile.render_tree(CR, ROOT, dst)
            raise AssertionError(f"must refuse {why}")
        except envprofile.ProfileError:
            pass
    assert (foreign / "precious.txt").read_text() == "keep me" and (ROOT / "streamlit_app.py").exists()
    ok = tmp / "ours"
    first = envprofile.render_tree(CR, ROOT, ok)
    (ok / "stale.txt").write_text("stale")
    second = envprofile.render_tree(CR, ROOT, ok)                       # a directory it made may be re-rendered (wiped)
    assert not (ok / "stale.txt").exists() and first["tree_sha256"] == second["tree_sha256"], "rendering must be deterministic"
    print("  [PASS] refuses a foreign non-empty directory, the repository and its parent; re-renders its own directory; the same input gives the same tree hash")


# ── the driver ───────────────────────────────────────────────────────────────

def _plan(*args, build=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("SNOWFLAKE_", "FIU_"))}
    env["FIU_SKIP_DOTENV"] = "1"
    return subprocess.run([sys.executable, str(ROOT / "scripts/deploy_snowflake.py"), *args] + (["--build-dir", str(build)] if build else []),
                          capture_output=True, text=True, env=env, cwd=ROOT, timeout=120)


def test_production_plan_is_unchanged_and_the_cleanroom_plan_names_only_the_clean_room():
    prod = _plan()
    assert prod.returncode == 0 and "PLAN ONLY" in prod.stdout, prod.stdout[-300:]
    headings = re.findall(r"^== (\w+) ==$", prod.stdout, re.M)
    assert headings == ["bootstrap", "roles", "ownership", "ddl", "data", "grants", "verify"], f"the production default must stay the original seven steps: {headings}"
    assert "FIU_COPILOT_CR" not in prod.stdout
    tmp = Path(tempfile.mkdtemp(prefix="fiu-plan-")) / "b"
    cr = _plan("--profile", "cleanroom", build=tmp)
    assert cr.returncode == 0, cr.stdout[-400:] + cr.stderr[-400:]
    headings = re.findall(r"^== (\w+) ==$", cr.stdout, re.M)
    assert headings == ["preflight", "bootstrap", "roles", "ownership", "ddl", "data", "grants", "verify", "app", "health", "test"], headings
    assert "RENDERED" in cr.stdout and "0 production identifiers left" in cr.stdout
    plan_body = cr.stdout.split("MODE:")[1]
    assert envprofile._PROD_RE.search(plan_body) is None, "the clean-room plan mentions a production identifier"
    assert "FIU_COPILOT_CR" in plan_body and "--role FIU_APP_ROLE_CR --secondary-roles NONE" in plan_body
    print("  [PASS] production plan = the original 7 steps, no clean-room name; clean-room plan = preflight → … → app → health → test, every identifier suffixed")


def test_preflight_requires_an_empty_namespace_and_never_reuses_a_production_name():
    empty = {"SHOW DATABASES": [[]], "SHOW WAREHOUSES": [[]], "SHOW ROLES": [[]]}
    with _cleanroom_driver():
        conn = FakeSF(empty)
        with patched(d, connect=lambda role: conn):
            d.step_preflight(True)
        assert len(conn.log) == 5 and all(s.startswith("SHOW ") for s in conn.log) and "FIU_COPILOT_CR" in conn.log[0]
        for existing, label in (({"SHOW DATABASES": [[{"name": "FIU_COPILOT_CR"}]], "SHOW WAREHOUSES": [[]], "SHOW ROLES": [[]]}, "database"),
                                ({"SHOW DATABASES": [[]], "SHOW WAREHOUSES": [[]], "SHOW ROLES": [[{"name": "FIU_APP_ROLE_CR"}]]}, "role")):
            with patched(d, connect=lambda role, e=existing: FakeSF(e)):
                try:
                    d.step_preflight(True)
                    raise AssertionError(f"an existing {label} must stop a clean-room run")
                except SystemExit as stop:
                    assert "NOT empty" in str(stop)
                d.OPTS.reuse = True
                try:
                    d.step_preflight(True)
                finally:
                    d.OPTS.reuse = False
        # LIKE is a wildcard match: only an exact name counts
        with patched(d, connect=lambda role: FakeSF({"SHOW DATABASES": [[{"name": "FIU_COPILOT_CRX"}]], "SHOW WAREHOUSES": [[]], "SHOW ROLES": [[]]})):
            d.step_preflight(True)
    with patched(d, PROFILE=CR, DB="FIU_COPILOT", connect=lambda role: FakeSF(empty)):
        try:
            d.step_preflight(True)
            raise AssertionError("a clean-room profile that names the production database must be refused")
        except SystemExit as stop:
            assert "must not reuse a production name" in str(stop)
    print("  [PASS] preflight: empty namespace passes (read-only SHOW only); an existing database or role stops it unless --reuse; LIKE-wildcard near-matches are ignored")


def test_a_connection_that_has_production_in_scope_is_refused():
    with _cleanroom_driver():
        for scope, ok in (((None, None), True), (("FIU_COPILOT_CR", "FIU_WH_CR"), True), (("FIU_COPILOT", "FIU_WH"), False), (("FIU_COPILOT_CR", "FIU_WH"), False), (("FIU_COPILOT", None), False)):
            conn = FakeSF(scope=scope)
            try:
                d._scope_ok(conn)
                assert ok, f"scope {scope} must be refused"
            except SystemExit as stop:
                assert not ok and conn.closed and "Refusing to continue" in str(stop), (scope, str(stop))
    with scoped_env(SNOWFLAKE_DATABASE="FIU_COPILOT", SNOWFLAKE_WAREHOUSE="FIU_WH", SNOWFLAKE_ROLE=None):
        with _cleanroom_driver():
            env = d._child_env("FIU_ADMIN_ROLE_CR")
        assert env["SNOWFLAKE_DATABASE"] == "FIU_COPILOT_CR" and env["SNOWFLAKE_WAREHOUSE"] == "FIU_WH_CR" and env["SNOWFLAKE_ROLE"] == "FIU_ADMIN_ROLE_CR", \
            "a stale .env must not beat the profile in a child process"
    print("  [PASS] a clean-room connection with production's database / warehouse in scope is closed and refused; a stale .env cannot leak production's scope into a child process")


def _fake_run(returncode=0):
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode, stdout="deployed app at https://app.snowflake.com/myorg/myacct/#/streamlit-apps/X", stderr="")
    return run, calls


def test_app_step_revokes_its_temporary_grant_even_when_the_deploy_fails_and_never_touches_a_foreign_app():
    app = CR.app_role
    after = [{"owner": app, "name": "FIU_AML_COPILOT"}]
    grants_ok = [{"privilege": "USAGE", "granted_on": "DATABASE", "name": "FIU_COPILOT_CR"}]
    with _cleanroom_driver():
        # create path, deploy succeeds: grant → snow → revoke, then the post-conditions hold
        run, calls = _fake_run(0)
        conn = FakeSF({"SHOW STREAMLITS": [[], after], "SHOW GRANTS TO ROLE": [grants_ok]})
        with patched(d, connect=lambda role: conn), patched(d.subprocess, run=run):
            d.step_app(True)
        sql = [s for s in conn.log if s.startswith(("GRANT", "REVOKE"))]
        assert sql == [f"GRANT CREATE STREAMLIT ON SCHEMA {CR.database}.AML TO ROLE {app}", f"REVOKE CREATE STREAMLIT ON SCHEMA {CR.database}.AML FROM ROLE {app}"], sql
        assert len(calls) == 1 and "--replace" not in calls[0] and calls[0][-4:] == ["--role", app, "--secondary-roles", "NONE"], calls
        # create path, deploy FAILS: the revoke must still run
        run, calls = _fake_run(1)
        conn = FakeSF({"SHOW STREAMLITS": [[]]})
        with patched(d, connect=lambda role: conn), patched(d.subprocess, run=run):
            try:
                d.step_app(True)
                raise AssertionError("a failed deploy must fail the step")
            except SystemExit as stop:
                assert "failed" in str(stop)
        assert any(s.startswith("REVOKE CREATE STREAMLIT") for s in conn.log), "the temporary grant must be revoked after a failed deploy"
        # existing app owned by the app role: --replace, no grant at all
        run, calls = _fake_run(0)
        conn = FakeSF({"SHOW STREAMLITS": [[{"owner": app}]], "SHOW GRANTS TO ROLE": [grants_ok]})
        with patched(d, connect=lambda role: conn), patched(d.subprocess, run=run):
            d.step_app(True)
        assert not [s for s in conn.log if s.startswith(("GRANT", "REVOKE"))] and "--replace" in calls[0]
        # existing app owned by another role: refuse, change nothing, run nothing
        run, calls = _fake_run(0)
        conn = FakeSF({"SHOW STREAMLITS": [[{"owner": "ACCOUNTADMIN"}]]})
        with patched(d, connect=lambda role: conn), patched(d.subprocess, run=run):
            try:
                d.step_app(True)
                raise AssertionError("an app owned by another role must be refused")
            except SystemExit as stop:
                assert "owned by ACCOUNTADMIN" in str(stop)
        assert not calls and not [s for s in conn.log if s.startswith(("GRANT", "REVOKE", "DROP"))]
        # a leftover CREATE privilege after the deploy fails the post-condition
        run, calls = _fake_run(0)
        conn = FakeSF({"SHOW STREAMLITS": [[], after], "SHOW GRANTS TO ROLE": [grants_ok + [{"privilege": "CREATE TABLE", "granted_on": "SCHEMA", "name": "x"}]]})
        with patched(d, connect=lambda role: conn), patched(d.subprocess, run=run):
            try:
                d.step_app(True)
                raise AssertionError("a leftover CREATE privilege must fail the step")
            except SystemExit as stop:
                assert "post-conditions" in str(stop)
    print("  [PASS] app step: grant → deploy → revoke; the revoke runs after a failed deploy; --replace needs no grant; a foreign-owned app is refused untouched; a leftover CREATE privilege fails it")


def test_snow_output_is_scrubbed_of_the_account_path_in_snowsight_urls():
    out = d._scrub("Access url: https://app.snowflake.com/myorg/myacct/#/streamlit-apps/DB.AML.APP")
    assert "myorg" not in out and "myacct" not in out and "app.snowflake.com/<org>/<account>/" in out, out
    print("  [PASS] a Snowsight URL printed by the CLI is reduced to app.snowflake.com/<org>/<account>/…")


def test_teardown_is_explicit_clean_room_only_and_never_names_production():
    try:
        d.step_teardown(False)                                        # production profile (module default)
        raise AssertionError("teardown must refuse the production profile")
    except SystemExit as stop:
        assert "refuses the production profile" in str(stop)
    with _cleanroom_driver():
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            d.step_teardown(False)                                     # plan only
        plan = buf.getvalue()
        assert envprofile._PROD_RE.search(plan) is None and "DROP DATABASE IF EXISTS FIU_COPILOT_CR" in plan, plan
        assert "teardown" not in d.CLEANROOM_DEFAULT_STEPS and "teardown" not in d.ORIGINAL_STEPS, "teardown must never be part of a default run"
        conn = FakeSF()
        with patched(d, connect=lambda role: conn):
            for confirm in (None, "FIU_COPILOT", "WRONG"):
                d.OPTS.confirm_teardown = confirm
                try:
                    with redirect_stdout(io.StringIO()):
                        d.step_teardown(True)
                    raise AssertionError("teardown without the exact confirmation must refuse")
                except SystemExit as stop:
                    assert "--confirm-teardown FIU_COPILOT_CR" in str(stop)
            d.OPTS.confirm_teardown = None
        assert conn.log == [], "nothing may run before the confirmation"
    print("  [PASS] teardown: production refused; plan names only clean-room objects; apply refuses without --confirm-teardown <exact database>; never in a default run")


def test_every_skills_module_is_in_the_streamlit_bundle():
    """snowflake.yml lists the bundle's source files explicitly. A module that skills/core.py imports but the list omits imports fine
    locally and crashes the hosted app, which nothing else here would notice (skills/scope_guard.py was nearly that case)."""
    import yaml
    listed = set(yaml.safe_load((ROOT / "snowflake.yml").read_text())["streamlit"]["additional_source_files"])
    modules = {f"skills/{p.name}" for p in (ROOT / "skills").glob("*.py")}
    assert modules <= listed, f"skills modules missing from snowflake.yml additional_source_files: {sorted(modules - listed)}"
    assert all((ROOT / f).exists() for f in listed), f"snowflake.yml lists a file that does not exist: {sorted(f for f in listed if not (ROOT / f).exists())}"
    print(f"  [PASS] all {len(modules)} skills modules are in the Streamlit bundle and every listed file exists")


def test_the_repository_renders_for_any_suffix_in_use_not_only_the_default_one():
    """Found by the CR2 deployment (2026-10-05): a sentence in skills/readiness.py that named the CR2 objects made the CR2 render refuse
    ("rendering is not reversible"), while the default CR suffix, the only one tested, still passed. No file the renderer processes may
    carry a suffixed clean-room name; documentation outside the copy (*.md, evidence/, design/) may."""
    for suffix in ("CR", "CR2", "JUDGE", "A1"):
        tmp = Path(tempfile.mkdtemp(prefix="fiu-render-suffix-")) / "build"
        report = envprofile.render_tree(envprofile.cleanroom(suffix), ROOT, tmp)
        assert report["files"] > 100 and report["files_changed"] > 20, (suffix, report["files"], report["files_changed"])
    print("  [PASS] the real repository renders (and un-renders byte-for-byte) for suffixes CR, CR2, JUDGE and A1")


TESTS = [
    test_default_profile_is_the_identity_and_names_are_production_names, test_every_account_level_name_changes_and_none_collides_with_production,
    test_rendering_respects_token_boundaries_and_is_idempotent, test_rendered_copy_differs_from_the_source_only_in_the_five_identifiers,
    test_rendered_copy_excludes_secrets_caches_docs_and_backups, test_rendered_artifacts_address_only_the_clean_room,
    test_rendered_python_compiles_and_sql_keeps_its_statement_structure, test_the_renderer_only_wipes_directories_it_made_and_stays_out_of_the_repo,
    test_production_plan_is_unchanged_and_the_cleanroom_plan_names_only_the_clean_room,
    test_preflight_requires_an_empty_namespace_and_never_reuses_a_production_name, test_a_connection_that_has_production_in_scope_is_refused,
    test_app_step_revokes_its_temporary_grant_even_when_the_deploy_fails_and_never_touches_a_foreign_app,
    test_snow_output_is_scrubbed_of_the_account_path_in_snowsight_urls, test_teardown_is_explicit_clean_room_only_and_never_names_production,
    test_every_skills_module_is_in_the_streamlit_bundle, test_the_repository_renders_for_any_suffix_in_use_not_only_the_default_one,
]

if __name__ == "__main__":
    raise SystemExit(Runner("Clean-room deployment profile and deploy driver (offline)").run(TESTS))
