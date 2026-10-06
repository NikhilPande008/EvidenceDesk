"""
KPI and business-value model (skills/kpis.py): every KPI has a definition, a source, a caveat and ONE status (measured · proxy · synthetic labels ·
not measured · simulated); nothing claims an improvement without a baseline; simulated numbers are always marked.

Offline. Usage:  python3 tests/test_kpis.py     (or pytest)
"""

from __future__ import annotations

import json
import re

from _helpers import Runner

from skills import kpis as K  # noqa: E402
from skills.ledger import evidence_snapshot_sha256  # noqa: E402

ALLOWED = {K.MEASURED, K.PROXY, K.SYNTHETIC_LABELS, K.NOT_MEASURED, K.SIMULATED}
REAL_SHA = evidence_snapshot_sha256([{"txn_id": "T1", "date": "2026-08-01", "type": "CREDIT", "amount_inr": 5, "channel": "UPI", "counterparty": "x", "is_flagged": False}])


def row(disp, alert, at, sla=5, ai="FILE", override=False, basis_ok=True, evidence=True, officer="PO-SECRET-9"):
    meta = {"schema_version": "3", "ai_recommendation": ai, "human_decision": disp, "override": override, "evidence_snapshot_sha256": REAL_SHA if evidence else evidence_snapshot_sha256([]),
            "regulatory_basis": {"legal_conclusion_permitted": basis_ok}, "defensibility_gate": {"conditions": []}}
    return {"DISPOSITION": disp, "ALERT_ID": alert, "DECISION_MADE_AT": at, "SLA_DAYS_REMAINING": sla, "METADATA_JSON": json.dumps(meta), "DECISION_MAKER_ID": officer, "DECISION_ID": f"{alert}-{at}"}


def alerts():
    return [{"ALERT_ID": "A1", "ALERT_DATE": "2026-09-01", "GOLD_DISPOSITION": "FILE"}, {"ALERT_ID": "A2", "ALERT_DATE": "2026-09-01", "GOLD_DISPOSITION": "NOT_FILE"},
            {"ALERT_ID": "A3", "ALERT_DATE": "2026-09-02", "GOLD_DISPOSITION": "FILE"}, {"ALERT_ID": "A4", "ALERT_DATE": "2026-09-02", "GOLD_DISPOSITION": "NOT_FILE"},
            {"ALERT_ID": "A5", "ALERT_DATE": "2026-09-03", "GOLD_DISPOSITION": "CONTESTED"}]


def ledger():
    return [row("FILE", "A1", "2026-09-04T10:00:00", sla=6), row("FILE", "A2", "2026-09-07T10:00:00", sla=-1), row("NOT_FILE", "A3", "2026-09-07T11:00:00", ai="FILE", override=True),
            row("NOT_FILE", "A4", "2026-09-08T09:00:00", ai="NOT_FILE", evidence=False), row("FILE", "A5", "2026-09-08T10:00:00", basis_ok=False)]


def by_id(rep):
    return {k["id"]: k for k in rep["kpis"]}


def test_every_kpi_has_a_definition_a_source_a_caveat_and_one_known_status():
    rep = K.compute_kpis(ledger(), alerts())
    ids = by_id(rep)
    wanted = {"alert_to_decision_median_days", "alert_to_decision_p95_days", "investigation_time", "analyst_touch_time", "alert_to_str_ratio", "false_positive_proxy_rate",
              "precision_vs_labels", "recall_vs_labels", "f1_vs_labels", "filing_timeliness", "analyst_throughput", "override_rate", "audit_rework_rate", "complete_evidence_and_basis"}
    assert wanted <= set(ids), wanted - set(ids)
    for k in rep["kpis"]:
        assert k["status"] in ALLOWED and k["definition"] and k["source"] and k["caveat"] is not None and k["status_meaning"] == K.STATUS_MEANING[k["status"]], k["id"]
        if k["status"] == K.NOT_MEASURED:
            assert k["needs"], f"{k['id']}: a KPI that is not measured must say what is needed"
    print(f"  [PASS] {len(rep['kpis'])} KPIs (median / p95 time, touch time, alert-to-STR, false positive, precision / recall / F1, timeliness, throughput, override, rework, complete evidence + basis): each has a definition, source, caveat and one status")


def test_hands_on_investigation_time_and_touch_time_are_not_measured_and_say_what_is_needed():
    ids = by_id(K.compute_kpis(ledger(), alerts()))
    for k in ("investigation_time", "analyst_touch_time"):
        assert ids[k]["status"] == K.NOT_MEASURED and ids[k]["value"] is None and ids[k]["display"] == "—"
        assert "telemetry" in ids[k]["needs"].lower() or "case-management" in ids[k]["needs"].lower()
    e = ids["alert_to_decision_median_days"]
    assert e["status"] == K.MEASURED and "ELAPSED" in e["caveat"] and "not investigation time" in e["caveat"]
    print("  [PASS] hands-on investigation time and analyst touch time are NOT_MEASURED (needs: telemetry / case-management time); the elapsed-time KPI is measured and says it is not investigation time")


