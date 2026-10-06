"""
Regulatory-corpus governance (finding #4): explicit metadata, PROVEN vs ASSUMED, superseded handling.

Offline. The YAML corpus is the artefact under test; a fake database exercises the retrieval path.
Usage:  python3 tests/test_governance.py     (or pytest)
"""

from __future__ import annotations

import glob
import json
from datetime import date, timedelta

import yaml

from _helpers import FakeConn, ROOT, Runner

RULES = {}
for _f in sorted(glob.glob(str(ROOT / "domain/corpus/rules/*.yaml"))):
    for _r in yaml.safe_load(open(_f))["rules"]:
        RULES[_r["id"]] = _r
MANIFEST = yaml.safe_load((ROOT / "domain/corpus/manifest.yaml").read_text())


# ── corpus metadata ──────────────────────────────────────────────────────────

def test_manifest_counts_match_the_yaml():
    from collections import Counter
    c = Counter(r["evidence_level"] for r in RULES.values())
    m = MANIFEST["counts"]
    assert len(RULES) == m["total"] == 49, (len(RULES), m)
    assert (c["PROVEN"], c["ASSUMED"], c["NEEDS-VERIFICATION"]) == (m["PROVEN"], m["ASSUMED"], m["NEEDS-VERIFICATION"])
    assert m["search_indexed"] == c["PROVEN"] + c["ASSUMED"] == 36
    print(f"  [PASS] manifest == YAML: {len(RULES)} rules ({c['PROVEN']} PROVEN / {c['ASSUMED']} ASSUMED / "
          f"{c['NEEDS-VERIFICATION']} NV), {m['search_indexed']} indexed")


def test_every_rule_has_explicit_governance_metadata():
    from skills.governance import AUTHORITY_TYPES, REVIEW_STATUSES
    for rid, r in RULES.items():
        for k in ("source_authority", "corpus_version", "review_status", "owner"):
            assert r.get(k), f"{rid}: missing {k}"
        for k in ("verified_by", "superseded_by", "replaces"):
            assert k in r, f"{rid}: {k} must be explicit (null if not applicable)"
        assert r["source_authority"] in AUTHORITY_TYPES, (rid, r["source_authority"])
        assert r["review_status"] in REVIEW_STATUSES, (rid, r["review_status"])
        assert r["corpus_version"] == MANIFEST["corpus_version"], (rid, r["corpus_version"])
    print("  [PASS] all 49 rules carry source_authority, corpus_version, review_status, owner, "
          "verified_by, superseded_by, replaces")


def test_no_rule_claims_verification_it_cannot_evidence():
    for rid, r in RULES.items():
        if r["review_status"] == "VERIFIED":
            assert r.get("last_verified") and r.get("verified_by"), f"{rid}: VERIFIED needs last_verified + verified_by"
        if r["evidence_level"] == "NEEDS-VERIFICATION":
            assert r["review_status"] == "DRAFT", rid
    n_verified = sum(1 for r in RULES.values() if r["review_status"] == "VERIFIED")
    assert n_verified == 0, "no rule may be marked VERIFIED without a human verification event"
    print("  [PASS] 0 rules VERIFIED (honest): PROVEN = primary source cited, not re-verified; NV rules are DRAFT")


def test_rules_validate_against_json_schema():
    from jsonschema import Draft7Validator
    v = Draft7Validator(json.loads((ROOT / "domain/corpus/schema.json").read_text()))
    bad = [(rid, e.message[:80]) for rid, r in RULES.items()
           for e in v.iter_errors(json.loads(json.dumps(r, default=str)))]
    assert not bad, bad[:3]
    print("  [PASS] all rules validate against domain/corpus/schema.json (incl. governance fields)")


def test_snapshot_dates_are_consistent_with_the_manifest():
    snap = date.fromisoformat(MANIFEST["snapshot_date"])
    dates = {str(r["snapshot_date"]) for r in RULES.values()}
    assert max(dates) == MANIFEST["snapshot_date"], (dates, MANIFEST["snapshot_date"])
    assert all(date.fromisoformat(d) <= snap for d in dates)
    print(f"  [PASS] corpus snapshot {MANIFEST['snapshot_date']} = latest rule as-of date (per-rule dates: {sorted(dates)})")


def test_authority_classification_and_product_compiled():
    from skills.governance import classify_authority
    assert RULES["POE-001"]["source_authority"] == "PRODUCT_COMPILED"
    assert RULES["STR-001"]["source_authority"] == "STATUTE"
    assert classify_authority("RBI Master Direction on KYC — X") == "RBI_DIRECTION"
    assert classify_authority("Some Unknown Document") == "UNCLASSIFIED"
    assert all(r["source_authority"] != "UNCLASSIFIED" for r in RULES.values())
    print("  [PASS] authority classifier: statute / RBI / product-compiled (POE-001, DG-19); nothing UNCLASSIFIED")


