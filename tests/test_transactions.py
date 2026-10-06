"""
T1: TRANSACTIONS wiring — proves the deterministic evidence layer now operates on
governed transaction data instead of the empty list it received before (audit §0).

No Snowflake needed: imports the seed data from scripts/setup_alerts.py and runs the
pure-Python validate_gos_evidence gate against it.

Usage:
    python3 tests/test_transactions.py
"""

from __future__ import annotations
import sys
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "scripts"))

from skills import CoPilotSkills          # noqa: E402
import setup_alerts as seed               # noqa: E402

RECONCILE_TOLERANCE = 0.01                 # ±1%, matches validate_gos_evidence


def _to_skill_shape(seed_rows: list[dict]) -> list[dict]:
    """Mirror streamlit_app._load_transactions: DB row → skill dict shape."""
    return [
        {
            "txn_id":       r["TXN_ID"],
            "date":         r["TXN_DATE"],
            "type":         r["TXN_TYPE"],
            "amount_inr":   float(r["AMOUNT_INR"]),
            "counterparty": r["COUNTERPARTY"],
        }
        for r in seed_rows
    ]


def _txns_for(alert_id: str) -> list[dict]:
    return _to_skill_shape([t for t in seed.TRANSACTIONS if t["ALERT_ID"] == alert_id])


def test_every_alert_has_transactions():
    """No alert may feed the skills an empty transaction list (the §0 bug)."""
    for a in seed.ALERTS:
        n = sum(1 for t in seed.TRANSACTIONS if t["ALERT_ID"] == a["ALERT_ID"])
        assert n > 0, f"{a['ALERT_ID']} has no transactions"
    print(f"  [PASS] all {len(seed.ALERTS)} alerts have transactions ({len(seed.TRANSACTIONS)} rows)")


def test_flow_totals_reconcile():
    """The flow the alert is about (CREDIT rows; DEBIT rows for the outward-flow alerts) must equal ALERT_AMOUNT_INR within ±1%, except an alert whose
    contradiction is DOCUMENTED in the seed (HEADER_AMOUNT_CONTRADICTIONS). A documented contradiction must really exist; an undocumented one must not."""
    bad, contradictions = [], set()
    for a in seed.ALERTS:
        aid = a["ALERT_ID"]
        side = "DEBIT" if aid in seed.OUTWARD_FLOW_ALERTS else "CREDIT"
        flow = sum(float(t["AMOUNT_INR"]) for t in seed.TRANSACTIONS if t["ALERT_ID"] == aid and t["TXN_TYPE"] == side)
        target = float(a["ALERT_AMOUNT_INR"])
        if target > 0 and abs(flow - target) / target > RECONCILE_TOLERANCE:
            (contradictions.add(aid) if aid in seed.HEADER_AMOUNT_CONTRADICTIONS else bad.append(f"{aid}: {side.lower()}s {flow:,.0f} vs alert {target:,.0f}"))
    assert not bad, "flow totals do not reconcile:\n  " + "\n  ".join(bad)
    assert contradictions == set(seed.HEADER_AMOUNT_CONTRADICTIONS), f"a documented contradiction no longer exists: {set(seed.HEADER_AMOUNT_CONTRADICTIONS) - contradictions}"
    print(f"  [PASS] flow totals reconcile to ALERT_AMOUNT_INR (±1%) for {len(seed.ALERTS) - len(contradictions)} alerts; {sorted(contradictions)} carry a documented, deliberate contradiction")


def test_txn_ids_unique():
    ids = [t["TXN_ID"] for t in seed.TRANSACTIONS]
    assert len(ids) == len(set(ids)), "duplicate TXN_IDs in seed"
    print(f"  [PASS] {len(ids)} TXN_IDs unique")


def test_hard_gate_runs_on_loaded_data():
    """
    The core §0 fix: the hard gate must catch a hallucinated amount and pass a
    grounded one, USING the loaded transaction data (not a test fixture).
    """
    skills = CoPilotSkills(None)            # validate_gos_evidence is pure Python
    txns = _txns_for("ALERT-01")            # 110000 / 140000 / 246500 / 95000 / 94200
    assert txns, "ALERT-01 transactions did not load"

    grounded = ("Credits of ₹1,10,000 and ₹1,40,000 were received from unknown "
                "handles; ₹2,46,500 was immediately transferred to a flagged counterparty.")
    res_ok = skills.validate_gos_evidence(grounded, txns)
    assert res_ok["passed"], f"grounded narrative should pass, got {res_ok}"

    hallucinated = ("The account transferred ₹25,00,000 to a counterparty in Dubai "
                    "and received ₹1,10,000 from an unknown handle.")
    res_bad = skills.validate_gos_evidence(hallucinated, txns)
    assert not res_bad["passed"], "hallucinated ₹25,00,000 should fail the hard gate"
    assert res_bad["unsupported_claims"], "unsupported_claims must be populated"
    print(f"  [PASS] hard gate on loaded data — grounded passes; "
          f"hallucination caught: {res_bad['unsupported_claims']}")


def test_skill_shape_contract():
    """Loaded rows must carry the keys the skills read (txn_id/type/amount_inr)."""
    t = _txns_for("ALERT-01")[0]
    for k in ("txn_id", "type", "amount_inr", "counterparty"):
        assert k in t, f"missing key {k} in skill-shape transaction"
    assert t["type"] in ("CREDIT", "DEBIT")
    print("  [PASS] loaded transaction dict matches the skill contract")


TESTS = [
    test_every_alert_has_transactions,
    test_flow_totals_reconcile,
    test_txn_ids_unique,
    test_hard_gate_runs_on_loaded_data,
    test_skill_shape_contract,
]

if __name__ == "__main__":
    print("Running TRANSACTIONS wiring tests (no Snowflake required)...\n")
    passed = failed = 0
    for fn in TESTS:
        try:
            fn()
            passed += 1
        except Exception as exc:
            failed += 1
            print(f"  [FAIL] {fn.__name__}: {exc}")
    print(f"\n{passed}/{passed + failed} tests passed.")
    if failed:
        sys.exit(1)
