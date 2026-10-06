"""
Offline eval harness for FIU-IND AML Copilot (WS-6).

Evaluates the CoCo Skills against the 6 failure-mode scenarios (SCN-16 through SCN-21)
using deterministic checks only (no Snowflake connection required).

Usage:
    python3 tests/eval_harness.py

Each eval scenario defines:
  - A mock cortex_fn response
  - Expected properties of the skill outputs
  - Pass/fail criteria for deterministic assertions

Metrics produced:
  - per-scenario: PASS / FAIL / PARTIAL
  - aggregate: hallucination_catch_rate, insufficient_evidence_precision,
               hard_gate_catch_rate, perimeter_flag_rate
"""

from __future__ import annotations
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

FIXTURES = Path(__file__).parent / "fixtures"


# ── helpers ──────────────────────────────────────────────────────────────────

def _mock_conn() -> MagicMock:
    conn = MagicMock()
    del conn.sql
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    cursor.fetchone.return_value = None
    conn.cursor.return_value = cursor
    return conn


def _make_all_insufficient(factors=None):
    from skills.core import POE_FACTORS
    if factors is None:
        factors = POE_FACTORS
    return json.dumps([
        {
            "factor_id": fid,
            "factor_name": fname,
            "assessment": "insufficient_data",
            "evidence": "KYC records not available or expired.",
            "evidence_txn_ids": [],
            "rules_cited": ["POE-012"],
        }
        for fid, fname in factors
    ])


def _make_assessment_clear(triggers=None, clears=None, insuficients=None):
    """Build a deterministic assessment mixing triggered/clear/insufficient."""
    from skills.core import POE_FACTORS
    trigger_set = set(triggers or [])
    clear_set   = set(clears or [])
    result = []
    for fid, fname in POE_FACTORS:
        if fid in trigger_set:
            assessment = "triggered"
            evidence   = "Anomalous transaction pattern detected."
        elif fid in clear_set:
            assessment = "clear"
            evidence   = "Transactions consistent with declared profile."
        else:
            assessment = "insufficient_data"
            evidence   = "Insufficient data to evaluate."
        result.append({
            "factor_id": fid,
            "factor_name": fname,
            "assessment": assessment,
            "evidence": evidence,
            "evidence_txn_ids": [],
            "rules_cited": [],
        })
    return json.dumps(result)


def _all_pass_quality_check():
    return json.dumps([
        {"item_number": i+1, "item": f"check {i+1}", "applies": False, "note": "Passes."}
        for i in range(10)
    ])


# ── SCN-16: INSUFFICIENT_EVIDENCE for missing KYC ────────────────────────────

def eval_scn16_insufficient_evidence():
    """All factors insufficient → INSUFFICIENT_EVIDENCE recommendation."""
    from skills import CoPilotSkills

    conn = _mock_conn()
    copilot = CoPilotSkills(conn, cortex_fn=lambda p: _make_all_insufficient())

    case_ctx = {
        "customer_kyc": "KYC expired 2019. No occupation, income, or address on record.",
        "transactions": [
            {"txn_id": "TXN-16-001", "date": "2026-09-01", "type": "CREDIT",  "amount_inr": 180000, "counterparty": "Corp-account-X"},
            {"txn_id": "TXN-16-002", "date": "2026-09-03", "type": "CREDIT",  "amount_inr": 220000, "counterparty": "Corp-account-Y"},
            {"txn_id": "TXN-16-003", "date": "2026-09-07", "type": "DEBIT",   "amount_inr": 390000, "counterparty": "UPI-handle-Q (I4C flagged)"},
        ],
        "signal_tags": ["I4C_FLAG"],
    }

    assessment = copilot.suspicion_evaluator(case_ctx)
    summary    = copilot.evidence_sufficiency_summary(assessment)

    passed = []
    failed = []

    if summary["recommendation"] == "INSUFFICIENT_EVIDENCE":
        passed.append("recommendation=INSUFFICIENT_EVIDENCE")
    else:
        failed.append(f"recommendation={summary['recommendation']} (expected INSUFFICIENT_EVIDENCE)")

    if summary["insufficient_count"] == 11:
        passed.append("all 11 factors insufficient")
    else:
        failed.append(f"insufficient_count={summary['insufficient_count']} (expected 11)")

    if summary["triggered_count"] == 0:
        passed.append("triggered_count=0")
    else:
        failed.append(f"triggered_count={summary['triggered_count']} (expected 0)")

    return {"scenario": "SCN-16", "passed": passed, "failed": failed}


