#!/usr/bin/env python3
"""
Ledger audit CLI — non-destructive reconciliation and append-only export (skills/audit.py, deploy/05_audit_export.sql).

  python3 scripts/audit_ledger.py report                  # read-only integrity report; exit 1 if COMPROMISED
  python3 scripts/audit_ledger.py report --json           # same, machine-readable
  python3 scripts/audit_ledger.py export                  # PLAN only: how many ledger rows are not yet in the export
  python3 scripts/audit_ledger.py export --out ledger.ndjson   # write the pending export to a LOCAL file (no database write)
  python3 scripts/audit_ledger.py export --apply          # append the pending records to FIU_COPILOT.AUDIT.LEDGER_EXPORT
  python3 scripts/audit_ledger.py provision [--outcomes] [--apply]   # plan / create the audit role, schema and table (+ the outcome feed) (opt-in, ACCOUNTADMIN)
  python3 scripts/audit_ledger.py status                  # is audit-export protection provisioned and current? (read-only)
  python3 scripts/audit_ledger.py export --package-dir DIR   # also write the pending export as a write-once PACKAGE (NDJSON + manifest) to a LOCAL directory
  python3 scripts/audit_ledger.py verify DIR              # verify packages OFFLINE (no Snowflake): bodies, hash chains, links between packages

Safety
  * `report` and `export` (without --apply) only SELECT. `export --apply` only INSERTs, into the audit table, as FIU_AUDIT_ROLE,
    inside one transaction. No command here ever issues UPDATE, DELETE, TRUNCATE or DROP, and none touches DECISION_LEDGER.
  * Plan-only is the default for every command that could write. Nothing is uploaded anywhere except that INSERT.
  * Errors are reduced to one secret-free sentence (skills/connection.py).
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))      # deploy_snowflake (shared SQL splitter / runner)

from skills import audit  # noqa: E402
from skills.connection import SnowflakeConfigError, SnowflakeConnectError, connect_from_env, load_env  # noqa: E402

load_env(ROOT)
AUDIT_ROLE, APP_ROLE = "FIU_AUDIT_ROLE", "FIU_APP_ROLE"


def _connect(role: str | None):
    try:
        return connect_from_env(role=role)
    except (SnowflakeConfigError, SnowflakeConnectError) as err:
        raise SystemExit(f"ERROR: {err}")


def _executor(conn):
    import snowflake.connector

    def execute(sql: str) -> list[dict]:
        cur = conn.cursor(snowflake.connector.DictCursor)
        try:
            cur.execute(sql)
            return cur.fetchall()
        finally:
            cur.close()
    return execute


def _lit(value) -> str:
    from skills.core import _lit as lit
    return lit(value)


class LocalDirectorySink:
    """A SIMULATION of a write-once store, for the prototype: a package file is created exclusively (an existing name is refused, never
    overwritten) and made read-only. A local directory is NOT immutable — its owner can delete or chmod anything — so this proves the
    package format and the no-overwrite discipline, not WORM retention. The production sink is an object store with compliance-mode
    retention in another account (skills/audit.py WORM_REQUIREMENTS)."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def put(self, key: str, data: str) -> Path:
        import os
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("refusing to write outside the sink directory")
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)       # O_EXCL: an existing object is an error, not an overwrite
        with os.fdopen(fd, "w") as f:
            f.write(data)
        os.chmod(path, 0o444)
        return path


def load_packages(directory: Path) -> list[tuple[str, str]]:
    """The (ndjson, manifest json) pairs in a directory, ordered by first sequence number."""
    pairs = []
    for man in sorted(Path(directory).rglob("*.manifest.json")):
        body = man.with_name(man.name.replace(".manifest.json", ".ndjson"))
        pairs.append((json.loads(man.read_text()).get("first_seq", 0), body.read_text() if body.exists() else "", man.read_text()))
    return [(b, m) for _, b, m in sorted(pairs, key=lambda t: t[0])]


