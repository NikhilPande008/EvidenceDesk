#!/usr/bin/env python3
"""
Check an EvidenceDesk inspection pack WITHOUT the application or Snowflake.

  python3 scripts/verify_dossier.py decision-1a2b3c4d.json [--html page.html]

Replays everything that can be replayed from the file alone (skills/dossier.py `verify`): that the file is as sealed, that the ledger row hashes to
the hash the ledger stored (recomputed with Snowflake's own serialisation), that the stored gate and regulatory basis are consistent, that the
rationale and the included transactions match the digests recorded at the time, and, for a FILE, that the evidence gate still passes on the stored text.

Exit status: 0 when no check failed (VERIFIED, or INCOMPLETE where a check cannot be run on that decision), 1 when a check failed, 2 when the file cannot be read.
It cannot show that the ledger still holds the row (that is what the audit export is for).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skills import dossier as D  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("file")
    ap.add_argument("--html", help="also write the printable page")
    args = ap.parse_args()
    try:
        dossier = json.loads(Path(args.file).read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        print(f"cannot read {args.file}: {err}")
        return 2
    v = D.verify(dossier)
    d = (dossier.get("decision") or {}) if isinstance(dossier, dict) else {}
    print(f"Decision {d.get('decision_id')}  alert {d.get('alert_id')}  {d.get('disposition')}  by {d.get('decision_maker_id')}\n")
    for name, c in v["checks"].items():
        mark = {True: "ok     ", False: "FAILED ", None: "n/a    "}[c["ok"]]
        print(f"  {mark} {name.replace('_', ' '):28} {c['detail']}")
    print(f"\nVerdict: {v['verdict']}" + (f"  (failed: {', '.join(v['failed'])})" if v.get("failed") else ""))
    if args.html and isinstance(dossier, dict) and dossier.get("schema") == D.SCHEMA:
        Path(args.html).write_text(D.render_html(dossier, v), encoding="utf-8")
        print(f"wrote {args.html}")
    return 1 if v.get("failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