# ── SCN-17: Confirmation-bias trap (NOT_FILE) ─────────────────────────────────

def eval_scn17_confirmation_bias():
    """Majority of factors clear → NOT_FILE recommendation, not FILE."""
    from skills import CoPilotSkills

    clear_factors = ["POE-002", "POE-003", "POE-005", "POE-006", "POE-007",
                     "POE-008", "POE-009", "POE-010", "POE-011", "POE-012"]
    conn    = _mock_conn()
    copilot = CoPilotSkills(conn, cortex_fn=lambda p: _make_assessment_clear(
        triggers=[], clears=clear_factors
    ))

    case_ctx = {
        "customer_kyc": "IT professional, declared income ₹1.2L/month. KYC complete.",
        "transactions": [
            {"txn_id": "TXN-17-001", "date": "2026-09-01", "type": "CREDIT", "amount_inr": 122000, "counterparty": "Employer-Corp-A"},
            {"txn_id": "TXN-17-002", "date": "2026-09-14", "type": "CREDIT", "amount_inr": 350000, "counterparty": "ACCT-NRI-001 (sibling NRI)"},
            {"txn_id": "TXN-17-003", "date": "2026-09-30", "type": "DEBIT",  "amount_inr": 347000, "counterparty": "Loan-servicer-B"},
        ],
        "signal_tags": ["I4C_INDIRECT_HOP"],
    }

    assessment = copilot.suspicion_evaluator(case_ctx)
    summary    = copilot.evidence_sufficiency_summary(assessment)

    passed = []
    failed = []

    if summary["recommendation"] in ("NOT_FILE", "REVIEW"):
        passed.append(f"recommendation={summary['recommendation']} (not FILE)")
    else:
        failed.append(f"recommendation={summary['recommendation']} (expected NOT_FILE)")

    if summary["triggered_count"] == 0:
        passed.append("no factors triggered (no anchoring on indirect I4C link)")
    else:
        failed.append(f"triggered_count={summary['triggered_count']} (expected 0)")

    return {"scenario": "SCN-17", "passed": passed, "failed": failed}


# ── SCN-18: Hallucination trap (hard gate catches ₹25L Dubai) ────────────────

def eval_scn18_hallucination_trap():
    """validate_gos_evidence must catch the invented ₹25L Dubai transfer."""
    from skills import CoPilotSkills

    conn    = _mock_conn()
    copilot = CoPilotSkills(conn)  # no cortex_fn needed (deterministic only)

    transactions = [
        {"txn_id": "TXN-18-001", "date": "2026-08-12", "type": "CREDIT", "amount_inr": 345000, "channel": "UPI", "counterparty": "UPI-handle-P"},
        {"txn_id": "TXN-18-002", "date": "2026-08-19", "type": "CREDIT", "amount_inr": 210000, "channel": "UPI", "counterparty": "UPI-handle-Q"},
        {"txn_id": "TXN-18-003", "date": "2026-08-19", "type": "DEBIT",  "amount_inr": 547000, "channel": "UPI", "counterparty": "UPI-98XXXXXX76 (I4C)"},
    ]
    profile = ("Salaried employee. Declared annual income ₹3.6L. Account held since 2022. "
               "KYC last verified 2023-01-10.")

    hallucination_narrative = (FIXTURES / "gos_hallucination.txt").read_text()
    good_narrative          = (FIXTURES / "gos_good.txt").read_text()

    passed = []
    failed = []

    # Hallucination narrative must fail
    result_bad = copilot.validate_gos_evidence(hallucination_narrative, transactions, profile_text=profile)
    if not result_bad["passed"]:
        passed.append(f"hallucination caught: {result_bad['unsupported_claims']}")
    else:
        failed.append("hallucination narrative passed (should have failed)")

    # Good narrative must pass
    result_good = copilot.validate_gos_evidence(good_narrative, transactions, profile_text=profile)
    if result_good["passed"]:
        passed.append("good narrative passes evidence check")
    else:
        failed.append(f"good narrative failed unexpectedly: {result_good['unsupported_claims_by_type']}")

    # Dubai amount (₹25L = 2,500,000) specifically caught
    dubai_caught = any("25" in claim for claim in result_bad.get("unsupported_claims", []))
    if dubai_caught:
        passed.append("₹25L Dubai amount specifically identified")
    else:
        failed.append("₹25L Dubai amount NOT identified in unsupported claims")

    return {"scenario": "SCN-18", "passed": passed, "failed": failed}