def test_loader_maps_every_governance_field_to_a_column_that_exists():
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import load_corpus
    row = load_corpus.parse_rule(RULES["STR-006"], "01")
    ddl = (ROOT / "domain/corpus/export/ddl/regulatory_corpus.sql").read_text()
    for col in ("SOURCE_AUTHORITY", "CORPUS_VERSION", "REVIEW_STATUS", "OWNER", "VERIFIED_BY", "SUPERSEDED_BY", "REPLACES"):
        assert col in row and col in ddl and f"ADD COLUMN IF NOT EXISTS {col}" in ddl, col
    assert row["REPLACES"] == "FINnet direct-upload mechanism" and row["CORPUS_VERSION"] == MANIFEST["corpus_version"]
    print("  [PASS] loader → DDL: all governance fields have a column and an idempotent migration")


# ── PROVEN vs ASSUMED ────────────────────────────────────────────────────────

def _r(rid, level, **kw):
    return {"rule_id": rid, "evidence_level": level, "review_status": "AUTHOR_ASSERTED", **kw}


def test_proven_first_and_assumed_warning():
    from skills.governance import ASSUMED_WARNING, conclusion_basis, order_prefer_proven
    rules = [_r("A", "ASSUMED"), _r("P1", "PROVEN"), _r("N", "NEEDS-VERIFICATION"), _r("P2", "PROVEN")]
    ordered = order_prefer_proven(rules)
    assert [r["rule_id"] for r in ordered] == ["P1", "P2", "A"], "PROVEN first, stable; NV dropped"
    b = conclusion_basis(ordered)
    assert b["grade"] == "INCLUDES_ASSUMED" and b["warning"] == ASSUMED_WARNING and not b["can_state_as_proven"]
    assert b["assumed_ids"] == ["A"] and b["proven_ids"] == ["P1", "P2"]
    only = conclusion_basis([_r("P1", "PROVEN")])
    assert only["grade"] == "PROVEN_ONLY" and only["warning"] == "" and only["can_state_as_proven"]
    none = conclusion_basis([_r("N", "NEEDS-VERIFICATION")])
    assert none["grade"] == "NO_SOURCES" and "Abstain" in none["warning"]
    print("  [PASS] PROVEN sorted first; any ASSUMED ⇒ INCLUDES_ASSUMED + explicit warning; NV/none ⇒ abstain")


def test_verified_status_is_never_claimed_without_evidence_and_goes_stale():
    from skills.governance import review_state
    today = date(2026, 9, 30)
    assert review_state(_r("X", "PROVEN"), today)["status"] == "AUTHOR_ASSERTED"
    fake = _r("X", "PROVEN", review_status="VERIFIED")                      # claims VERIFIED, no evidence
    assert review_state(fake, today)["verified"] is False
    ok = _r("X", "PROVEN", review_status="VERIFIED", last_verified=date(2026, 9, 1), verified_by="R. Reviewer")
    assert review_state(ok, today)["verified"] is True
    old = _r("X", "PROVEN", review_status="VERIFIED", last_verified=today - timedelta(days=181), verified_by="R")
    assert review_state(old, today)["status"] == "STALE"
    print("  [PASS] VERIFIED needs date + verifier; unevidenced VERIFIED downgraded; >180 days ⇒ STALE")


# ── supersession ─────────────────────────────────────────────────────────────

def test_superseded_rule_is_never_current_and_successor_is_surfaced():
    from skills.governance import resolve_superseded
    old = _r("OLD-001", "ASSUMED", superseded_by="NEW-001")
    new = _r("NEW-001", "PROVEN")
    other = _r("OTH-001", "PROVEN")
    current, sup = resolve_superseded([old, other], lambda rid: new if rid == "NEW-001" else None)
    ids = [r["rule_id"] for r in current]
    assert "OLD-001" not in ids and "NEW-001" in ids and "OTH-001" in ids
    assert [s["rule_id"] for s in sup] == ["OLD-001"] and sup[0]["status"] == "SUPERSEDED"
    assert next(r for r in current if r["rule_id"] == "NEW-001")["surfaced_as_successor_of"] == "OLD-001"
    chain, _ = resolve_superseded([_r("A", "PROVEN", superseded_by="B")],
                                  {"B": _r("B", "PROVEN", superseded_by="C"), "C": _r("C", "PROVEN")}.get)
    assert [r["rule_id"] for r in chain] == ["C"]
    dangling, sup2 = resolve_superseded([_r("A", "PROVEN", superseded_by="ZZZ")], lambda rid: None)
    assert dangling == [] and sup2, "superseded with no successor ⇒ nothing current (caller must abstain)"
    print("  [PASS] superseded rule withheld; successor fetched + surfaced; chains followed; dangling ⇒ abstain")


