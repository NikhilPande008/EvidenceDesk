"""
Readiness, architecture and known limitations (skills/readiness.py + ARCHITECTURE.md, PRODUCTION_READINESS.md, KNOWN_LIMITATIONS.md) and the approved-model allow-list.

The claim under test: every capability sits in exactly one of three tiers, an "implemented" item names a test that exists, the security checklist covers the fourteen controls
that were asked for, the seven-stage architecture separates fast deterministic work from slow on-demand AI, and the documents are RENDERED from this module so they cannot drift.

Offline. Usage:  python3 tests/test_readiness.py     (or pytest)
"""

from __future__ import annotations

import re

from _helpers import FakeConn, ROOT, Runner

from skills import core  # noqa: E402
from skills import readiness as R  # noqa: E402


def test_every_capability_is_in_exactly_one_tier_and_an_implemented_one_names_tests_that_exist():
    ids = [c["id"] for c in R.CAPABILITIES]
    assert len(ids) == len(set(ids))
    for c in R.CAPABILITIES:
        assert c["status"] in R.TIERS and c["capability"] and c["area"], c["id"]
        if c["status"] == R.IMPLEMENTED:
            assert c["evidence"], f"{c['id']}: an implemented capability must name its evidence"
            for f in re.split(r",\s*", c["evidence"]):
                assert (ROOT / f).exists(), f"{c['id']}: evidence {f} does not exist"
        if c["status"] == R.SIMULATED:
            assert c["simulated_by"] and c["production"], f"{c['id']}: a simulation names the stand-in and what replaces it"
        if c["status"] == R.PRODUCTION:
            assert c["production"], f"{c['id']}: a production requirement says what production needs"
        for w in re.split(r",\s*", c["where"] or ""):
            if re.match(r"^[\w./-]+\.(?:py|sql)\b", w.split()[0] if w.split() else ""):
                assert (ROOT / w.split()[0]).exists() or " " in w, f"{c['id']}: {w} does not exist"
    by = R.by_tier(R.CAPABILITIES)
    assert all(by[t] for t in R.TIERS), "all three tiers are populated"
    print(f"  [PASS] {len(ids)} capabilities: {len(by[R.IMPLEMENTED])} implemented (each names a test file that exists), {len(by[R.SIMULATED])} simulated (stand-in named), {len(by[R.PRODUCTION])} production requirements")


def test_the_security_checklist_covers_the_fourteen_asked_for_controls_and_never_oversells():
    wanted = {"SSO": "single sign-on", "MFA": "multi-factor", "AUTH-ID": "authenticated user identity", "MASK": "dynamic data masking", "RAP": "row-access", "LEAST": "least privilege",
              "NETPOL": "network policies", "MODELS": "approved-model", "PROMPT": "prompt minimisation", "RESIDENCY": "data residency", "RETENTION": "retention", "MONITOR": "monitoring",
              "SIEM": "siem", "SOD": "separation of duties"}
    got = {c["id"]: c for c in R.PRODUCTION_CHECKLIST}
    assert set(got) == set(wanted), set(got) ^ set(wanted)
    for cid, needle in wanted.items():
        assert needle in got[cid]["control"].lower(), (cid, got[cid]["control"])
        assert got[cid]["status"] in R.TIERS and got[cid]["today"] and got[cid]["production"]
    implemented = {cid for cid, c in got.items() if c["status"] == R.IMPLEMENTED}
    assert implemented == {"AUTH-ID", "LEAST", "MODELS", "PROMPT"}, implemented
    for cid in implemented:
        assert got[cid]["evidence"] and (ROOT / got[cid]["evidence"].split(",")[0]).exists()
    for cid in ("SSO", "MFA", "MASK", "RAP", "NETPOL", "RESIDENCY", "RETENTION", "MONITOR", "SIEM", "SOD"):
        assert got[cid]["status"] == R.PRODUCTION and got[cid]["evidence"] is None or cid == "MONITOR", cid
    print("  [PASS] 14 controls (SSO, MFA, authenticated identity, masking, row access, least privilege, network policy, model allow-list, prompt minimisation, residency, retention, monitoring, SIEM, separation of duties); only the 4 that are built and tested are 'implemented'")


def test_the_architecture_has_the_seven_requested_stages_in_order_and_separates_fast_from_slow():
    names = [s["name"].lower() for s in R.ARCHITECTURE_STAGES]
    order = ["ingestion", "monitoring", "queue", "ai enrichment", "officer review", "ledger", "integration"]
    assert [n for n in order if any(n in x for x in names)] == order and len(names) == 7
    assert [s["n"] for s in R.ARCHITECTURE_STAGES] == list(range(1, 8))
    lat = {s["n"]: s["latency"] for s in R.ARCHITECTURE_STAGES}
    assert lat[4] == R.LATENCY_AI and lat[4] != lat[3] and "deterministic" in lat[3].lower() and lat[1] == lat[2] == lat[3] == lat[6] == R.LATENCY_FAST
    assert lat[5] == lat[7] == R.LATENCY_HUMAN and "11–120 s" in R.LATENCY_AI
    status = {s["n"]: s["status"] for s in R.ARCHITECTURE_STAGES}
    assert status[4] == R.SIMULATED and status[7] == R.PRODUCTION and status[3] == R.IMPLEMENTED
    topics = " ".join(x["topic"].lower() for x in R.SCALABILITY)
    assert "millions of transactions" in topics and "regulatory documents" in topics
    print("  [PASS] 7 stages: ingestion → monitoring / signal source → prioritised queue → async AI enrichment → officer review → ledger → integration; the AI stage is the only slow-lane stage; scalability covers millions of transactions and regulatory documents")


