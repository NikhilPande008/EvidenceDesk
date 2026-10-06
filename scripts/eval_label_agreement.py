#!/usr/bin/env python3
"""
Compare recorded decisions with the synthetic scenario author's labels. ADMIN ROLE ONLY.

  python3 scripts/eval_label_agreement.py

The labels live in FIU_COPILOT.AML.ALERT_GOLD_LABELS, which FIU_APP_ROLE cannot read (deploy/03_grants.sql names every readable table and this
is not one; deploy/04_verify_ledger_rbac.sql proves it). So the application's Business value page cannot show these KPIs: they are computed here,
by someone holding the owner/admin role (set SNOWFLAKE_ROLE=FIU_ADMIN_ROLE in .env), and they say nothing about real-world accuracy: the
labels are one author's, not an adjudicated outcome. Read-only.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skills import connection as C  # noqa: E402
from skills.kpis import confusion  # noqa: E402


def main() -> int:
    C.load_env()
    if not C.has_credentials():
        print("No Snowflake credentials: set them in .env (see .env.example) with an admin role.")
        return 2
    try:
        conn = C.connect_from_env()
    except Exception as err:  # noqa: BLE001
        print("Could not connect:", C.redact(str(err)).splitlines()[0][:240])
        return 2
    import snowflake.connector
    cur = conn.cursor(snowflake.connector.DictCursor)
    try:
        cur.execute("SELECT ALERT_ID, GOLD_DISPOSITION FROM FIU_COPILOT.AML.ALERT_GOLD_LABELS")
        labels = {r["ALERT_ID"]: (r["GOLD_DISPOSITION"] or "").upper() for r in cur.fetchall()}
        cur.execute("SELECT ALERT_ID, DISPOSITION FROM FIU_COPILOT.AML.DECISION_LEDGER "
                    "QUALIFY ROW_NUMBER() OVER (PARTITION BY ALERT_ID ORDER BY DECISION_MADE_AT DESC) = 1")
        latest = {r["ALERT_ID"]: (r["DISPOSITION"] or "").upper() for r in cur.fetchall()}
    except Exception as err:  # noqa: BLE001
        print("Could not read the labels or the ledger (this needs an admin role, not FIU_APP_ROLE):", C.redact(str(err)).splitlines()[0][:200])
        return 2
    finally:
        conn.close()
    pairs = [(d, labels[a]) for a, d in latest.items() if d in ("FILE", "NOT_FILE") and labels.get(a) in ("FILE", "NOT_FILE")]
    cm = confusion(pairs)
    print(f"Decided alerts with a FILE/NOT_FILE label: {cm['n']}  (CONTESTED labels and escalations excluded; latest concluding decision per alert)")
    for k in ("precision", "recall", "f1"):
        print(f"  {k:9s} {'-' if cm[k] is None else format(cm[k], '.1%')}")
    print("These are the scenario author's labels, not adjudicated outcomes. They show the computation, not accuracy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
