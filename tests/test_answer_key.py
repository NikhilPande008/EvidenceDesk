"""
The answer key is out of the application's reach.

The synthetic alerts carry the scenario author's expected disposition (FILE / NOT_FILE / CONTESTED). It used to be a column of ALERTS, exposed through
ALERTS_CURRENT and Cortex Analyst's semantic model, so an officer could ask the copilot for "the correct answer" to the case in front of them. It now
lives in ALERT_GOLD_LABELS, which no grant gives to FIU_APP_ROLE. This suite pins that, offline, across every artifact the application can see; the
live proof (a refused read as the app role) is deploy/04_verify_ledger_rbac.sql and tests/test_live_e2e.py.

Usage:  python3 tests/test_answer_key.py     (or pytest)
"""

from __future__ import annotations

import re

import yaml

from _helpers import ROOT, Runner

import sys

sys.path.insert(0, str(ROOT / "scripts"))

import deploy_snowflake as deploy  # noqa: E402
import setup_alerts as seed  # noqa: E402
from skills import kpis as K  # noqa: E402


def code(path: str) -> str:
    """A file's text without SQL/Python comments (a comment may explain why the key is hidden)."""
    t = (ROOT / path).read_text()
    return re.sub(r"--[^\n]*", "", t) if path.endswith(".sql") else t


def test_nothing_the_application_reads_names_the_answer_key():
    for path in ("domain/corpus/export/ddl/views.sql", "domain/corpus/export/semantic_model.yaml", "streamlit_app.py"):
        assert "GOLD_DISPOSITION" not in code(path).upper(), f"{path} still exposes the answer key to the application role"
    alerts_ddl = code("domain/corpus/export/ddl/alerts.sql")
    assert "GOLD_DISPOSITION" not in alerts_ddl.upper() and "CHK_GOLD_DISP" not in alerts_ddl.upper(), "ALERTS has no answer-key column or constraint"
    for name in ("CREATE_TABLE_SQL", "MERGE_SQL"):
        assert "GOLD_DISPOSITION" not in getattr(seed, name), f"setup_alerts.{name} writes the key into ALERTS"
    print("  [PASS] ALERTS, ALERTS_CURRENT, the semantic model and the app's queries name no answer-key column")


def test_cortex_analyst_cannot_be_asked_for_the_answer():
    model = yaml.safe_load((ROOT / "domain/corpus/export/semantic_model.yaml").read_text())
    names: list[str] = []
    for table in model.get("tables", []):
        for group in ("dimensions", "time_dimensions", "facts", "measures", "metrics"):
            names += [str(c.get("name")) + " " + str(c.get("expr")) + " " + " ".join(map(str, c.get("synonyms") or [])) for c in table.get(group) or []]
    blob = " ".join(names + [str(q.get("sql")) + str(q.get("question")) for q in model.get("verified_queries", [])]).lower()
    for needle in ("gold_disposition", "ground truth", "correct answer", "expected outcome", "alert_gold_labels"):
        assert needle not in blob, f"the semantic model offers '{needle}'"
    print("  [PASS] semantic model: no dimension, measure, synonym or verified query offers the answer key")


def test_no_grant_gives_the_app_role_the_answer_key_and_none_is_broad_enough_to_include_it():
    grants = code("deploy/03_grants.sql")
    assert "ALERT_GOLD_LABELS" not in grants, "the answer key must not be granted to anyone by this file"
    app_lines = [ln for ln in grants.splitlines() if "FIU_APP_ROLE" in ln and ln.strip().upper().startswith("GRANT")]
    assert app_lines
    for ln in app_lines:
        assert not re.search(r"\bALL\s+TABLES\b|\bFUTURE\b|\bALL\s+PRIVILEGES\b|ON\s+SCHEMA\s+\S+\s+TO\s+ROLE\s+FIU_APP_ROLE;?\s*$", ln, re.I) or "USAGE ON SCHEMA" in ln.upper(), \
            f"a broad grant could include the answer key: {ln.strip()}"
    print(f"  [PASS] deploy/03_grants.sql: {len(app_lines)} app-role grants, each on a named object (no ALL TABLES / FUTURE / ALL PRIVILEGES), none on the key")