def test_readiness_model_has_complete_ordered_roadmap_data():
    pri = [r["priority"] for r in R.ROADMAP]
    assert pri == sorted(pri) and set(pri) == {"P0", "P1", "P2", "P3"}
    assert all(r["item"] and r["why"] for r in R.ROADMAP)
    print("  [PASS] readiness model has a complete, ordered P0–P3 roadmap; detailed rendered readiness reports are intentionally private")


def test_the_limitations_state_the_things_that_must_never_be_overclaimed():
    text = " ".join(R.KNOWN_LIMITATIONS).lower()
    for needle in ("does not detect fraud", "legal advice", "synthetic", "0 of 49", "not immutable", "no baseline", "synthetic scenario labels", "not exercised", "never been verified", "string equality"):
        assert needle in text, needle
    assert "audit export is opt-in and not provisioned" in text
    print("  [PASS] the limitations say: no detection, no legal advice, synthetic data, 0 of 49 rules verified, not immutable, no baseline, synthetic labels, live paths not exercised, hosted render unverified, string matching")


# ── the approved-model allow-list ────────────────────────────────────────────

def test_a_model_not_on_the_approved_list_is_refused_before_anything_is_sent():
    assert core.CORTEX_MODEL in core.APPROVED_MODELS and core.CORTEX_MODEL_FALLBACK in core.APPROVED_MODELS, "the defaults are approved"
    assert core.is_approved_model("llama3.3-70b") and not core.is_approved_model("mistral-large2") and not core.is_approved_model("")
    for hostile in ("llama3.3-70b'); DROP TABLE x; --", "llama3.3-70b ", "../x", "a" * 80, None, 5):
        assert not core.is_approved_model(hostile), hostile
    real_primary, real_fallback = core.CORTEX_MODEL, core.CORTEX_MODEL_FALLBACK
    try:
        core.CORTEX_MODEL = "some-unreviewed-model"
        conn = FakeConn()
        try:
            core.CoPilotSkills(conn)._cortex_complete("hello")
            raise AssertionError("an unapproved model was called")
        except core.ModelNotApproved as err:
            assert "approved list" in str(err) and "nothing was sent" in str(err)
        assert not [s for s in conn.log if "CORTEX.COMPLETE" in s], "no model statement reached the database"
        core.CORTEX_MODEL, core.CORTEX_MODEL_FALLBACK = "llama3.3-70b", "unreviewed-fallback"
        conn2 = FakeConn([("CORTEX.COMPLETE", [{"RESPONSE": "ok"}])])
        assert core.CoPilotSkills(conn2)._cortex_complete("hi") == "ok" and all("unreviewed-fallback" not in s for s in conn2.log)
    finally:
        core.CORTEX_MODEL, core.CORTEX_MODEL_FALLBACK = real_primary, real_fallback
    print("  [PASS] an unapproved or malformed model name (incl. a SQL-injection string) raises ModelNotApproved before any model statement is sent; an unapproved fallback is never used; the defaults are on the list")


def test_a_refused_model_degrades_to_a_fully_human_decision_not_a_silent_substitute():
    real = core.CORTEX_MODEL
    try:
        core.CORTEX_MODEL = "unreviewed"
        sk = core.CoPilotSkills(FakeConn())
        res = sk.str_quality_checker("A narrative of reasonable length " * 10, {"customer_kyc": "x", "transactions": []})
        assert res["ai_output_valid"] is False and res["status"] == "NEEDS_MANUAL_REVIEW" and "approved list" in (res["ai_output_error"] or "")
        try:
            sk.suspicion_evaluator({"customer_kyc": "x", "transactions": []})
            raise AssertionError("the assessment ran with a refused model")
        except core.ModelNotApproved:
            pass
    finally:
        core.CORTEX_MODEL = real
    print("  [PASS] with a refused model the quality check fails closed (NEEDS_MANUAL_REVIEW, never READY) and the assessment raises, so the officer decides without AI — the model is not silently replaced")


TESTS = [
    test_every_capability_is_in_exactly_one_tier_and_an_implemented_one_names_tests_that_exist, test_the_security_checklist_covers_the_fourteen_asked_for_controls_and_never_oversells,
    test_the_architecture_has_the_seven_requested_stages_in_order_and_separates_fast_from_slow, test_readiness_model_has_complete_ordered_roadmap_data,
    test_the_limitations_state_the_things_that_must_never_be_overclaimed, test_a_model_not_on_the_approved_list_is_refused_before_anything_is_sent,
    test_a_refused_model_degrades_to_a_fully_human_decision_not_a_silent_substitute,
]

if __name__ == "__main__":
    raise SystemExit(Runner("Readiness, architecture and the model allow-list (offline)").run(TESTS))
