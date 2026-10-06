"""
Live smoke tests WITHOUT an LLM: connection, seeded data, retrieval governance and the recorder's
write path. Every write happens inside a transaction that is ROLLED BACK, so the append-only
DECISION_LEDGER is never polluted (the previous version of this file inserted a permanent
'TEST-PO' FILE row on every run — 10 of the 12 rows in the live ledger came from it).

Skipped only when credentials are absent; otherwise a failure is a real failure.
Run:  python3 -m pytest tests/test_skills_smoke.py -v     (or python3 tests/test_skills_smoke.py)
"""

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from skills import CoPilotSkills  # noqa: E402

pytestmark = pytest.mark.live
MANIFEST = yaml.safe_load((ROOT / "domain/corpus/manifest.yaml").read_text())


def _rows(conn, sql):
    import snowflake.connector
    cur = conn.cursor(snowflake.connector.DictCursor)
    try:
        cur.execute(sql)
        return cur.fetchall()
    finally:
        cur.close()


def test_connection_context(conn):
    r = _rows(conn, "SELECT CURRENT_ROLE() R, CURRENT_DATABASE() D, CURRENT_SCHEMA() S, CURRENT_WAREHOUSE() W")[0]
    assert (r["D"], r["S"]) == ("FIU_COPILOT", "AML"), r
    print(f"\n  connected: role={r['R']} warehouse={r['W']} {r['D']}.{r['S']}")


def test_corpus_matches_manifest(conn):
    m = MANIFEST["counts"]
    got = {r["EVIDENCE_LEVEL"]: r["N"] for r in _rows(conn, "SELECT EVIDENCE_LEVEL, COUNT(*) N FROM REGULATORY_CORPUS GROUP BY 1")}
    assert got == {"PROVEN": m["PROVEN"], "ASSUMED": m["ASSUMED"], "NEEDS-VERIFICATION": m["NEEDS-VERIFICATION"]}, \
        f"corpus in Snowflake differs from domain/corpus/manifest.yaml: {got} — run scripts/load_corpus.py --upsert"
    v = _rows(conn, "SELECT COUNT(DISTINCT CORPUS_VERSION) NV, MAX(CORPUS_VERSION) V, COUNT_IF(SOURCE_AUTHORITY IS NULL OR REVIEW_STATUS IS NULL OR OWNER IS NULL) NULLS FROM REGULATORY_CORPUS")[0]
    assert v["NV"] == 1 and v["V"] == MANIFEST["corpus_version"] and v["NULLS"] == 0, \
        f"governance columns not loaded ({v}) — run: python3 scripts/deploy_snowflake.py --apply --step ddl --step data"
    print(f"\n  corpus {v['V']}: {got}; governance columns populated on all rows")


def test_search_service_active_and_indexes_exactly_proven_and_assumed(conn):
    r = _rows(conn, "SHOW CORTEX SEARCH SERVICES LIKE 'CORPUS_SEARCH' IN SCHEMA FIU_COPILOT.AML")
    assert r, "CORPUS_SEARCH service missing — run the ddl step"
    r = {k.lower(): v for k, v in r[0].items()}
    assert r["indexing_state"] == "ACTIVE" and r["serving_state"] == "ACTIVE", r
    assert int(r["source_data_num_rows"]) == MANIFEST["counts"]["search_indexed"], \
        f"index has {r['source_data_num_rows']} rows, expected {MANIFEST['counts']['search_indexed']} (try ALTER CORTEX SEARCH SERVICE … REFRESH)"


def test_alerts_and_transactions_seeded(conn):
    import setup_alerts_ref as ref  # noqa: F401  (tests/setup_alerts_ref.py re-exports the seed)
    from collections import Counter
    assert Counter(a["GOLD_DISPOSITION"] for a in ref.ALERTS) == {"FILE": 10, "NOT_FILE": 5, "CONTESTED": 4}       # the key, as seeded (it is NOT readable by the app role)
    assert _rows(conn, "SELECT COUNT(*) N FROM ALERTS")[0]["N"] == len(ref.ALERTS)
    assert _rows(conn, "SELECT COUNT(*) N FROM TRANSACTIONS")[0]["N"] == len(ref.TRANSACTIONS)
    per_alert = {r["A"]: r["N"] for r in _rows(conn, "SELECT ALERT_ID A, COUNT(*) N FROM TRANSACTIONS GROUP BY 1")}
    assert len(per_alert) == len(ref.ALERTS) == 19 and all(per_alert.values())


def test_regulatory_lookup_is_governed(conn):
    res = CoPilotSkills(conn).regulatory_lookup_with_basis("STR filing deadline 7 working days")
    assert res["mode"] == "cortex_search", f"Cortex Search did NOT serve this lookup ({res['fallback_reason']}) — keyword fallback ran instead"
    assert res["rules"], "no rules returned"
    assert res["rules"][0]["rule_id"] in ("STR-002", "STR-001"), f"unexpected top hit {res['rules'][0]['rule_id']} for the deadline question"
    levels = [r["evidence_level"] for r in res["rules"]]
    assert set(levels) <= {"PROVEN", "ASSUMED"}, levels
    assert levels == sorted(levels, key=lambda l: l != "PROVEN"), f"PROVEN must come first: {levels}"
    assert res["basis"]["grade"] in ("PROVEN_ONLY", "INCLUDES_ASSUMED")
    assert res["basis"]["grade"] != "INCLUDES_ASSUMED" or res["basis"]["warning"]
    fin = CoPilotSkills(conn).regulatory_lookup_with_basis("upload the STR through FINnet direct upload")
    assert fin["qualifications"] and fin["qualifications"][0]["successor_rule"] == "STR-006", fin["qualifications"]


def test_recorder_write_path_is_inserted_hashed_and_rolled_back(conn):
    sk = CoPilotSkills(conn)
    before = _rows(conn, "SELECT COUNT(*) N FROM DECISION_LEDGER")[0]["N"]
    cur = conn.cursor()
    cur.execute("BEGIN")
    try:
        out = sk.alert_disposition_recorder(
            alert_id="ALERT-01", customer_ref="CUST-01", disposition="DEFERRED",
            rationale_text="[SMOKE TEST — rolled back] awaiting re-KYC documents before deciding.",
            rules_cited=["STR-001"], rfi_triggers=["RFI-001"], poe_assessment=[],
            decision_maker_id="SMOKE-TEST", suspicion_formed_at=None)
        row = _rows(conn, f"SELECT INTEGRITY_STATUS S, STORED_HASH H FROM DECISION_LEDGER_INTEGRITY_V WHERE DECISION_ID='{out['decision_id']}'")
        assert row and row[0]["S"] == "INTACT" and row[0]["H"] == out["row_hash"]
        meta = json.loads(_rows(conn, f"SELECT TO_JSON(METADATA_JSON) M FROM DECISION_LEDGER WHERE DECISION_ID='{out['decision_id']}'")[0]["M"])
        assert meta["ai_recommendation"] == "NOT_RUN" and meta["written_by_role"], meta
    finally:
        cur.execute("ROLLBACK")
    assert _rows(conn, "SELECT COUNT(*) N FROM DECISION_LEDGER")[0]["N"] == before, "smoke test must leave the ledger untouched"


def test_analyst_available(conn):
    from skills import CorpusAnalyst
    res = CorpusAnalyst(conn).ask("How many alerts are there?")
    assert res["available"], f"Cortex Analyst unavailable: {res['warnings']}"
    assert res["generated_sql"] and res["rows"] is not None, res


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "-s", "-p", "no:cacheprovider"]))
