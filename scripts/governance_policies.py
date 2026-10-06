#!/usr/bin/env python3
"""
Opt-in column masking (deploy/10_governance_optin.sql): plan, apply, probe, remove.

  python3 scripts/governance_policies.py plan                 # what would be applied (default; nothing is changed)
  python3 scripts/governance_policies.py apply --apply        # create the two masking policies and attach them (as the owner role)
  python3 scripts/governance_policies.py probe                # read-only: what THIS role actually sees in the two masked columns, and which policies are attached
  python3 scripts/governance_policies.py remove --apply       # detach and drop them (deploy/10_governance_remove.sql)

`probe` is how the claim is checked: run it as the application role (clear text expected) and as any other role with SELECT (masked text expected) and compare.
It reports what came back; it does not decide whether that is right. Nothing here reads or writes DECISION_LEDGER.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from skills.connection import SnowflakeConfigError, SnowflakeConnectError, connect_from_env, load_env  # noqa: E402

load_env(ROOT)
APPLY_FILE, REMOVE_FILE = "deploy/10_governance_optin.sql", "deploy/10_governance_remove.sql"
MASK = "*** masked ***"
TARGETS = (("TRANSACTIONS", "COUNTERPARTY", "MASK_COUNTERPARTY"), ("ALERTS", "CUSTOMER_PROFILE", "MASK_CUSTOMER_PROFILE"))


def _connect(role: str | None):
    try:
        return connect_from_env(role=role)
    except (SnowflakeConfigError, SnowflakeConnectError) as err:
        raise SystemExit(f"ERROR: {err}")


def cmd_plan(_args) -> int:
    from deploy_snowflake import sql_file
    for f in (APPLY_FILE, REMOVE_FILE):
        stmts = sql_file(f)
        print(f"PLAN ONLY — {f}: {len(stmts)} statements")
        for s in stmts:
            print("   ", " ".join(s.split())[:130])
    print("Nothing was executed. `apply --apply` / `remove --apply` run them as the owner role.")
    return 0


def cmd_apply(args) -> int:
    from deploy_snowflake import run_statements, sql_file
    if not args.apply:
        return cmd_plan(args)
    conn = _connect("FIU_ADMIN_ROLE")
    try:
        run_statements(conn, sql_file(APPLY_FILE), "governance policies")
    finally:
        conn.close()
    print("Applied. Check with `probe` as the application role and as another role.")
    return 0


def cmd_remove(args) -> int:
    from deploy_snowflake import redact, sql_file
    if not args.apply:
        return cmd_plan(args)
    conn = _connect("FIU_ADMIN_ROLE")
    cur = conn.cursor()
    try:
        for stmt in sql_file(REMOVE_FILE):
            head = " ".join(stmt.split())[:100]
            try:
                cur.execute(stmt)
                print(f"    ok      {head}")
            except Exception as err:  # noqa: BLE001
                if "UNSET MASKING POLICY" in stmt.upper():     # idempotent: a column with no policy attached has nothing to detach
                    print(f"    skipped {head}  ({redact(str(err)).splitlines()[0][:100]})")
                    continue
                raise SystemExit(f"remove: {head} failed: {redact(str(err)).splitlines()[0][:200]}")
    finally:
        cur.close()
        conn.close()
    return 0


def cmd_probe(args) -> int:
    conn = _connect(args.role)
    cur = conn.cursor()
    try:
        cur.execute("SELECT CURRENT_ROLE(), CURRENT_DATABASE()")
        role, db = cur.fetchone()
        print(f"role {role} on {db}")
        for table, column, policy in TARGETS:
            cur.execute(f"SELECT {column} FROM AML.{table} WHERE {column} IS NOT NULL ORDER BY 1 LIMIT 200")
            values = [r[0] for r in cur.fetchall()]
            masked = sum(1 for v in values if v == MASK)
            print(f"  {table}.{column}: {len(values)} values read, {masked} masked, {len(values) - masked} in clear"
                  + (f"   e.g. {values[0][:48]!r}" if values else ""))
            try:
                cur.execute("SELECT POLICY_NAME FROM TABLE(INFORMATION_SCHEMA.POLICY_REFERENCES(REF_ENTITY_NAME => %s, REF_ENTITY_DOMAIN => 'TABLE')) WHERE REF_COLUMN_NAME = %s",
                            (f"{db}.AML.{table}", column))
                attached = [r[0] for r in cur.fetchall()]
                print(f"      policy attached, as far as this role can see: {', '.join(attached) if attached else 'nothing visible (a role without access to the reference view sees none: this is not proof of absence)'}")
            except Exception:  # noqa: BLE001 — the reference view may need privileges this role lacks; that is reported, not guessed
                print("      policy attached: could not be read as this role")
    finally:
        cur.close()
        conn.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    for name in ("plan", "apply", "remove", "probe"):
        p = sub.add_parser(name)
        if name in ("apply", "remove"):
            p.add_argument("--apply", action="store_true", help="execute (the default is a plan)")
        if name == "probe":
            p.add_argument("--role", help="connect as this role (default: the role in .env)")
    args = ap.parse_args()
    return {"plan": cmd_plan, "apply": cmd_apply, "remove": cmd_remove, "probe": cmd_probe}.get(args.cmd, cmd_plan)(args)


if __name__ == "__main__":
    raise SystemExit(main())
