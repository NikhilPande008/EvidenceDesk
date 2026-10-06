"""
pytest configuration.

LIVE tests (marker `live`, fixtures `conn` / `app_conn`):
  * SKIPPED only when Snowflake credentials are absent (no SNOWFLAKE_ACCOUNT / SNOWFLAKE_USER /
    credential in the environment or .env) — the skip message says exactly what to set.
  * If credentials ARE present, a connection problem is a test FAILURE with one concise,
    actionable, secret-free sentence (skills/connection.py) — never a skip, never a traceback
    that echoes configuration.
Offline suites never touch the network.
"""

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from skills import connection as C  # noqa: E402

C.load_env(ROOT)
APP_ROLE = os.environ.get("SNOWFLAKE_APP_ROLE", "FIU_APP_ROLE")


SKIP_REASON = ("Snowflake credentials absent — set SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER and one of "
               "SNOWFLAKE_PASSWORD / SNOWFLAKE_PRIVATE_KEY_PATH / SNOWFLAKE_PAT in .env to run live tests")


def pytest_configure(config):
    config.addinivalue_line("markers", "live: needs a live Snowflake account (skipped only when credentials are absent)")


def pytest_collection_modifyitems(config, items):
    """Every test marked `live` is skipped — by this ONE rule, not test by test — when credentials are absent.
    (A live test that needs no connection *fixture*, e.g. the deploy-verification script, used to fail with a
    SystemExit in a credential-free `pytest -q`.) With credentials present nothing is skipped here, and a
    connection problem is a failure (see _connect)."""
    if C.has_credentials():
        return
    skip = pytest.mark.skip(reason=SKIP_REASON)
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _no_test_may_leak_environment_changes():
    """A default `pytest -q` runs the live suites in the SAME process after the offline ones, so a test that fakes (and then deletes)
    SNOWFLAKE_* variables silently breaks every live test after it. Fail the offender — naming the KEYS only, never values."""
    watched = lambda: {k: v for k, v in os.environ.items() if k.startswith(("SNOWFLAKE_", "FIU_"))}  # noqa: E731
    before = watched()
    yield
    after = watched()
    if after != before:
        changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
        for k in set(before) | set(after):          # restore, so one bad test does not cascade
            os.environ.pop(k, None) if k not in before else os.environ.__setitem__(k, before[k])
        pytest.fail(f"this test leaked environment changes ({', '.join(changed)}); use _helpers.scoped_env", pytrace=False)


def _connect(role=None):
    if not C.has_credentials():
        pytest.skip(SKIP_REASON)
    try:
        return C.connect_from_env(role=role)
    except (C.SnowflakeConnectError, C.SnowflakeConfigError) as err:
        pytest.fail(str(err), pytrace=False)


@pytest.fixture(scope="session")
def conn():
    """Live connection as the configured user/role (SNOWFLAKE_ROLE or the user's default)."""
    c = _connect()
    yield c
    c.close()


@pytest.fixture(scope="session")
def app_conn():
    """Live connection AS the application role (least privilege). Requires deploy/01_roles.sql + 03_grants.sql."""
    try:
        c = _connect(role=APP_ROLE)
    except BaseException as err:  # add the provisioning hint to a role failure
        if "not granted" in str(err).lower() or "role" in str(err).lower():
            pytest.fail(f"{err}  →  provision it with: python3 scripts/deploy_snowflake.py --apply", pytrace=False)
        raise
    yield c
    c.close()