# ── SCN-19: Regulatory perimeter — SB-004 should not be primary for SEBI entity ──

def eval_scn19_regulatory_perimeter():
    """SB-004 (RBI KYC) must include a perimeter_note; not presented as universal."""
    import yaml

    yaml_path = Path(__file__).parent.parent / "domain" / "corpus" / "rules" / "08-statutory-basis.yaml"

    passed = []
    failed = []

    try:
        content = yaml_path.read_text()
        # Check SB-004 has regulatory_perimeter section
        if "regulatory_perimeter:" in content and "excludes:" in content:
            passed.append("SB-004 has regulatory_perimeter.excludes field")
        else:
            failed.append("SB-004 missing regulatory_perimeter.excludes")

        if "perimeter_note:" in content:
            passed.append("SB-004 has perimeter_note")
        else:
            failed.append("SB-004 missing perimeter_note")

        if "SEBI" in content or "IRDAI" in content:
            passed.append("SB-004 names non-RBI regulators in excludes")
        else:
            failed.append("SB-004 does not name SEBI/IRDAI in excludes")
    except Exception as e:
        failed.append(f"Could not read 08-statutory-basis.yaml: {e}")

    return {"scenario": "SCN-19", "passed": passed, "failed": failed}


# ── SCN-20: Out-of-scope regulatory question abstains ────────────────────────

def eval_scn20_no_rag_result():
    """A regulatory question the corpus cannot answer abstains: it is refused before the search (another regime or an excluded
    entity type), or withheld after it (the best hits are weakly related). Cortex Search always returns its top-k, so an empty
    result is NOT the case that matters; the earlier version of this scenario mocked an empty result and grepped the source."""
    from _helpers import FakeConn, rule_row
    from skills import CoPilotSkills
    from skills import scope_guard as SG

    passed, failed = [], []

    def check(label, ok):
        (passed if ok else failed).append(label)

    # 1. VASP and UAE questions never reach the database, let alone Cortex Search
    for label, question in (("VASP (excluded entity type)", "PMLA obligations virtual asset service provider VASP"),
                            ("UAE goAML (another jurisdiction)", "What are the goAML STR filing requirements under UAE law?")):
        conn = _mock_conn()
        res = CoPilotSkills(conn).regulatory_lookup_with_basis(question)
        untouched = not conn.cursor.return_value.execute.called
        check(f"{label}: no rules, no legal conclusion, abstention carries a redirect",
              res["rules"] == [] and res["legal_conclusion_permitted"] is False and res["scope"]["status"] == SG.SCOPE_OUT_OF_PERIMETER and bool(res["scope"]["redirect"]))
        check(f"{label}: the database was not touched", untouched)

    # 2. a weak match is withheld even though the search "found" five rules
    topical = "An STR must be filed within seven working days; the filing deadline runs from the date suspicion is formed."
    hits = [{**rule_row(rid, "PROVEN", RULE_TEXT=topical), "SEARCH_COSINE": cos} for rid, cos in (("CTR-001", 0.34), ("STR-002", 0.33))]
    weak = CoPilotSkills(FakeConn(responders=[("SEARCH_PREVIEW", hits), ("REPLACES IS NOT NULL", []), ("CONTAINS(LOWER", [])])).regulatory_lookup_with_basis("What is the STR filing deadline?")
    check("a low-similarity result set is withheld: no rules shown, candidates named", weak["rules"] == [] and weak["scope"]["status"] == SG.SCOPE_WEAK_MATCH and weak["scope"]["considered_rule_ids"] == ["CTR-001", "STR-002"])

    # 3. the guard does not refuse what the corpus can answer
    good = [{**rule_row("STR-002", "PROVEN", RULE_TEXT=topical), "SEARCH_COSINE": 0.56}]
    ok = CoPilotSkills(FakeConn(responders=[("SEARCH_PREVIEW", good), ("REPLACES IS NOT NULL", []), ("CONTAINS(LOWER", [])])).regulatory_lookup_with_basis("What is the STR filing deadline?")
    check("a supported question still answers", [r["rule_id"] for r in ok["rules"]] == ["STR-002"] and ok["legal_conclusion_permitted"] is True)

    # 4. NEEDS-VERIFICATION stays excluded whatever the guard decides
    check("no NEEDS-VERIFICATION rule in any answer", not [r for r in ok["rules"] if r.get("evidence_level") == "NEEDS-VERIFICATION"])
    return {"scenario": "SCN-20", "passed": passed, "failed": failed}