def cmd_verify(args) -> int:
    packages = load_packages(Path(args.path))
    if not packages:
        print(f"no packages found under {args.path}")
        return 1
    res = audit.verify_package_sequence(packages)
    print(f"{res['packages']} package(s), last SEQ {res['last_seq']}, head {str(res['head'])[:16]}… — {'VERIFIED' if res['ok'] else 'FAILED'}")
    for p in res["problems"]:
        print(f"  problem: {p}")
    print("  note: a verified chain proves the packages are internally consistent and in order. It does not prove they are the complete ledger "
          "(reconcile against the live ledger) or that the store they sit in is write-once.")
    return 0 if res["ok"] else 1


def cmd_status(args) -> int:
    from datetime import datetime, timezone
    conn = _connect(args.role or APP_ROLE)
    try:
        execute = _executor(conn)
        rows = audit.fetch_ledger_rows(execute)
        anchor, why = audit.fetch_anchor(execute)
    finally:
        conn.close()
    st = audit.export_protection_status(audit.reconcile(rows, anchor, anchor_error=why), now=datetime.now(timezone.utc))
    print(f"{st['level']}: {st['headline']}\n  {st['detail']}\n  external write-once copy: {st['external']} — {st['external_detail']}\n  residual risk: {st['residual_risk']}")
    return 0 if st["level"] == audit.STATUS_CURRENT else 2


def cmd_report(args) -> int:
    conn = _connect(args.role or APP_ROLE)
    try:
        execute = _executor(conn)
        rows = audit.fetch_ledger_rows(execute)
        anchor, why = audit.fetch_anchor(execute)
    finally:
        conn.close()
    rep = audit.reconcile(rows, anchor, anchor_error=why)
    if args.json:
        print(json.dumps(rep, indent=2, sort_keys=True, default=str))
    else:
        print(f"Ledger reconciliation: {rep['verdict']} — {rep['ledger_rows']} row(s): "
              + ", ".join(f"{n} {k}" for k, n in sorted(rep["by_integrity"].items())))
        for f in rep["findings"]:
            print(f"  [{f['severity']}] {f['code']} × {f['count']}: {f['detail']}")
        a = rep["anchor"]
        print("  audit export: " + (f"{a['records']} record(s), chain {'valid' if a['chain_valid'] else 'BROKEN'}" if a["present"] else f"none ({a['reason']})"))
        print(f"  deletion detectable: {'yes, for exported rows' if rep['deletion_detectable'] else 'NO — no valid audit export'}")
        for limit in rep["limits"]:
            print(f"  limit: {limit}")
    if rep["verdict"] == audit.VERDICT_COMPROMISED:
        return 1
    return 2 if (args.strict and rep["verdict"] == audit.VERDICT_ATTENTION) else 0


def cmd_export(args) -> int:
    conn = _connect(args.role or AUDIT_ROLE)
    try:
        execute = _executor(conn)
        rows = audit.fetch_ledger_rows(execute)
        anchor, why = audit.fetch_anchor(execute)
        if anchor is None:
            print(f"ERROR: the audit export table is not available ({why}). Provision it first: python3 scripts/audit_ledger.py provision --apply")
            return 1
        errors = audit.verify_chain(anchor) if anchor else []
        if errors:
            print("ERROR: the existing export chain is broken — refusing to extend it: " + "; ".join(errors[:3]))
            return 1
        exported = {r["DECISION_ID"] for r in anchor}
        pending = [r for r in rows if r["DECISION_ID"] not in exported]
        previous = sorted(anchor, key=lambda r: int(r["SEQ"]))[-1] if anchor else None
        records = audit.export_records(pending, previous)
        print(f"{len(rows)} ledger row(s); {len(exported)} already exported; {len(records)} pending "
              f"({sum(1 for r in records if not r['CONTENT_ANCHORED'])} legacy rows would be anchored by existence only).")
        manifest = audit.build_manifest(records, exported_by=args.role or AUDIT_ROLE)
        if args.out:
            Path(args.out).write_text(audit.to_ndjson(records, manifest))
            print(f"wrote {len(records)} record(s) to {args.out} (local file; nothing was written to Snowflake)")
        if args.package_dir and records:
            pkg = audit.worm_package(records, manifest, export_id=str(uuid.uuid4()))
            sink = LocalDirectorySink(Path(args.package_dir))
            body = sink.put(pkg["object_key"], pkg["ndjson"])
            sink.put(pkg["manifest_object_key"], pkg["manifest_json"])
            print(f"wrote package {body.name} + manifest (SEQ {pkg['manifest']['first_seq']}–{pkg['manifest']['last_seq']}, head {pkg['manifest']['head'][:16]}…) to {args.package_dir}\n"
                  "  SIMULATION: a local directory is not write-once. Copy the package to an object store with compliance-mode retention in ANOTHER account (DEPLOY.md, Audit export).")
        if not args.apply:
            if not args.out:
                print("PLAN ONLY — re-run with --apply to append these records to FIU_COPILOT.AUDIT.LEDGER_EXPORT.")
            return 0
        if not records:
            print("nothing to append.")
            return 0
        export_id = str(uuid.uuid4())
        stmts = audit.export_insert_sql(records, export_id, _lit)
        try:
            execute("BEGIN")
            for sql in stmts:
                execute(sql)
            execute("COMMIT")
        except Exception as err:  # noqa: BLE001
            try:
                execute("ROLLBACK")
            except Exception:  # noqa: BLE001
                pass
            print(f"ERROR: export failed and was rolled back: {' '.join(str(err).split())[:200]}")
            return 1
        print(f"appended {len(records)} record(s) as export {export_id}; chain head {records[-1]['CHAIN_HASH'][:16]}…")
        return 0
    finally:
        conn.close()