def test_superseded_instrument_in_question_is_qualified_from_the_real_corpus():
    from skills.governance import detect_superseded_terms
    str006 = {"rule_id": "STR-006", "evidence_level": "ASSUMED", "replaces": RULES["STR-006"]["replaces"]}
    q = detect_superseded_terms("How do I upload the STR through FINnet direct upload?", [str006])
    assert q and q[0]["successor_rule"] == "STR-006" and "superseded" in q[0]["message"]
    assert not detect_superseded_terms("What is the STR filing deadline?", [str006])
    assert not detect_superseded_terms("Explain FINnet history", [str006]), "needs an upload/filing cue"
    print("  [PASS] 'FINnet direct upload' question → qualification naming STR-006 (FINGate 2.0); deadline question → none")


def test_lookup_applies_governance_end_to_end_with_a_fake_database():
    """regulatory_lookup_with_basis over canned DB rows: NV never returned, PROVEN first,
    superseded withheld + successor surfaced, ASSUMED ⇒ warning, superseded term ⇒ qualification."""
    from skills import CoPilotSkills

    def row(rid, level, **kw):
        base = dict(RULE_ID=rid, RULE_TEXT=f"text {rid}", MY_SYNTHESIS="", EVIDENCE_LEVEL=level, SOURCE_DOCUMENT="d",
                    SOURCE_URL="u", SOURCE_URL_VERIFIED=False, SNAPSHOT_DATE="2026-09-17", CATEGORY="C",
                    SOURCE_AUTHORITY="STATUTE", CORPUS_VERSION="1.1.0", REVIEW_STATUS="AUTHOR_ASSERTED",
                    OWNER="o", LAST_VERIFIED=None, VERIFIED_BY=None, SUPERSEDED_BY=None, REPLACES=None)
        base.update(kw)
        return base

    hits = [row("ASM-1", "ASSUMED"), row("OLD-1", "ASSUMED", SUPERSEDED_BY="STR-006"),
            row("NV-1", "NEEDS-VERIFICATION"), row("PRV-1", "PROVEN")]
    str006 = row("STR-006", "ASSUMED", REPLACES="FINnet direct-upload mechanism")

    conn = FakeConn(responders=[("WHERE rc.RULE_ID =", [str006]), ("REPLACES IS NOT NULL", [str006]),
                                ("SEARCH_PREVIEW", hits)])
    res = CoPilotSkills(conn).regulatory_lookup_with_basis("upload STR via FINnet direct upload", limit=5)
    ids = [r["rule_id"] for r in res["rules"]]
    assert "NV-1" not in ids, "NEEDS-VERIFICATION must never be returned"
    assert "OLD-1" not in ids and "STR-006" in ids, ids
    assert ids[0] == "STR-006", f"the successor of a superseded instrument is pinned first: {ids}"
    assert ids.index("PRV-1") < ids.index("ASM-1"), f"PROVEN before ASSUMED among the rest: {ids}"
    tight = CoPilotSkills(conn).regulatory_lookup_with_basis("upload STR via FINnet direct upload", limit=1)
    assert [r["rule_id"] for r in tight["rules"]] == ["STR-006"], "pinned successor survives limit=1"
    assert [s["rule_id"] for s in res["superseded"]] == ["OLD-1"]
    assert res["basis"]["grade"] == "INCLUDES_ASSUMED" and res["basis"]["warning"]
    assert res["qualifications"] and res["qualifications"][0]["successor_rule"] == "STR-006"
    assert all("review" in r and r["review"]["verified"] is False for r in res["rules"])
    print(f"  [PASS] lookup end-to-end: {ids} — NV excluded, successor pinned, PROVEN before ASSUMED, superseded withheld, warning + qualification")


