"""
One place that knows how to connect to Snowflake from a local machine / CI.

Used by streamlit_app.py (local fallback), scripts/*.py and tests/*.py so that every
entry point has identical requirements, identical role handling and identical,
secret-free error messages.

Inside Streamlit-in-Snowflake none of this is used (the app gets a Snowpark session).

Environment (see .env.example):
  required   SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER  +  ONE credential:
               SNOWFLAKE_PASSWORD                      (password auth)
               SNOWFLAKE_PRIVATE_KEY_PATH [+ SNOWFLAKE_PRIVATE_KEY_PASSPHRASE]  (key-pair)
               SNOWFLAKE_PAT                           (programmatic access token)
  optional   SNOWFLAKE_ROLE, SNOWFLAKE_WAREHOUSE (FIU_WH), SNOWFLAKE_DATABASE (FIU_COPILOT),
             SNOWFLAKE_SCHEMA (AML), SNOWFLAKE_AUTHENTICATOR
"""

from __future__ import annotations

import os
import re
from pathlib import Path

DEFAULTS = {"SNOWFLAKE_WAREHOUSE": "FIU_WH", "SNOWFLAKE_DATABASE": "FIU_COPILOT", "SNOWFLAKE_SCHEMA": "AML"}
_CREDENTIAL_VARS = ("SNOWFLAKE_PASSWORD", "SNOWFLAKE_PRIVATE_KEY_PATH", "SNOWFLAKE_PAT")
_SECRET_VARS = ("SNOWFLAKE_PASSWORD", "SNOWFLAKE_PAT", "SNOWFLAKE_TOKEN", "SNOWFLAKE_PRIVATE_KEY_PASSPHRASE")


class SnowflakeConfigError(RuntimeError):
    """Required configuration is missing (no connection was attempted)."""


class SnowflakeConnectError(RuntimeError):
    """A connection was attempted and failed. Message is concise, actionable and secret-free."""


def load_env(repo_root: Path | None = None) -> None:
    """Load .env from the repo root if python-dotenv is available (no-op otherwise).

    FIU_SKIP_DOTENV=1 skips the file entirely — a hermetic run (CI, or a test that must prove behaviour
    *without* credentials on a machine that has a .env)."""
    if os.environ.get("FIU_SKIP_DOTENV") == "1":
        return
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover
        return
    root = repo_root or Path(__file__).resolve().parent.parent
    load_dotenv(root / ".env")


def has_credentials() -> bool:
    """True iff enough configuration exists to ATTEMPT a connection.
    Live tests skip ONLY when this is False; once it is True a failure is a real failure."""
    return bool(os.environ.get("SNOWFLAKE_ACCOUNT") and os.environ.get("SNOWFLAKE_USER")
                and any(os.environ.get(v) for v in _CREDENTIAL_VARS))


