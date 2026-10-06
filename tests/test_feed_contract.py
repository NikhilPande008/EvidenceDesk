"""
The case feed contract and loader (skills/feed_contract.py, scripts/load_feed.py).

An institution's detection system sends two files. These suites pin what is accepted, what is refused and why, that a differently shaped export maps
onto the contract with a small mapping file, that nothing is guessed or repaired, and that the loader writes only accepted rows, only when told which
database it expects, and never with the application role.

Offline. Usage:  python3 tests/test_feed_contract.py     (or pytest)
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date

from _helpers import ROOT, Runner

sys.path.insert(0, str(ROOT / "scripts"))

TODAY = date(2026, 10, 5)
FEEDS = ROOT / "domain" / "feeds"


def _alert(**over):
    base = {"alert_id": "A-1", "customer_ref": "C-1", "alert_date": "2026-09-22", "alert_type": "PASS_THROUGH", "alert_amount_inr": "100000", "signal_source": None, "account_type": None,
            "customer_profile": None, "alert_narrative": None, "suspicion_formed_at": None, "rfi_triggers": None}
    base.update(over)
    return base


def _txn(**over):
    base = {"txn_id": "T-1", "alert_id": "A-1", "txn_date": "2026-09-22", "txn_type": "CREDIT", "amount_inr": "100000", "channel": None, "counterparty": None, "is_flagged": None, "customer_ref": None}
    base.update(over)
    return base


def test_a_clean_feed_is_accepted_and_normalised():
    from skills import feed_contract as FC
    rep = FC.validate([_alert(rfi_triggers="RFI-001; RFI-005", suspicion_formed_at="2026-09-29T11:00:00+05:30")], [_txn(txn_type="credit", amount_inr="1,00,000", is_flagged="Y")], today=TODAY)
    assert rep["summary"] == {"alerts_in": 1, "alerts_accepted": 1, "transactions_in": 1, "transactions_accepted": 1, "rejected": 0, "warnings": 0}, rep
    a, t = rep["alerts"][0], rep["transactions"][0]
    assert a["rfi_triggers"] == ["RFI-001", "RFI-005"] and a["alert_amount_inr"] == 100000.0 and a["suspicion_formed_at"] == "2026-09-29T11:00:00+05:30"
    assert t["txn_type"] == "CREDIT" and t["amount_inr"] == 100000.0 and t["is_flagged"] is True and t["customer_ref"] == "C-1", "the customer defaults to the alert's"
    print("  [PASS] a clean feed: types normalised, tags split, flags read, the customer defaulted from the alert")


def test_every_kind_of_bad_row_is_refused_with_its_reason_and_nothing_is_repaired():
    from skills import feed_contract as FC
    bad_alerts = [
        (_alert(alert_id=""), "alert_id is required"), (_alert(alert_id="has space"), "alert_id may hold"), (_alert(alert_id="x" * 21), "limit is 20"),
        (_alert(alert_date="22/09/2026"), "not a YYYY-MM-DD"), (_alert(alert_date="2026-10-20"), "in the future"), (_alert(alert_date="1999-01-01"), "before 2000"),
        (_alert(alert_amount_inr="abc"), "not a number"), (_alert(alert_amount_inr="-5"), "positive amount"), (_alert(alert_amount_inr="0"), "positive amount"),
        (_alert(alert_amount_inr="1e30"), "below"), (_alert(alert_type="bad\x00type"), "control character"), (_alert(customer_profile="x" * 501), "limit is 500"),
        (_alert(suspicion_formed_at="2026-09-29T11:00:00"), "no time zone"), (_alert(suspicion_formed_at="yesterday"), "not an ISO 8601"), (_alert(rfi_triggers="ok; not ok!"), "plain id"),
        (_alert(customer_ref=None), "customer_ref is required"),
    ]
    for row, needle in bad_alerts:
        rep = FC.validate([row], [], today=TODAY)
        assert rep["summary"]["alerts_accepted"] == 0 and any(needle in r for r in rep["rejected"][0]["reasons"]), (needle, rep["rejected"])
    bad_txns = [
        (_txn(txn_type="X"), "not CREDIT or DEBIT"), (_txn(amount_inr="nan"), "positive amount"), (_txn(txn_date="2026-02-31"), "not a YYYY-MM-DD"), (_txn(alert_id="ZZ"), "not an accepted alert"),
        (_txn(is_flagged="maybe"), "not true or false"), (_txn(counterparty="x" * 201), "limit is 200"), (_txn(txn_id=None), "txn_id is required"),
    ]
    for row, needle in bad_txns:
        rep = FC.validate([_alert()], [row], today=TODAY)
        assert rep["summary"]["transactions_accepted"] == 0 and any(needle in r for r in rep["rejected"][0]["reasons"]), (needle, rep["rejected"])
    print(f"  [PASS] {len(bad_alerts)} kinds of bad alert row and {len(bad_txns)} kinds of bad transaction row are refused, each with a reason naming the field")


def test_duplicates_and_orphans_are_refused_and_the_rest_of_the_feed_still_loads():
    from skills import feed_contract as FC
    rep = FC.validate([_alert(), _alert(), _alert(alert_id="A-2")], [_txn(), _txn(), _txn(txn_id="T-2", alert_id="A-2"), _txn(txn_id="T-3", alert_id="GONE")], today=TODAY)
    assert [a["alert_id"] for a in rep["alerts"]] == ["A-1", "A-2"] and [t["txn_id"] for t in rep["transactions"]] == ["T-1", "T-2"]
    reasons = [(r["file"], r["row"]) for r in rep["rejected"]]
    assert ("alerts", 2) in reasons and ("transactions", 2) in reasons and ("transactions", 4) in reasons
    assert any("more than once" in w for r in rep["rejected"] for w in r["reasons"])
    # an alert that was itself rejected takes its transactions with it: they are orphans, not silently attached elsewhere
    rep2 = FC.validate([_alert(alert_amount_inr="oops")], [_txn()], today=TODAY)
    assert rep2["summary"]["alerts_accepted"] == 0 and rep2["summary"]["transactions_accepted"] == 0 and "not an accepted alert" in rep2["rejected"][1]["reasons"][0]
    print("  [PASS] a duplicate id or a transaction with no accepted alert is refused; everything else loads")


def test_warnings_name_what_the_officer_will_see_without_refusing_the_row():
    from skills import feed_contract as FC
    rep = FC.validate([_alert(), _alert(alert_id="A-2", alert_amount_inr="500000", suspicion_formed_at="2026-09-29T11:00:00+05:30"), _alert(alert_id="A-3")],
                      [_txn(), _txn(txn_id="T-2", alert_id="A-2", amount_inr="100000")], today=TODAY)
    text = {w["id"]: w["text"] for w in rep["warnings"]}
    assert "not recorded" in text["A-1"] or "clock" in text["A-1"]
    assert "reconcile" in " ".join(w["text"] for w in rep["warnings"] if w["id"] == "A-2")
    assert "no transaction rows" in text["A-3"] and "FILE will be blocked" in text["A-3"]
    assert rep["summary"]["alerts_accepted"] == 3
    out = FC.validate([_alert(alert_amount_inr="100000")], [_txn(txn_type="DEBIT", amount_inr="100000")], today=TODAY)
    assert not [w for w in out["warnings"] if "reconcile" in w["text"]], "an outward alert reconciles on its debits"
    print("  [PASS] no rows, a reconciliation gap and a missing suspicion time are warned about, not refused; an outward alert reconciles on debits")


def test_a_differently_shaped_export_maps_onto_the_contract_with_a_mapping_file():
    import load_feed as LF
    rep = LF.prepare(str(FEEDS / "tm_export_alerts.csv"), str(FEEDS / "tm_export_transactions.csv"), str(FEEDS / "tm_export_mapping.json"), TODAY)
    assert rep["summary"]["alerts_accepted"] == 3 and rep["summary"]["transactions_accepted"] == 7 and rep["summary"]["rejected"] == 3, rep["summary"]
    a = {x["alert_id"]: x for x in rep["alerts"]}["TM-7001"]
    assert a["alert_date"] == "2026-09-26" and a["alert_amount_inr"] == 460000.0 and a["suspicion_formed_at"] == "2026-09-29T10:30:00+05:30", a
    t = {x["txn_id"]: x for x in rep["transactions"]}
    assert t["R-6"]["txn_type"] == "DEBIT" and t["R-6"]["is_flagged"] is True and t["R-1"]["txn_type"] == "CREDIT" and t["R-1"]["amount_inr"] == 150000.0
    reasons = {r["id"]: " ".join(r["reasons"]) for r in rep["rejected"]}
    assert "not an accepted alert" in reasons["R-8"] and "31/02/2026" in reasons["R-9"] and "'X'" in reasons["R-10"], reasons
    assert not [w for w in rep["warnings"] if "reconcile" in w["text"]], "every TM alert's credits reconcile to its total value"
    print("  [PASS] the sample TM export (own column names, D/C, Y/N, DD/MM/YYYY, zone-less IST time, Indian digit grouping) loads 3 alerts and 7 rows; its 3 bad rows are refused with reasons")


def test_the_canonical_sample_feed_loads_with_only_the_expected_warnings():
    import load_feed as LF
    rep = LF.prepare(str(FEEDS / "canonical_alerts.csv"), str(FEEDS / "canonical_transactions.csv"), None, TODAY)
    assert rep["summary"]["rejected"] == 0 and rep["summary"]["alerts_accepted"] == 3 and rep["summary"]["transactions_accepted"] == 13
    assert [w["id"] for w in rep["warnings"]] == ["FEED-002", "FEED-003"] and all("suspicion_formed_at" in w["text"] for w in rep["warnings"])
    print("  [PASS] the canonical sample: 3 alerts, 13 rows, no refusals, two 'no suspicion time' warnings")


def test_load_parameters_match_the_seed_merge_statements_and_carry_no_answer_key():
    import setup_alerts as seed
    from skills import feed_contract as FC
    rep = FC.validate([_alert(suspicion_formed_at="2026-09-29T11:00:00+05:30", rfi_triggers="RFI-001")], [_txn(channel="UPI", counterparty="Someone")], today=TODAY)
    ap, tp = FC.load_params(rep["alerts"][0]), FC.txn_params(rep["transactions"][0])
    assert set(re.findall(r"%\((\w+)\)s", seed.MERGE_SQL)) == set(ap), "every placeholder of the alert MERGE has a value, and nothing else is passed"
    assert set(re.findall(r"%\((\w+)\)s", seed.TXN_MERGE_SQL)) == set(tp)
    assert "GOLD_DISPOSITION" not in ap and ap["SCENARIO_ID"] == "FEED" and ap["POE_FACTORS"] == "[]" and json.loads(ap["RFI_TRIGGERS"]) == ["RFI-001"] and ap["ALERT_STATUS"] == "OPEN"
    assert len(ap["SCENARIO_ID"]) <= 5, "the ALERTS column is VARCHAR(5)"
    print("  [PASS] the parameters are exactly the placeholders of the seed MERGE statements; a feed alert carries no answer key and is OPEN")


class _Cur:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, params=None):
        self.conn.log.append((sql, params))
        self._row = (self.conn.db, self.conn.role) if "CURRENT_DATABASE" in sql else None

    def fetchone(self):
        return self._row

    def close(self):
        pass


class _Conn:
    def __init__(self, db, role):
        self.db, self.role, self.log = db, role, []

    def cursor(self):
        return _Cur(self)

    def close(self):
        pass


def _run_apply(db, role, expect, monkeypatch_conn):
    import load_feed as LF
    from skills import connection as C
    rep = LF.prepare(str(FEEDS / "canonical_alerts.csv"), str(FEEDS / "canonical_transactions.csv"), None, TODAY)
    conn = monkeypatch_conn(db, role)
    saved = (C.load_env, C.missing_config, C.connect_from_env)
    C.load_env, C.missing_config, C.connect_from_env = (lambda *a, **k: None), (lambda: []), (lambda *a, **k: conn)
    try:
        return LF.apply(rep, expect, "AML"), conn
    finally:
        C.load_env, C.missing_config, C.connect_from_env = saved


def test_the_loader_refuses_the_wrong_database_and_the_application_role_and_otherwise_merges_only_accepted_rows():
    rc, conn = _run_apply("FIU_COPILOT", "FIU_ADMIN_ROLE", "SOME_OTHER_DATABASE", _Conn)
    assert rc == 3 and len(conn.log) == 1, "wrong database: nothing but the identity query ran"
    rc, conn = _run_apply("FIU_COPILOT", "FIU_APP_ROLE", "FIU_COPILOT", _Conn)
    assert rc == 3 and len(conn.log) == 1, "the application role cannot write by design: refused before any write"
    rc, conn = _run_apply("FIU_COPILOT", "FIU_ADMIN_ROLE", "fiu_copilot", _Conn)
    merges = [s for s, _ in conn.log if s.lstrip().startswith("MERGE")]
    assert rc == 0 and len(merges) == 3 + 13 and all(".AML." in m for m in merges) and not [s for s, _ in conn.log if re.search(r"\b(UPDATE|DELETE|DROP|TRUNCATE)\b", s.split("MERGE", 1)[0])]
    print("  [PASS] --apply refuses a database that is not the one named and the application role, and otherwise issues one MERGE per accepted row")


def test_the_published_documents_name_every_field_of_the_contract_and_every_threshold_the_code_enforces():
    from skills import feed_contract as FC
    doc = (ROOT / "docs" / "DATA_CONTRACT.md").read_text(encoding="utf-8")
    for field in list(FC.ALERT_FIELDS) + list(FC.TXN_FIELDS):
        assert f"`{field}`" in doc, f"DATA_CONTRACT.md does not describe {field}"
    for needle in ("CREDIT", "DEBIT", "1%", "--expect-database", "Nothing is repaired or guessed", "owner role"):
        assert needle in doc, needle
    assert f"{FC.RECONCILIATION_TOLERANCE:.0%}" == "1%"
    pilot = (ROOT / "docs" / "PILOT_PROTOCOL.md").read_text(encoding="utf-8")
    from skills.kpis import MIN_CASES_FOR_A_CLAIM
    assert f"at least {MIN_CASES_FOR_A_CLAIM} decisions" in pilot and "No pilot has been run" in pilot and "no result below is a prediction" in pilot
    import re as _re
    assert not _re.search(r"\b\d+(\.\d+)?\s?(%|percent|hours?|minutes?)\s+(faster|saved|reduction|improvement)", pilot, _re.I), "the pilot plan states no outcome"
    print("  [PASS] DATA_CONTRACT.md describes every field and the enforced rules; PILOT_PROTOCOL.md uses the same 30-decision rule as the KPI code and states no outcome")


TESTS = [
    test_a_clean_feed_is_accepted_and_normalised, test_every_kind_of_bad_row_is_refused_with_its_reason_and_nothing_is_repaired,
    test_duplicates_and_orphans_are_refused_and_the_rest_of_the_feed_still_loads, test_warnings_name_what_the_officer_will_see_without_refusing_the_row,
    test_a_differently_shaped_export_maps_onto_the_contract_with_a_mapping_file, test_the_canonical_sample_feed_loads_with_only_the_expected_warnings,
    test_load_parameters_match_the_seed_merge_statements_and_carry_no_answer_key,
    test_the_loader_refuses_the_wrong_database_and_the_application_role_and_otherwise_merges_only_accepted_rows,
    test_the_published_documents_name_every_field_of_the_contract_and_every_threshold_the_code_enforces,
]


if __name__ == "__main__":
    raise SystemExit(Runner("Case feed contract and loader").run(TESTS))