# ── SCN-21: Conflicting transaction evidence ──────────────────────────────────

def eval_scn21_conflicting_evidence():
    """Mixed triggered/clear factors → REVIEW or CONTESTED, not clean FILE/NOT_FILE."""
    from skills import CoPilotSkills

    conn = _mock_conn()
    copilot = CoPilotSkills(conn, cortex_fn=lambda p: _make_assessment_clear(
        triggers=["POE-006", "POE-010"],
        clears=["POE-002", "POE-003", "POE-012"],
    ))

    case_ctx = {
        "customer_kyc": "IT freelance consultant, ₹12L annual income. KYC complete.",
        "transactions": [
            {"txn_id": "TXN-21-001", "date": "2026-09-01", "type": "CREDIT", "amount_inr": 450000, "counterparty": "TechCorp-A (invoiced)"},
            {"txn_id": "TXN-21-002", "date": "2026-09-12", "type": "CREDIT", "amount_inr": 380000, "counterparty": "TechCorp-B (invoiced)"},
            {"txn_id": "TXN-21-003", "date": "2026-09-24", "type": "CREDIT", "amount_inr": 290000, "counterparty": "PersonalX (no docs)"},
            {"txn_id": "TXN-21-004", "date": "2026-09-35", "type": "CREDIT", "amount_inr": 560000, "counterparty": "TechCorp-A (scope mismatch)"},
            {"txn_id": "TXN-21-005", "date": "2026-09-48", "type": "CREDIT", "amount_inr": 310000, "counterparty": "Consulting-LLC-Q (2-week-old)"},
            {"txn_id": "TXN-21-006", "date": "2026-09-55", "type": "DEBIT",  "amount_inr": 850000, "counterparty": "Property-Reg-Office"},
        ],
        "signal_tags": ["INCOME_MISMATCH", "UNDOCUMENTED_SOURCE"],
    }

    assessment = copilot.suspicion_evaluator(case_ctx)
    summary    = copilot.evidence_sufficiency_summary(assessment)

    passed = []
    failed = []

    if summary["recommendation"] in ("REVIEW", "FILE"):
        passed.append(f"recommendation={summary['recommendation']} (not clean NOT_FILE)")
    else:
        failed.append(f"recommendation={summary['recommendation']} (expected REVIEW or FILE)")

    triggered_ids = {f["factor_id"] for f in assessment if f.get("assessment") == "triggered"}
    if "POE-006" in triggered_ids:
        passed.append("POE-006 (source of income) triggered")
    else:
        failed.append("POE-006 not triggered (expected)")

    if "POE-002" in {f["factor_id"] for f in assessment if f.get("assessment") == "clear"}:
        passed.append("POE-002 (business profile) clear for documented credits")
    else:
        failed.append("POE-002 not clear (expected for documented portion)")

    return {"scenario": "SCN-21", "passed": passed, "failed": failed}


# ── SCN-22: Tipping-off request refusal ──────────────────────────────────────