def missing_config() -> list[str]:
    missing = [v for v in ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER") if not os.environ.get(v)]
    if not any(os.environ.get(v) for v in _CREDENTIAL_VARS):
        missing.append("one of SNOWFLAKE_PASSWORD / SNOWFLAKE_PRIVATE_KEY_PATH / SNOWFLAKE_PAT")
    return missing


def redact(text: str) -> str:
    """Remove any configured secret value and the account/user identifiers from text."""
    out = str(text)
    for var in _SECRET_VARS + ("SNOWFLAKE_USER",):
        val = os.environ.get(var)
        if val and len(val) >= 4:
            out = out.replace(val, "<redacted>")
    acct = os.environ.get("SNOWFLAKE_ACCOUNT")
    if acct and len(acct) >= 4:
        out = out.replace(acct, mask_account(acct)).replace(acct.lower(), mask_account(acct))
    out = re.sub(r"(?i)(password|token|passphrase)\s*[=:]\s*\S+", r"\1=<redacted>", out)
    return out


def mask_account(account: str | None) -> str:
    if not account:
        return "<unset>"
    return account[:4] + "…" + account[-2:] if len(account) > 8 else "<set>"


# errno / substring → one actionable sentence. Order matters (first match wins).
_HINTS = (
    ("390100", "Incorrect user name or password. Check SNOWFLAKE_USER / SNOWFLAKE_PASSWORD in .env."),
    ("incorrect username or password", "Incorrect user name or password. Check SNOWFLAKE_USER / SNOWFLAKE_PASSWORD in .env."),
    ("390144", "Key-pair JWT rejected. Confirm the public key is registered for the user (ALTER USER … SET RSA_PUBLIC_KEY)."),
    ("mfa", "Account requires MFA / a second factor for password login. Use key-pair auth (SNOWFLAKE_PRIVATE_KEY_PATH) or a programmatic access token (SNOWFLAKE_PAT)."),
    ("390422", "Login blocked by a network policy. Add this machine's IP to the account network policy or use a permitted network."),
    ("network policy", "Login blocked by a network policy. Add this machine's IP to the account network policy."),
    ("250003", "Could not reach Snowflake. Check the account identifier format (<org>-<account> or <locator>.<region>) and your network / VPN."),
    ("failed to connect", "Could not reach Snowflake. Check SNOWFLAKE_ACCOUNT format (<org>-<account> or <locator>.<region>) and your network / VPN."),
    ("name or service not known", "Account host not found. Check SNOWFLAKE_ACCOUNT format (<org>-<account> or <locator>.<region>)."),
    ("not granted", "The requested role is not granted to this user. As ACCOUNTADMIN: GRANT ROLE <role> TO USER <user> (see deploy/01_roles.sql)."),
    ("role", "Role problem — check SNOWFLAKE_ROLE exists and is granted to this user (deploy/01_roles.sql)."),
    ("no active warehouse", "No active warehouse. Set SNOWFLAKE_WAREHOUSE (default FIU_WH) and ensure the role has USAGE on it."),
    ("does not exist or not authorized", "Database/schema/warehouse not found or role lacks USAGE. Run scripts/deploy_snowflake.py or check SNOWFLAKE_DATABASE/SCHEMA/WAREHOUSE."),
    ("timed out", "Connection timed out. Check your network / VPN and the account identifier."),
)


def explain_connect_error(err: Exception) -> str:
    raw = redact(str(err))
    low = raw.lower()
    hint = next((h for key, h in _HINTS if key in low), "Unclassified connection error — see detail.")
    detail = raw.strip().splitlines()[0][:160] if raw.strip() else type(err).__name__
    return (f"Snowflake connection failed (account {mask_account(os.environ.get('SNOWFLAKE_ACCOUNT'))}, "
            f"role {os.environ.get('SNOWFLAKE_ROLE') or '<user default>'}): {hint} [detail: {detail}]")


def connect_kwargs(role: str | None = None) -> dict:
    """Build connector kwargs from the environment. Raises SnowflakeConfigError if incomplete."""
    missing = missing_config()
    if missing:
        raise SnowflakeConfigError(
            "Missing Snowflake configuration: " + ", ".join(missing) +
            ". Copy .env.example to .env and fill it in (never commit .env).")
    kw: dict = {
        "account":   os.environ["SNOWFLAKE_ACCOUNT"],
        "user":      os.environ["SNOWFLAKE_USER"],
        "warehouse": os.environ.get("SNOWFLAKE_WAREHOUSE") or DEFAULTS["SNOWFLAKE_WAREHOUSE"],
        "database":  os.environ.get("SNOWFLAKE_DATABASE") or DEFAULTS["SNOWFLAKE_DATABASE"],
        "schema":    os.environ.get("SNOWFLAKE_SCHEMA") or DEFAULTS["SNOWFLAKE_SCHEMA"],
        "login_timeout": 30, "network_timeout": 120,
    }
    role = role or os.environ.get("SNOWFLAKE_ROLE")
    if role:
        kw["role"] = role
    if os.environ.get("SNOWFLAKE_PRIVATE_KEY_PATH"):
        kw["private_key_file"] = os.environ["SNOWFLAKE_PRIVATE_KEY_PATH"]
        if os.environ.get("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE"):
            kw["private_key_file_pwd"] = os.environ["SNOWFLAKE_PRIVATE_KEY_PASSPHRASE"]
    elif os.environ.get("SNOWFLAKE_PAT") and not os.environ.get("SNOWFLAKE_PASSWORD"):
        kw["authenticator"] = "PROGRAMMATIC_ACCESS_TOKEN"
        kw["token"] = os.environ["SNOWFLAKE_PAT"]
    else:
        kw["password"] = os.environ["SNOWFLAKE_PASSWORD"]
    if os.environ.get("SNOWFLAKE_AUTHENTICATOR"):
        kw["authenticator"] = os.environ["SNOWFLAKE_AUTHENTICATOR"]
    return kw


def connect_from_env(role: str | None = None):
    """Open a connector connection from the environment.

    Raises SnowflakeConfigError (nothing attempted) or SnowflakeConnectError (attempt
    failed; concise, actionable, secret-free message)."""
    import snowflake.connector
    kw = connect_kwargs(role)
    try:
        conn = snowflake.connector.connect(**kw)
    except Exception as err:  # noqa: BLE001 - re-raised as a redacted, actionable error
        raise SnowflakeConnectError(explain_connect_error(err)) from None
    if kw.get("role"):
        # Snowflake's default secondary roles are ALL: a session "as FIU_APP_ROLE" would silently also carry
        # every other role the user holds (incl. the object owner) and least privilege would be void.
        # (2026-09-30: exactly this let a verification script TRUNCATE + DROP the ledger.) An explicit role
        # therefore means ONLY that role.
        try:
            cur = conn.cursor()
            cur.execute("USE SECONDARY ROLES NONE")
            cur.close()
        except Exception as err:  # noqa: BLE001
            conn.close()
            raise SnowflakeConnectError(
                f"Could not isolate role {kw['role']} (USE SECONDARY ROLES NONE failed: {redact(str(err)).splitlines()[0][:120]}); refusing to continue.") from None
    return conn
