#!/usr/bin/env python3
"""
Load an institution's alert feed into EvidenceDesk: validate it, say what was refused and why, and (only when told to) write what was accepted.

  python3 scripts/load_feed.py --alerts domain/feeds/canonical_alerts.csv --transactions domain/feeds/canonical_transactions.csv
  python3 scripts/load_feed.py --alerts domain/feeds/tm_export_alerts.csv --transactions domain/feeds/tm_export_transactions.csv --map domain/feeds/tm_export_mapping.json
  python3 scripts/load_feed.py ... --apply --expect-database <DATABASE> [--schema AML]        # needs an OWNER role; the app role cannot write

Default is a DRY RUN: nothing is written, the report is printed (and saved with --report). The contract is skills/feed_contract.py; the columns and the
rules are in docs/DATA_CONTRACT.md. --apply upserts the accepted alerts and transactions (MERGE, so a re-run is safe), loads nothing that was rejected, and
refuses unless --expect-database names the database the connection is actually on, so a feed cannot land in the wrong environment by accident. A feed
never carries an answer key or a decision: only signals and the rows behind them.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from skills import feed_contract as FC  # noqa: E402


def read_rows(path: str) -> list[dict]:
    p = Path(path)
    if p.suffix.lower() == ".json":
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
            raise ValueError(f"{path}: a JSON feed must be a list of objects")
        return data
    with p.open(newline="", encoding="utf-8-sig") as fh:
        return [dict(r) for r in csv.DictReader(fh)]


def prepare(alerts_path: str, txns_path: str, mapping_path: str | None, today: date) -> dict:
    mapping = json.loads(Path(mapping_path).read_text(encoding="utf-8")) if mapping_path else None
    alerts = FC.apply_mapping(read_rows(alerts_path), FC.ALERT_FIELDS, mapping, "alerts")
    txns = FC.apply_mapping(read_rows(txns_path), FC.TXN_FIELDS, mapping, "transactions")
    return FC.validate(alerts, txns, today=today)


def print_report(rep: dict) -> None:
    s = rep["summary"]
    print(f"alerts: {s['alerts_accepted']} of {s['alerts_in']} accepted · transactions: {s['transactions_accepted']} of {s['transactions_in']} accepted · "
          f"{s['rejected']} rejected · {s['warnings']} warning(s)")
    for r in rep["rejected"]:
        print(f"  REJECTED {r['file']} row {r['row']} ({r['id']}): " + "; ".join(r["reasons"]))
    for w in rep["warnings"]:
        print(f"  warning  {w['id']}: {w['text']}")


def apply(rep: dict, expect_database: str, schema: str) -> int:
    import setup_alerts as seed
    from skills import connection as C
    C.load_env(ROOT)
    if C.missing_config():
        print("No Snowflake configuration: " + ", ".join(C.missing_config()))
        return 2
    conn = C.connect_from_env()
    cur = conn.cursor()
    cur.execute("SELECT CURRENT_DATABASE(), CURRENT_ROLE()")
    db, role = cur.fetchone()
    if str(db).upper() != expect_database.upper():
        print(f"REFUSED: connected to database {db}, but --expect-database says {expect_database}. Nothing was written.")
        return 3
    if "APP_ROLE" in str(role).upper():
        print(f"REFUSED: {role} is the application role, which cannot write alerts by design. Use the owner role.")
        return 3
    rewrite = lambda sql: sql.replace(".AML.", f".{schema}.")  # noqa: E731
    ok_a = ok_t = 0
    for a in rep["alerts"]:
        cur.execute(rewrite(seed.MERGE_SQL), FC.load_params(a))
        ok_a += 1
    for t in rep["transactions"]:
        cur.execute(rewrite(seed.TXN_MERGE_SQL), FC.txn_params(t))
        ok_t += 1
    conn.commit() if hasattr(conn, "commit") else None
    print(f"loaded into {db}.{schema} as {role}: {ok_a} alert(s), {ok_t} transaction row(s)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--alerts", required=True)
    ap.add_argument("--transactions", required=True)
    ap.add_argument("--map", help="mapping file for a feed in another shape (see domain/feeds/tm_export_mapping.json)")
    ap.add_argument("--today", help="YYYY-MM-DD (default: today); dates after it are refused")
    ap.add_argument("--report", help="write the full report as JSON")
    ap.add_argument("--apply", action="store_true", help="write the accepted rows (default is a dry run)")
    ap.add_argument("--expect-database", help="with --apply: the database this feed is meant for")
    ap.add_argument("--schema", default="AML")
    args = ap.parse_args()
    try:
        rep = prepare(args.alerts, args.transactions, args.map, date.fromisoformat(args.today) if args.today else date.today())
    except (OSError, ValueError, KeyError) as err:
        print(f"cannot read the feed: {err}")
        return 2
    print_report(rep)
    if args.report:
        Path(args.report).write_text(json.dumps(rep, indent=1, default=str) + "\n")
    if not args.apply:
        print("dry run: nothing was written (add --apply --expect-database NAME to load the accepted rows)")
        return 0 if not rep["rejected"] else 1
    if not args.expect_database:
        print("--apply needs --expect-database NAME")
        return 2
    return apply(rep, args.expect_database, args.schema)


if __name__ == "__main__":
    raise SystemExit(main())