def test_the_measured_values_are_computed_correctly():
    ids = by_id(K.compute_kpis(ledger(), alerts()))
    # elapsed (days): A1 3, A2 6, A3 5, A4 6, A5 5 → median 5, nearest-rank p95 6
    assert ids["alert_to_decision_median_days"]["value"] == 5.0 and ids["alert_to_decision_p95_days"]["value"] == 6.0 and ids["alert_to_decision_median_days"]["n"] == 5
    assert ids["alert_to_str_ratio"]["value"] == 3 / 5 and ids["alert_to_str_ratio"]["n"] == 5
    assert ids["filing_timeliness"]["value"] == 2 / 3 and ids["filing_timeliness"]["n"] == 3
    assert ids["override_rate"]["value"] == 1 / 5
    # throughput: first decision Fri 2026-09-04, last Tue 2026-09-08 → 3 working days (Fri, Mon, Tue) → 5 / 3
    assert abs(ids["analyst_throughput"]["value"] - 5 / 3) < 1e-9, ids["analyst_throughput"]["value"]
    c = ids["complete_evidence_and_basis"]
    assert c["n"] == 5
    assert c["with_transaction_evidence"] == 4 and c["with_supported_basis"] == 4 and abs(c["value"] - 3 / 5) < 1e-9, c
    assert ids["false_positive_proxy_rate"]["status"] == K.PROXY and ids["false_positive_proxy_rate"]["value"] == 2 / 5
    print("  [PASS] median 5 d / p95 6 d (nearest rank); alert-to-STR 3/5; timeliness 2/3; override 1/5; throughput 5 decisions over 3 working days (Fri→Tue); evidence+basis 3/5; FP proxy 2/5")


def test_precision_recall_and_f1_are_computed_against_synthetic_labels_and_labelled_so():
    # latest concluding per alert: A1 FILE/FILE=TP, A2 FILE/NOT_FILE=FP, A3 NOT_FILE/FILE=FN, A4 NOT_FILE/NOT_FILE=TN, A5 CONTESTED excluded
    ids = by_id(K.compute_kpis(ledger(), alerts()))
    p, r, f = ids["precision_vs_labels"], ids["recall_vs_labels"], ids["f1_vs_labels"]
    assert p["confusion"] == {"tp": 1, "fp": 1, "fn": 1, "tn": 1, "n": 4, "precision": 0.5, "recall": 0.5, "f1": 0.5}
    assert (p["value"], r["value"], f["value"]) == (0.5, 0.5, 0.5) and p["status"] == r["status"] == f["status"] == K.SYNTHETIC_LABELS
    assert "synthetic" in p["caveat"].lower() and "not an adjudicated" in p["caveat"].lower() and "real-world accuracy" in p["caveat"]
    none = by_id(K.compute_kpis([row("FILE", "A1", "2026-09-04T10:00:00")], []))
    assert none["precision_vs_labels"]["status"] == K.NOT_MEASURED and "label" in none["precision_vs_labels"]["needs"]
    assert K.confusion([("FILE", "FILE")] * 3)["f1"] == 1.0 and K.confusion([("NOT_FILE", "NOT_FILE")])["precision"] is None
    print("  [PASS] precision / recall / F1 from the confusion matrix (1/1/1/1 → 50 % each); status SYNTHETIC_LABELS with the 'not adjudicated, no real-world accuracy' caveat; no labels → NOT_MEASURED")


def test_percentile_and_median_use_the_stated_methods():
    assert K.percentile([], 95) is None and K.median([]) is None
    assert K.percentile(list(range(1, 101)), 95) == 95.0 and K.percentile([5, 1, 3], 50) == 3.0 and K.percentile([7], 95) == 7.0
    assert K.median([1, 2, 3, 4]) == 2.5
    print("  [PASS] nearest-rank percentile (p95 of 1..100 = 95) and midpoint median (1,2,3,4 → 2.5)")