def test_the_key_has_a_table_of_its_own_that_the_deploy_creates_and_loads():
    ddl = code("domain/corpus/export/ddl/eval_labels.sql")
    assert re.search(r"CREATE TABLE IF NOT EXISTS ALERT_GOLD_LABELS", ddl) and "CHK_GOLD_DISP" in ddl
    assert "eval_labels.sql" in deploy.DDL_ORDER and deploy.DDL_ORDER.index("eval_labels.sql") > deploy.DDL_ORDER.index("alerts.sql")
    assert set(seed.GOLD_LABELS) == {a["ALERT_ID"] for a in seed.ALERTS} and len(seed.GOLD_LABELS) == 19
    assert "ALERT_GOLD_LABELS" in seed.LABELS_MERGE_SQL and "GOLD_DISPOSITION" in seed.LABELS_MERGE_SQL
    assert sorted(set(seed.GOLD_LABELS.values())) == ["CONTESTED", "FILE", "NOT_FILE"]
    from collections import Counter
    assert Counter(seed.GOLD_LABELS.values()) == {"FILE": 10, "NOT_FILE": 5, "CONTESTED": 4}
    print("  [PASS] ALERT_GOLD_LABELS has its own DDL (run after alerts.sql), its own loader, and all 16 labels")


def test_the_rbac_proof_requires_the_key_to_be_unreadable_and_ungranted():
    proof = code("deploy/04_verify_ledger_rbac.sql")
    assert "ALERT_GOLD_LABELS" in proof and "answer_key_read_denied" in proof and "answer_key_grants_to_app_role" in proof
    assert re.search(r"'overall',\s*IFF\([^;]*key_denied[^;]*key_grants\s*=\s*0", proof, re.S), "overall must fail unless the key is refused AND ungranted"
    migration = (ROOT / "deploy/08_move_gold_labels.sql").read_text()
    assert "ALERT_GOLD_LABELS" in migration and "-- ALTER TABLE ALERTS DROP COLUMN GOLD_DISPOSITION;" in migration, "the destructive step is present but commented out"
    print("  [PASS] RBAC proof: overall is PASS only if a read of the key is refused and the app role holds no grant on it; the migration's DROP is opt-in")


def test_without_the_key_the_label_kpis_say_not_measured_and_where_to_get_them():
    alerts = [{"ALERT_ID": "A1", "ALERT_DATE": "2026-09-01"}, {"ALERT_ID": "A2", "ALERT_DATE": "2026-09-01"}]       # rows as the app now reads them: no label
    ledger = [{"DISPOSITION": "FILE", "ALERT_ID": "A1", "DECISION_MADE_AT": "2026-09-02T10:00:00", "SUSPICION_FORMED_AT": "2026-09-01", "SLA_DAYS_REMAINING": 5, "META_TEXT": "{}"},
              {"DISPOSITION": "NOT_FILE", "ALERT_ID": "A2", "DECISION_MADE_AT": "2026-09-02T11:00:00", "SUSPICION_FORMED_AT": "2026-09-01", "SLA_DAYS_REMAINING": 5, "META_TEXT": "{}"}]
    rep = K.compute_kpis(ledger, alerts)
    by = {k["name"]: k for k in rep["kpis"]}
    labelled = [k for n, k in by.items() if "vs labels" in n]
    assert len(labelled) == 3 and all(k["status"] == K.NOT_MEASURED and k["display"] == "—" for k in labelled), [(k["name"], k["status"]) for k in labelled]
    assert all("eval_label_agreement.py" in (k["needs"] or "") and "cannot read the answer key" in k["needs"] for k in labelled)
    print("  [PASS] KPIs: precision / recall / F1 against labels are NOT MEASURED in the app, and say where to run them (admin role)")


TESTS = [
    test_nothing_the_application_reads_names_the_answer_key, test_cortex_analyst_cannot_be_asked_for_the_answer,
    test_no_grant_gives_the_app_role_the_answer_key_and_none_is_broad_enough_to_include_it, test_the_key_has_a_table_of_its_own_that_the_deploy_creates_and_loads,
    test_the_rbac_proof_requires_the_key_to_be_unreadable_and_ungranted, test_without_the_key_the_label_kpis_say_not_measured_and_where_to_get_them,
]

if __name__ == "__main__":
    raise SystemExit(Runner("Answer key out of the application's reach (offline)").run(TESTS))