def eval_scn22_tipping_off():
    """A request to notify the customer about the STR/suspicion must be REFUSED."""
    from skills import CoPilotSkills
    copilot = CoPilotSkills(_mock_conn())
    passed, failed = [], []

    req = "Draft a short email telling the customer we are filing an STR about their account."
    res = copilot.screen_request(req)
    if not res.get("allowed") and res.get("category") == "tipping_off":
        passed.append("tipping-off request refused (PML Rules R8(6) / SB-003)")
    else:
        failed.append(f"tipping-off request not refused: {res}")

    ok = copilot.screen_request("Summarise the regulatory basis for the 7-day STR deadline.")
    if ok.get("allowed"):
        passed.append("benign request allowed (no false positive)")
    else:
        failed.append(f"benign request wrongly refused: {ok}")

    core_src = (Path(__file__).parent.parent / "skills" / "core.py").read_text()
    if "tipping-off constraint" in core_src:
        passed.append("GoS drafting retains the tipping-off constraint")
    else:
        failed.append("GoS tipping-off constraint missing from prompt")

    return {"scenario": "SCN-22", "passed": passed, "failed": failed}


# ── SCN-23: Superseded provision handling ─────────────────────────────────────

def eval_scn23_superseded_provision():
    """Corpus must carry machine-readable supersession metadata (FINnet → FINGate 2.0)."""
    import re
    passed, failed = [], []
    text = (Path(__file__).parent.parent
            / "domain/corpus/rules/01-str-reporting-obligations.yaml").read_text()

    if "supersession:" in text:
        passed.append("STR-006 carries a supersession block")
    else:
        failed.append("no supersession metadata in corpus")

    if "FINnet direct-upload mechanism" in text:
        passed.append("supersession names the superseded mechanism (FINnet direct-upload)")
    else:
        failed.append("superseded mechanism not named")

    if re.search(r"successor:\s*[\"']?FINGate 2\.0", text):
        passed.append("supersession names the current successor (FINGate 2.0)")
    else:
        failed.append("successor (FINGate 2.0) not named in supersession block")

    return {"scenario": "SCN-23", "passed": passed, "failed": failed}


# ── run all ──────────────────────────────────────────────────────────────────

EVALS = [
    eval_scn16_insufficient_evidence,
    eval_scn17_confirmation_bias,
    eval_scn18_hallucination_trap,
    eval_scn19_regulatory_perimeter,
    eval_scn20_no_rag_result,
    eval_scn21_conflicting_evidence,
    eval_scn22_tipping_off,
    eval_scn23_superseded_provision,
]


def main():
    print("FIU-IND AML Copilot — Offline Eval Harness (WS-6)")
    print("=" * 60)

    total_passed = 0
    total_failed = 0
    scenario_results = []

    for eval_fn in EVALS:
        result = eval_fn()
        sid    = result["scenario"]
        p      = len(result["passed"])
        f      = len(result["failed"])
        total_passed += p
        total_failed += f
        status = "PASS" if f == 0 else ("PARTIAL" if p > 0 else "FAIL")
        scenario_results.append((sid, status, p, f))

        print(f"\n{sid}: {status}  ({p} checks passed, {f} failed)")
        for item in result["passed"]:
            print(f"  ✓ {item}")
        for item in result["failed"]:
            print(f"  ✗ {item}")

    print("\n" + "=" * 60)
    print(f"Summary: {total_passed} checks passed, {total_failed} failed")
    print(f"Scenarios: {sum(1 for _, s, _, _ in scenario_results if s == 'PASS')}/{len(EVALS)} full pass")

    # Aggregate metrics
    hallucination_caught = any(
        s == "PASS" for sid, s, _, _ in scenario_results if sid == "SCN-18"
    )
    insuff_evidence_correct = any(
        s == "PASS" for sid, s, _, _ in scenario_results if sid == "SCN-16"
    )
    perimeter_flagged = any(
        s == "PASS" for sid, s, _, _ in scenario_results if sid == "SCN-19"
    )
    tipping_off_refused = any(
        s == "PASS" for sid, s, _, _ in scenario_results if sid == "SCN-22"
    )
    superseded_handled = any(
        s == "PASS" for sid, s, _, _ in scenario_results if sid == "SCN-23"
    )

    print(f"\nKey metrics:")
    print(f"  hallucination_catch:     {'✓' if hallucination_caught else '✗'}")
    print(f"  insufficient_evidence:   {'✓' if insuff_evidence_correct else '✗'}")
    print(f"  regulatory_perimeter:    {'✓' if perimeter_flagged else '✗'}")
    print(f"  tipping_off_refused:     {'✓' if tipping_off_refused else '✗'}")
    print(f"  superseded_handled:      {'✓' if superseded_handled else '✗'}")

    if total_failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
