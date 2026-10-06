"""
env_fingerprint.py — a READ-ONLY fingerprint of one environment, to PROVE that a deployment into a different namespace did not touch it.

    python3 scripts/env_fingerprint.py --out before.json          # production (default names)
    ...run the clean-room deployment...
    python3 scripts/env_fingerprint.py --out after.json
    python3 scripts/env_fingerprint.py --compare before.json after.json     # exit 0 = identical, 1 = something changed

What it records (all SELECT / SHOW through scripts/health_check.py's read-only gate — nothing is written):
  * per table: row count and HASH_AGG(*) — an order-independent hash of EVERY row, so one changed value changes the hash;
  * the app role's complete grant list (hashed) and the ledger's grantees;
  * the Streamlit app (owner, warehouse, url id, created_on), the Cortex Search service (created_on, rows indexed, states);
  * the named account-level objects (database, warehouse, roles): name + created_on.
It does NOT record row values, only counts and hashes. Timestamps of the fingerprint itself are excluded from the comparison.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import health_check as H  # noqa: E402

TABLES = ("REGULATORY_CORPUS", "ALERTS", "TRANSACTIONS", "DECISION_LEDGER")
VIEWS = ("ALERT_TXN_SUMMARY", "ALERTS_CURRENT", "DECISION_LEDGER_INTEGRITY_V")


def _digest(rows: list[tuple]) -> str:
    return hashlib.sha256(json.dumps(sorted(rows), default=str).encode()).hexdigest()


def fingerprint(conn, db: str = H.DB, schema: str = H.SCHEMA, wh: str = H.WH, roles: tuple[str, ...] = (H.ADMIN, H.APP, H.AUDIT), app_role: str = H.APP) -> dict:
    r = H.Runner(conn)
    fp: dict = {"environment": {"database": db, "schema": schema, "warehouse": wh, "roles": list(roles)}, "tables": {}, "views": {}}
    for t in TABLES:
        try:
            row = r.q(f"SELECT COUNT(*) AS N, HASH_AGG(*) AS H FROM {db}.{schema}.{t}")[0]
            fp["tables"][t] = {"rows": int(row["n"]), "hash_agg": str(row["h"])}
        except Exception as err:  # noqa: BLE001
            fp["tables"][t] = {"unreadable": " ".join(str(err).split())[:80]}
    for v in VIEWS:
        try:
            row = r.q(f"SELECT COUNT(*) AS N FROM {db}.{schema}.{v}")[0]
            fp["views"][v] = {"rows": int(row["n"])}
        except Exception as err:  # noqa: BLE001
            fp["views"][v] = {"unreadable": " ".join(str(err).split())[:80]}
    try:
        fp["ledger_integrity"] = {x["integrity_status"]: int(x["n"]) for x in r.q(f"SELECT INTEGRITY_STATUS, COUNT(*) AS N FROM {db}.{schema}.DECISION_LEDGER_INTEGRITY_V GROUP BY 1")}
    except Exception as err:  # noqa: BLE001
        fp["ledger_integrity"] = {"unreadable": " ".join(str(err).split())[:80]}
    try:
        g = r.q(f"SHOW GRANTS TO ROLE {app_role}")
        rows = [(x["privilege"], x["granted_on"], x["name"], x.get("grant_option")) for x in g]
        fp["app_role_grants"] = {"count": len(rows), "sha256": _digest(rows)}
        led = r.q(f"SHOW GRANTS ON TABLE {db}.{schema}.DECISION_LEDGER")
        fp["ledger_grantees"] = sorted(f"{x['grantee_name']}:{x['privilege']}" for x in led)
    except Exception as err:  # noqa: BLE001
        fp["app_role_grants"] = {"unreadable": " ".join(str(err).split())[:80]}
    try:
        s = r.q(f"SHOW STREAMLITS LIKE 'FIU_AML_COPILOT' IN SCHEMA {db}.{schema}")
        fp["streamlit"] = [{k: str(x.get(k)) for k in ("owner", "query_warehouse", "url_id", "created_on")} for x in s]
    except Exception as err:  # noqa: BLE001
        fp["streamlit"] = {"unreadable": " ".join(str(err).split())[:80]}
    try:
        s = r.q(f"SHOW CORTEX SEARCH SERVICES LIKE 'CORPUS_SEARCH' IN SCHEMA {db}.{schema}")
        fp["search_service"] = [{k: str(x.get(k)) for k in ("created_on", "source_data_num_rows", "indexing_state", "serving_state", "warehouse")} for x in s]
    except Exception as err:  # noqa: BLE001
        fp["search_service"] = {"unreadable": " ".join(str(err).split())[:80]}
    objs = {}
    for kind, name in (("DATABASES", db), *(("WAREHOUSES", wh),), *(("ROLES", x) for x in roles)):
        try:
            hit = [x for x in r.q(f"SHOW {kind} LIKE '{name}'") if str(x["name"]).upper() == name.upper()]
            objs[f"{kind[:-1]} {name}"] = str(hit[0].get("created_on")) if hit else "absent"
        except Exception as err:  # noqa: BLE001
            objs[f"{kind[:-1]} {name}"] = "unreadable: " + " ".join(str(err).split())[:60]
    fp["named_objects"] = objs
    fp["statements_run"] = len(r.log)
    fp["taken_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return fp


def compare(a: dict, b: dict) -> list[str]:
    """Differences between two fingerprints, ignoring when they were taken and how many statements it took."""
    def strip(x):
        return {k: v for k, v in x.items() if k not in ("taken_at", "statements_run")}
    a, b = strip(a), strip(b)
    out: list[str] = []

    def walk(x, y, path=""):
        if isinstance(x, dict) and isinstance(y, dict):
            for k in sorted(set(x) | set(y)):
                if k not in x:
                    out.append(f"{path}{k}: appeared ({y[k]})")
                elif k not in y:
                    out.append(f"{path}{k}: disappeared (was {x[k]})")
                else:
                    walk(x[k], y[k], f"{path}{k}.")
        elif x != y:
            out.append(f"{path.rstrip('.')}: {x} → {y}")
    walk(a, b)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="write the fingerprint (JSON) to this file")
    ap.add_argument("--role", help="role to connect as (default: your default role — needs to SEE the roles / databases; read-only either way)")
    ap.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"), help="compare two fingerprint files (offline)")
    args = ap.parse_args()
    if args.compare:
        a, b = (json.loads(Path(p).read_text()) for p in args.compare)
        diff = compare(a, b)
        print("IDENTICAL — nothing in the fingerprinted environment changed." if not diff else "CHANGED:\n  " + "\n  ".join(diff))
        return 1 if diff else 0
    from skills.connection import SnowflakeConfigError, SnowflakeConnectError, connect_from_env, load_env, missing_config, redact
    load_env(ROOT)
    if missing_config():
        print("ERROR: missing Snowflake configuration: " + ", ".join(missing_config()), file=sys.stderr)
        return 1
    try:
        conn = connect_from_env(role=args.role)
    except (SnowflakeConfigError, SnowflakeConnectError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    try:
        fp = fingerprint(conn)
    finally:
        conn.close()
    text = redact(json.dumps(fp, indent=2, sort_keys=True, default=str))
    if args.out:
        Path(args.out).write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