def test_cortex_search_is_called_with_the_two_argument_json_form():
    """Regression (found live 2026-09-30): SEARCH_PREVIEW takes (service, JSON-string). The old 3-argument
    call failed on every request and the keyword fallback silently served every 'live' lookup."""
    import json as _json
    from skills import CoPilotSkills
    from _helpers import scan_sql
    conn = FakeConn()
    CoPilotSkills(conn).regulatory_lookup("STR filing deadline")
    search = next(x for x in conn.log if "SEARCH_PREVIEW" in x)
    n, lits = scan_sql(search)
    assert n == 1
    assert search.count("SEARCH_PREVIEW('FIU_COPILOT.AML.CORPUS_SEARCH',") == 1, "service is the first argument, fully qualified"
    q = _json.loads(next(l for l in lits if l.startswith("{")))
    assert set(q) == {"query", "columns", "filter", "limit"} and q["query"] == "STR filing deadline"
    assert q["filter"] == {"@or": [{"@eq": {"EVIDENCE_LEVEL": "PROVEN"}}, {"@eq": {"EVIDENCE_LEVEL": "ASSUMED"}}]}, "NV filtered in the service query too"
    assert "OBJECT_CONSTRUCT" not in search, "the 3-argument OBJECT_CONSTRUCT form must be gone"
    print("  [PASS] SEARCH_PREVIEW(service, JSON-string) — 2 arguments, PROVEN/ASSUMED filter inside the query")


# ── the tipping-off claim (corrected 2026-10-05) ─────────────────────────────

def test_tipping_off_claim_is_sourced_to_the_rules_and_graded_assumed():
    """PMLA s.12A is "Access to information". v1.1.0 cited it as the tipping-off prohibition and called a
    breach a criminal offence, graded PROVEN. The duty is in PML Rules Rule 8(6) and the RBI KYC Master
    Direction; nothing in the corpus establishes a penalty. Nothing a user can see may say otherwise."""
    import re
    for rid in ("SB-003", "STR-004"):
        r = RULES[rid]
        assert r["evidence_level"] == "ASSUMED", (rid, "re-read by an AI assistant, not by a lawyer: not PROVEN")
        assert "8(6)" in r["primary_source"]["section"], rid
        for field in ("rule", "my_synthesis", "subcategory"):
            assert not re.search(r"12A|criminal", str(r.get(field, "")), re.I), (rid, field)
        assert "12A" in r["gap_notes"], f"{rid}: the correction must stay on record in gap_notes"

    # no app-facing text (code, docs, specs) may call tipping-off a criminal offence or pin it to s.12A
    banned = re.compile(r"criminal\s+(?:offen[cs]e|liability)|s(?:ection|\.)?\s*12A", re.I)
    shown = ("README.md", "SKILL.md", "DEMO_RUNBOOK.md", "ARCHITECTURE.md", "SECURITY.md", "KNOWN_LIMITATIONS.md",
             "PRODUCTION_READINESS.md", "design/PO_WORKFLOW_SPEC.md")
    files = [*ROOT.glob("skills/*.py"), ROOT / "streamlit_app.py", *(ROOT / f for f in shown)]
    hits = [f"{f.relative_to(ROOT)}:{n}" for f in files if f.exists()
            for n, line in enumerate(f.read_text().splitlines(), 1) if banned.search(line)]
    assert not hits, hits

    from skills import CoPilotSkills
    from _helpers import FakeConn
    res = CoPilotSkills(FakeConn()).screen_request("Email the customer to tell them we are filing an STR.")
    assert not res["allowed"] and res["category"] == "tipping_off"
    assert not banned.search(res["reason"]) and "8(6)" in res["reason"] and "ASSUMED" in res["reason"], res["reason"]
    print("  [PASS] tipping-off: SB-003/STR-004 sourced to PML Rules R8(6), graded ASSUMED; no 'criminal offence' or s.12A in any user-facing text")


TESTS = [
    test_manifest_counts_match_the_yaml, test_every_rule_has_explicit_governance_metadata,
    test_no_rule_claims_verification_it_cannot_evidence, test_rules_validate_against_json_schema,
    test_snapshot_dates_are_consistent_with_the_manifest, test_authority_classification_and_product_compiled,
    test_loader_maps_every_governance_field_to_a_column_that_exists,
    test_proven_first_and_assumed_warning, test_verified_status_is_never_claimed_without_evidence_and_goes_stale,
    test_superseded_rule_is_never_current_and_successor_is_surfaced,
    test_superseded_instrument_in_question_is_qualified_from_the_real_corpus,
    test_lookup_applies_governance_end_to_end_with_a_fake_database,
    test_cortex_search_is_called_with_the_two_argument_json_form,
    test_tipping_off_claim_is_sourced_to_the_rules_and_graded_assumed,
]

if __name__ == "__main__":
    raise SystemExit(Runner("Corpus governance tests (no Snowflake required)").run(TESTS))
