"""
Connection / configuration handling (finding #6 + #8): requirements are explicit, failures are
concise and actionable, and NO secret ever appears in an error message.

Offline (no network): the connector is never called.
Usage:  python3 tests/test_connection.py     (or pytest)
"""

from __future__ import annotations

import os
from contextlib import contextmanager

from _helpers import Runner

SECRETS = {"SNOWFLAKE_PASSWORD": "Sup3r$ecretPW!x9", "SNOWFLAKE_PAT": "pat-abcdef0123456789-TOKEN",
           "SNOWFLAKE_TOKEN": "tok-zzzzzzzzzz-1234", "SNOWFLAKE_PRIVATE_KEY_PASSPHRASE": "correct-horse-battery"}
KEYS = ["SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD", "SNOWFLAKE_PAT", "SNOWFLAKE_TOKEN",
        "SNOWFLAKE_PRIVATE_KEY_PATH", "SNOWFLAKE_PRIVATE_KEY_PASSPHRASE", "SNOWFLAKE_ROLE", "SNOWFLAKE_AUTHENTICATOR",
        "SNOWFLAKE_WAREHOUSE", "SNOWFLAKE_DATABASE", "SNOWFLAKE_SCHEMA"]


@contextmanager
def env(**kw):
    saved = {k: os.environ.pop(k, None) for k in KEYS}
    os.environ.update({k: v for k, v in kw.items() if v is not None})
    try:
        yield
    finally:
        for k in KEYS:
            os.environ.pop(k, None)
        os.environ.update({k: v for k, v in saved.items() if v is not None})


def test_no_credentials_means_skip_condition_only():
    from skills import connection as c
    with env():
        assert c.has_credentials() is False and len(c.missing_config()) == 3
    with env(SNOWFLAKE_ACCOUNT="acct", SNOWFLAKE_USER="u"):
        assert c.has_credentials() is False, "account+user without a credential is still 'absent'"
    with env(SNOWFLAKE_ACCOUNT="acct", SNOWFLAKE_USER="u", SNOWFLAKE_PASSWORD="p"):
        assert c.has_credentials() is True and c.missing_config() == []
    with env(SNOWFLAKE_ACCOUNT="acct", SNOWFLAKE_USER="u", SNOWFLAKE_PAT="t"):
        assert c.has_credentials() is True
    print("  [PASS] has_credentials(): False only when account/user/credential are missing (the ONLY skip condition)")


def test_missing_config_error_names_variables_not_values():
    from skills import connection as c
    with env(SNOWFLAKE_ACCOUNT="acct123456"):
        try:
            c.connect_kwargs()
            raise AssertionError("must raise")
        except c.SnowflakeConfigError as e:
            msg = str(e)
            assert "SNOWFLAKE_USER" in msg and ".env.example" in msg and "acct123456" not in msg
    print("  [PASS] incomplete config → SnowflakeConfigError naming the missing variables (no values)")


def test_connect_kwargs_role_and_auth_modes():
    from skills import connection as c
    with env(SNOWFLAKE_ACCOUNT="a", SNOWFLAKE_USER="u", SNOWFLAKE_PASSWORD="p"):
        kw = c.connect_kwargs()
        assert kw["password"] == "p" and kw["warehouse"] == "FIU_WH" and kw["database"] == "FIU_COPILOT" and kw["schema"] == "AML"
        assert "role" not in kw
        assert c.connect_kwargs(role="FIU_APP_ROLE")["role"] == "FIU_APP_ROLE"
    with env(SNOWFLAKE_ACCOUNT="a", SNOWFLAKE_USER="u", SNOWFLAKE_PAT="t", SNOWFLAKE_ROLE="FIU_ADMIN_ROLE"):
        kw = c.connect_kwargs()
        assert kw["authenticator"] == "PROGRAMMATIC_ACCESS_TOKEN" and kw["token"] == "t" and kw["role"] == "FIU_ADMIN_ROLE"
    with env(SNOWFLAKE_ACCOUNT="a", SNOWFLAKE_USER="u", SNOWFLAKE_PRIVATE_KEY_PATH="/k.p8", SNOWFLAKE_PRIVATE_KEY_PASSPHRASE="x"):
        kw = c.connect_kwargs()
        assert kw["private_key_file"] == "/k.p8" and kw["private_key_file_pwd"] == "x" and "password" not in kw
    print("  [PASS] password / PAT / key-pair auth modes and SNOWFLAKE_ROLE are honoured; sensible defaults")


def test_connect_errors_are_actionable_and_never_leak_secrets():
    from skills import connection as c
    cases = {
        "390100 Incorrect username or password was specified.": "SNOWFLAKE_PASSWORD",
        "250001: Failed to connect to DB: x.snowflakecomputing.com:443. Incorrect username or password": "password",
        "Failed to authenticate: MFA with TOTP is required": "MFA",
        "390422: Incoming request with IP is not allowed to access Snowflake. network policy": "network policy",
        "Role 'FIU_APP_ROLE' specified in the connect string is not granted to this user": "GRANT ROLE",
        "Cannot perform operation. This session does not have a current database": "Unclassified",
    }
    with env(SNOWFLAKE_ACCOUNT="ORGNAME-ACCTNAME12", SNOWFLAKE_USER="jdoe@example.com", **SECRETS):
        for raw, expect in cases.items():
            poisoned = f"{raw} password={SECRETS['SNOWFLAKE_PASSWORD']} token {SECRETS['SNOWFLAKE_PAT']} user jdoe@example.com"
            msg = c.explain_connect_error(RuntimeError(poisoned))
            assert expect.lower() in msg.lower(), (raw, msg)
            for name, secret in SECRETS.items():
                assert secret not in msg, f"{name} leaked"
            assert "jdoe@example.com" not in msg and "ORGNAME-ACCTNAME12" not in msg, "identifiers must be masked"
            assert len(msg) < 600, "concise"
    print(f"  [PASS] {len(cases)} error classes → one actionable sentence; passwords, tokens, user and account id never printed")


def test_connect_from_env_wraps_connector_failures_without_leaking():
    from skills import connection as c
    import snowflake.connector as sc
    real = sc.connect
    def boom(**kw):
        raise sc.errors.DatabaseError(f"250001: Failed to connect. Incorrect username or password. pw={kw.get('password')}")
    sc.connect = boom
    try:
        with env(SNOWFLAKE_ACCOUNT="ORGNAME-ACCTNAME12", SNOWFLAKE_USER="jdoe", SNOWFLAKE_PASSWORD=SECRETS["SNOWFLAKE_PASSWORD"]):
            try:
                c.connect_from_env()
                raise AssertionError("must raise")
            except c.SnowflakeConnectError as e:
                assert SECRETS["SNOWFLAKE_PASSWORD"] not in str(e) and "SNOWFLAKE_PASSWORD" in str(e)
                assert e.__cause__ is None, "original exception (which may embed secrets) must not be chained"
    finally:
        sc.connect = real
    print("  [PASS] connect_from_env(): failure is SnowflakeConnectError, redacted, original exception not chained")


TESTS = [test_no_credentials_means_skip_condition_only, test_missing_config_error_names_variables_not_values,
         test_connect_kwargs_role_and_auth_modes, test_connect_errors_are_actionable_and_never_leak_secrets,
         test_connect_from_env_wraps_connector_failures_without_leaking]

if __name__ == "__main__":
    raise SystemExit(Runner("Connection / configuration tests (no network)").run(TESTS))
