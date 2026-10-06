"""
Test-suite reliability: the DEFAULT `pytest -q` must not fail merely because live Snowflake credentials are absent, every
network-dependent test must be marked `live`, live tests are skipped ONLY when credentials are absent, and a connection
problem WITH credentials stays a failure.

(Regression, 2026-10-01: in a credential-free `pytest -q`, `test_deploy_verification_script_passes` — marked live, but taking no
connection fixture — died with a SystemExit instead of skipping. CI never saw it because CI deselected live tests.)

Offline. Usage:  python3 tests/test_reliability.py     (or pytest)
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys

from _helpers import ROOT, Runner

TESTS_DIR = ROOT / "tests"
LIVE_MODULES = {"test_live_e2e.py", "test_skills_smoke.py"}
FIXTURES_THAT_CONNECT = {"conn", "app_conn"}


def _module_is_marked_live(src: str) -> bool:
    return bool(re.search(r"^pytestmark\s*=\s*pytest\.mark\.live\b", src, re.M))


def test_every_network_dependent_test_is_marked_live():
    unmarked, live_found = [], set()
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        src = path.read_text()
        marked = _module_is_marked_live(src)
        if marked:
            live_found.add(path.name)
        tree = ast.parse(src)
        for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")):
            args = {a.arg for a in fn.args.args}
            uses_connection = bool(args & FIXTURES_THAT_CONNECT)
            uses_real_scripts = any(isinstance(c, ast.Call) and (getattr(c.func, "attr", None) == "step_verify" or getattr(c.func, "id", None) == "step_verify")
                                    for c in ast.walk(fn))        # the deploy verification script opens its own live connection
            marked_here = marked or any("live" in ast.dump(d) for d in fn.decorator_list)
            if (uses_connection or uses_real_scripts) and not marked_here:
                unmarked.append(f"{path.name}::{fn.name}")
    assert not unmarked, f"network-dependent tests without the `live` marker: {unmarked}"
    assert live_found == LIVE_MODULES, (
        f"live test modules changed: {sorted(live_found)} — if this is deliberate, update LIVE_MODULES here and the docs "
        "(README suite table, DEPLOY.md Step 6) so the credential-free run still skips them")
    print(f"  [PASS] every test that takes a connection fixture or runs the deploy verification is marked `live` ({', '.join(sorted(live_found))})")


def test_a_credential_free_run_of_the_live_suites_skips_everything_and_fails_nothing():
    env = {k: v for k, v in os.environ.items() if not k.startswith("SNOWFLAKE_")}
    env["FIU_SKIP_DOTENV"] = "1"                      # a developer's .env must not leak into this proof
    r = subprocess.run([sys.executable, "-m", "pytest", *(f"tests/{m}" for m in sorted(LIVE_MODULES)), "-q", "-p", "no:cacheprovider"],
                       capture_output=True, text=True, env=env, cwd=ROOT, timeout=120)
    out = r.stdout + r.stderr
    assert r.returncode == 0, f"credential-free live suites must exit 0:\n{out[-1500:]}"
    m = re.search(r"(\d+) skipped", out)
    assert m and int(m.group(1)) >= 16, out[-500:]
    assert " passed" not in out and " failed" not in out and "error" not in out.lower().replace("0 errors", ""), out[-500:]
    print(f"  [PASS] `pytest` on the live suites with no credentials: {m.group(1)} skipped, 0 failed, 0 errors, exit 0 "
          "(run hermetically: FIU_SKIP_DOTENV=1)")


def test_with_credentials_a_connection_problem_is_a_failure_never_a_skip():
    import conftest
    from _pytest.outcomes import Failed, Skipped
    from skills import connection as C

    real_has, real_connect = C.has_credentials, C.connect_from_env
    try:
        C.has_credentials = lambda: False
        try:
            conftest._connect()
            raise AssertionError("no credentials: expected a skip")
        except Skipped as s:
            assert "credentials absent" in str(s)
        C.has_credentials = lambda: True

        def bad(role=None):
            raise C.SnowflakeConnectError("Snowflake connection failed (account ABCD…): Incorrect user name or password. Check SNOWFLAKE_USER / SNOWFLAKE_PASSWORD in .env.")
        C.connect_from_env = bad
        try:
            conftest._connect()
            raise AssertionError("credentials present but the connection failed: expected a FAILURE")
        except Failed as f:
            assert "Incorrect user name or password" in str(f)
        def missing(role=None):
            raise C.SnowflakeConfigError("Missing Snowflake configuration: SNOWFLAKE_USER.")
        C.connect_from_env = missing
        try:
            conftest._connect()
            raise AssertionError("expected a failure")
        except Failed:
            pass
    finally:
        C.has_credentials, C.connect_from_env = real_has, real_connect
    print("  [PASS] credentials absent → skip; credentials present + connection/config problem → FAIL (one concise sentence)")


def test_the_collection_hook_marks_live_items_only_when_credentials_are_absent():
    import conftest
    from skills import connection as C

    class Item:
        def __init__(self, live): self.keywords, self.added = ({"live": 1} if live else {}), []
        def add_marker(self, m): self.added.append(m)

    real = C.has_credentials
    try:
        for has, expect in ((False, True), (True, False)):
            C.has_credentials = lambda has=has: has
            live, offline = Item(True), Item(False)
            conftest.pytest_collection_modifyitems(None, [live, offline])
            assert bool(live.added) is expect and not offline.added, (has, live.added)
    finally:
        C.has_credentials = real
    print("  [PASS] central hook: live items are skipped when credentials are absent, never when present; offline items are never touched")


def test_hermetic_switch_ignores_dotenv():
    from skills import connection as C
    import tempfile
    from pathlib import Path
    from _helpers import scoped_env
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / ".env").write_text("FIU_TEST_CANARY_VAR=from-dotenv\n")
        with scoped_env(FIU_SKIP_DOTENV="1", FIU_TEST_CANARY_VAR=None):
            C.load_env(Path(d))
            assert "FIU_TEST_CANARY_VAR" not in os.environ, ".env must be ignored when FIU_SKIP_DOTENV=1"
        with scoped_env(FIU_SKIP_DOTENV=None, FIU_TEST_CANARY_VAR=None):
            C.load_env(Path(d))
            assert os.environ.get("FIU_TEST_CANARY_VAR") == "from-dotenv", "without the switch .env loads as before"
    print("  [PASS] FIU_SKIP_DOTENV=1 skips .env entirely; unset it loads as before (and the caller's environment is restored exactly)")


def test_a_test_that_leaks_environment_changes_is_errored_and_the_environment_restored():
    env = {k: v for k, v in os.environ.items() if not k.startswith("SNOWFLAKE_")}
    env["FIU_SKIP_DOTENV"] = "1"
    r = subprocess.run([sys.executable, "-m", "pytest", "tests/_probe_env_leak.py", "-q", "-p", "no:cacheprovider"],
                       capture_output=True, text=True, env=env, cwd=ROOT, timeout=120)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "1 error" in out and "2 passed" in out, out[-600:]      # the guard fires in teardown → an ERROR beside the leaking test
    assert "SNOWFLAKE_LEAK_PROBE" in out, "the failure must name the leaked KEY"
    assert "probe-secret-value-731" not in out, "…and must never print the VALUE"
    print("  [PASS] a test that leaks SNOWFLAKE_*/FIU_* is errored by the conftest guard (key named, value never printed) and the environment is restored for the next test")


def test_ci_runs_the_default_pytest_command():
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    commands = "\n".join(line for line in ci.splitlines() if not line.lstrip().startswith("#"))
    assert re.search(r"python -m pytest tests -q -p no:cacheprovider\s*$", commands, re.M), "CI must run the DEFAULT command so a live-skip regression is caught"
    assert "-m \"not live\"" not in commands, "CI no longer needs to deselect live tests: they skip themselves when credentials are absent"
    print("  [PASS] CI runs the default `pytest -q` (live tests skip themselves), so this class of failure cannot hide again")


TESTS = [
    test_every_network_dependent_test_is_marked_live, test_a_credential_free_run_of_the_live_suites_skips_everything_and_fails_nothing,
    test_with_credentials_a_connection_problem_is_a_failure_never_a_skip, test_the_collection_hook_marks_live_items_only_when_credentials_are_absent,
    test_hermetic_switch_ignores_dotenv, test_a_test_that_leaks_environment_changes_is_errored_and_the_environment_restored,
    test_ci_runs_the_default_pytest_command,
]

if __name__ == "__main__":
    raise SystemExit(Runner("Test-suite reliability (offline)").run(TESTS))