def cmd_provision(args) -> int:
    from deploy_snowflake import run_statements, sql_file     # same SQL splitter / runner the deploy driver uses
    files = ["deploy/05_audit_export.sql"] + (["deploy/07_decision_outcomes.sql"] if args.outcomes else [])
    if not args.apply:
        for f in files:
            stmts = sql_file(f, {"DEPLOY_USER": '"<connecting user>"'})
            print(f"PLAN ONLY — as ACCOUNTADMIN: {len(stmts)} statements from {f} "
                  + (f"(role {AUDIT_ROLE}, schema FIU_COPILOT.AUDIT, table LEDGER_EXPORT, SELECT for {APP_ROLE})." if "05_" in f else
                     f"(table FIU_COPILOT.AUDIT.DECISION_OUTCOMES, SELECT for {APP_ROLE}; requires 05 first)."))
        print("Re-run with --apply to execute.")
        return 0
    conn = _connect("ACCOUNTADMIN")
    user = conn.cursor().execute("SELECT CURRENT_USER()").fetchone()[0]
    for f in files:
        run_statements(conn, sql_file(f, {"DEPLOY_USER": f'"{user}"'}), "audit export store" if "05_" in f else "decision outcome feed")
    conn.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report", help="read-only reconciliation of the ledger (and of the audit export, if present)")
    r.add_argument("--role", help=f"default {APP_ROLE}")
    r.add_argument("--json", action="store_true")
    r.add_argument("--strict", action="store_true", help="exit 2 on ATTENTION (legacy rows / incomplete provenance / rows awaiting export)")
    e = sub.add_parser("export", help="build (and optionally append / write) the pending audit export")
    e.add_argument("--role", help=f"default {AUDIT_ROLE}")
    e.add_argument("--out", help="write the pending records as NDJSON to this LOCAL file")
    e.add_argument("--apply", action="store_true", help="append the pending records to FIU_COPILOT.AUDIT.LEDGER_EXPORT (default: plan only)")
    e.add_argument("--package-dir", help="also write the pending records as a write-once PACKAGE (NDJSON + manifest) into this LOCAL directory (a simulation of an external store)")
    p = sub.add_parser("provision", help="create the audit role / schema / table (opt-in; plan only unless --apply)")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--outcomes", action="store_true", help="also create the opt-in downstream-outcome feed (deploy/07_decision_outcomes.sql)")
    st = sub.add_parser("status", help="is audit-export protection provisioned and current? (read-only)")
    st.add_argument("--role", help=f"default {APP_ROLE}")
    v = sub.add_parser("verify", help="verify audit packages in a directory OFFLINE (no Snowflake)")
    v.add_argument("path")
    args = ap.parse_args()
    return {"report": cmd_report, "export": cmd_export, "provision": cmd_provision, "status": cmd_status, "verify": cmd_verify}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