def test_an_improvement_is_refused_without_a_baseline_the_same_definition_and_enough_cases():
    base = {"value": 10.0, "n": 40, "definition": "median elapsed days"}
    cur = {"value": 7.0, "n": 35, "definition": "median elapsed days"}
    ok = K.improvement(base, cur, higher_is_better=False)
    assert ok["allowed"] and ok["delta"] == -3.0 and abs(ok["pct"] + 30.0) < 1e-9 and ok["direction"] == "better" and "not proof of cause" in ok["reason"]
    assert K.improvement(base, cur, higher_is_better=True)["direction"] == "worse"
    for label, args in (("no baseline", (None, cur)), ("baseline without value", ({"value": None, "n": 99, "definition": "x"}, cur)), ("no current", (base, None)),
                        ("different definition", (base, dict(cur, definition="mean elapsed days"))), ("small baseline", (dict(base, n=29), cur)), ("small current", (base, dict(cur, n=5))),
                        ("missing n", ({"value": 1.0, "definition": "x"}, {"value": 2.0, "definition": "x"}))):
        r = K.improvement(*args, higher_is_better=False)
        assert r["allowed"] is False and r["delta"] is None and r["reason"], label
    rep = K.compute_kpis(ledger(), alerts())
    assert rep["baseline"]["captured"] is False and "No improvement is claimed" in rep["claims_policy"] and str(K.MIN_CASES_FOR_A_CLAIM) in rep["claims_policy"]
    print("  [PASS] improvement() is allowed only with a baseline, the same definition and ≥30 cases in each period; every other case is refused with a reason; the report states that no baseline exists and no improvement is claimed")


def test_the_report_contains_no_improvement_claim_and_no_officer_identity():
    blob = json.dumps(K.compute_kpis(ledger(), alerts()))
    assert "PO-SECRET-9" not in blob and "DECISION_MAKER_ID" not in blob
    claim = re.compile(r"\b(?:improved|reduced by|saves?|savings|faster than|ROI|% (?:improvement|reduction|faster))\b", re.I)
    assert not claim.search(blob.replace("No improvement is claimed", "")), claim.search(blob)
    print("  [PASS] the KPI report names no officer and contains no improvement / savings / ROI claim")


def test_the_simulated_cohort_is_deterministic_and_every_number_is_marked_simulated():
    a, b, c = K.simulated_cohort(), K.simulated_cohort(), K.simulated_cohort(seed=15)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True) and json.dumps(a["kpis"]) != json.dumps(c["kpis"])
    assert a["simulated"] is True and a["n"] == 240 and a["notice"] == K.SIM_NOTICE and "not measurements" in a["notice"] and "no claim of improvement" in a["notice"]
    for k in a["kpis"]:
        assert k["status"] == K.SIMULATED and k["display"].endswith("(simulated)") and k["caveat"] == K.SIM_NOTICE and k["id"].startswith("sim_"), k["id"]
    assert not any(k["status"] != K.SIMULATED for k in a["kpis"]) and len(a["kpis"]) >= 8
    print(f"  [PASS] the demonstration cohort ({a['n']} cases, seed {a['seed']}) is deterministic; all {len(a['kpis'])} figures are status SIMULATED, end in “(simulated)” and carry the not-a-measurement notice")


def test_open_case_decision_readiness_is_computed_from_the_evidence_quality_of_the_queue():
    ready = {"evaluated": True, "blocks_filing": False, "counts": {"REQUIRES_MANUAL_REVIEW": 0}, "sufficiency_pct": 90}
    thin = {"evaluated": True, "blocks_filing": False, "counts": {"REQUIRES_MANUAL_REVIEW": 1}, "sufficiency_pct": 90}
    blocked = {"evaluated": True, "blocks_filing": True, "counts": {"REQUIRES_MANUAL_REVIEW": 0}, "sufficiency_pct": 90}
    low = {"evaluated": True, "blocks_filing": False, "counts": {"REQUIRES_MANUAL_REVIEW": 0}, "sufficiency_pct": 79}
    k = by_id(K.compute_kpis([], [], open_case_quality=[ready, thin, blocked, low]))["open_cases_decision_ready"]
    assert k["value"] == 0.25 and k["n"] == 4 and k["status"] == K.MEASURED
    assert "open_cases_decision_ready" not in by_id(K.compute_kpis([], []))
    print("  [PASS] open cases with a decision-grade record: 1 of 4 (blocked, manual-review and <80 % sufficiency cases are not ready); absent when no queue is supplied")


TESTS = [
    test_every_kpi_has_a_definition_a_source_a_caveat_and_one_known_status, test_hands_on_investigation_time_and_touch_time_are_not_measured_and_say_what_is_needed,
    test_the_measured_values_are_computed_correctly, test_precision_recall_and_f1_are_computed_against_synthetic_labels_and_labelled_so,
    test_percentile_and_median_use_the_stated_methods, test_an_improvement_is_refused_without_a_baseline_the_same_definition_and_enough_cases,
    test_the_report_contains_no_improvement_claim_and_no_officer_identity, test_the_simulated_cohort_is_deterministic_and_every_number_is_marked_simulated,
    test_open_case_decision_readiness_is_computed_from_the_evidence_quality_of_the_queue,
]

if __name__ == "__main__":
    raise SystemExit(Runner("KPIs and business value (offline)").run(TESTS))
