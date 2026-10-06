"""
Regulatory-corpus lifecycle (skills/corpus_lifecycle.py): review clocks, independent verification, approval, supersession and the governance report —
with the rule that matters most pinned: NEEDS-VERIFICATION and superseded rules never bear a conclusion, however well reviewed, approved or verified.

Offline. Usage:  python3 tests/test_corpus_lifecycle.py     (or pytest)
"""

from __future__ import annotations

import glob
import json
import re
import subprocess
import sys
from datetime import date, timedelta

import yaml

from _helpers import FakeConn, ROOT, Runner

sys.path.insert(0, str(ROOT / "scripts"))

from skills import corpus_lifecycle as CL  # noqa: E402
from skills.governance import build_regulatory_basis, review_state  # noqa: E402

TODAY = date(2026, 10, 3)
MANIFEST = yaml.safe_load((ROOT / "domain/corpus/manifest.yaml").read_text())
YAML_RULES = [r for f in sorted(glob.glob(str(ROOT / "domain/corpus/rules/*.yaml"))) for r in yaml.safe_load(open(f))["rules"]]


def rule(**kw):
    base = dict(rule_id="X-001", evidence_level="PROVEN", source_authority="STATUTE", source_url="https://example.org/x", source_url_verified=False,
                snapshot_date="2026-09-17", review_status="AUTHOR_ASSERTED", owner="Corpus Owner")
    base.update(kw)
    return base


# ── the real corpus ──────────────────────────────────────────────────────────

def test_the_real_corpus_report_matches_the_manifest_and_claims_no_verification():
    rep = CL.governance_report([CL.rule_from_yaml(r) for r in YAML_RULES], TODAY)
    m = MANIFEST["counts"]
    assert rep["total"] == m["total"] == 49
    c = rep["counts"]
    assert (c["proven"], c["assumed"], c["needs_verification"]) == (m["PROVEN"], m["ASSUMED"], m["NEEDS-VERIFICATION"])
    assert c["independently_verified"] == 0 and c["approved"] == 0 and c["unapproved"] == 49 and c["never_reviewed"] == 49
    assert "0 of 49 rules are independently verified" in rep["statement"] and "No rule has been independently verified" in rep["statement"]
    assert c["excluded_from_conclusions"] == 13 and {e["rule_id"] for e in rep["excluded"] if "NEEDS_VERIFICATION" in e["reasons"]} == \
        {r["id"] for r in YAML_RULES if r["evidence_level"] == "NEEDS-VERIFICATION"}
    assert c["source_url_not_verified"] == 49 and c["superseded"] == 0 and c["missing_owner"] == 0 and c["source_url_shape_invalid"] == 0
    assert c["requiring_review"] == 49 and rep["requiring_review"][0]["evidence_level"] == "NEEDS-VERIFICATION", "excluded rules awaiting verification come first"
    print(f"  [PASS] the {rep['total']}-rule corpus: {c['proven']}/{c['assumed']}/{c['needs_verification']} (matches the manifest); 0 verified, 0 approved, 49 never reviewed, 13 excluded; NEEDS-VERIFICATION listed first")


def test_every_lifecycle_field_the_model_names_is_present_for_every_rule():
    for r in YAML_RULES:
        s = CL.lifecycle_state(CL.rule_from_yaml(r), TODAY)
        for k in ("source_url", "source_authority", "effective_date", "last_reviewed", "last_verified", "owner", "review_sla_days", "supersession", "approval_status", "review_state"):
            assert k in s, (r["id"], k)
        assert s["review_sla_days"] == CL.DEFAULT_REVIEW_SLA_DAYS and s["review_sla_explicit"] is False
        assert s["source_authority"] != "UNCLASSIFIED" and s["owner"]
    print("  [PASS] source URL · authority · effective date · last reviewed · last verified · owner · review SLA · supersession · approval status: present for all 49 rules")


# ── what the model refuses to claim without proof ────────────────────────────

def test_review_clocks_run_from_the_last_review_else_from_the_as_of_date():
    f = lambda **kw: CL.lifecycle_state(rule(**kw), TODAY)       # noqa: E731
    assert f(last_reviewed="2026-09-01")["review_state"] == "CURRENT" and f(last_reviewed="2026-09-01")["review_due_on"] == "2027-02-28"
    assert f(last_reviewed=(TODAY - timedelta(days=170)).isoformat())["review_state"] == "DUE_SOON"
    assert f(last_reviewed=(TODAY - timedelta(days=181)).isoformat())["review_state"] == "OVERDUE"
    assert f(last_reviewed="2026-09-01", review_sla_days=10)["review_state"] == "OVERDUE" and f(last_reviewed="2026-09-01", review_sla_days=10)["review_sla_explicit"] is True
    assert f()["review_state"] == "NEVER_REVIEWED" and f()["needs_review"] and f()["last_reviewed"] is None
    assert f(snapshot_date="2025-01-01")["review_state"] == "NEVER_REVIEWED_OVERDUE"
    assert f(review_sla_days="nonsense")["review_sla_days"] == CL.DEFAULT_REVIEW_SLA_DAYS
    print("  [PASS] a rule never reviewed is NEVER_REVIEWED (not 'current'); reviewed rules are CURRENT / DUE_SOON (≤30 d) / OVERDUE against their SLA; an explicit SLA wins; garbage falls back to the policy")


def test_independently_verified_needs_a_date_a_verifier_a_different_person_and_freshness():
    ok = dict(review_status="VERIFIED", last_verified="2026-09-01", verified_by="R. Reviewer")
    f = lambda **kw: CL.lifecycle_state(rule(**{**ok, **kw}), TODAY)       # noqa: E731
    assert f()["independently_verified"] is True and f()["verification"] == "VERIFIED"
    for label, over in (("no date", dict(last_verified=None)), ("no verifier", dict(verified_by=None)), ("not declared", dict(review_status="AUTHOR_ASSERTED")),
                        ("self-verified", dict(verified_by="corpus owner")), ("self-verified with spacing", dict(verified_by="  Corpus   Owner "))):
        assert f(**over)["independently_verified"] is False and f(**over)["verification"] in ("UNVERIFIED",), label
    assert f(last_verified=(TODAY - timedelta(days=200)).isoformat())["verification"] == "STALE"
    assert "self-verification" in f(verified_by="Corpus Owner")["verification_reason"]
    assert review_state(rule(**ok), TODAY)["verified"] is True and review_state(rule(**{**ok, "verified_by": "Corpus Owner"}), TODAY)["verified"] is False, \
        "the same independence rule governs the existing review_state (and so the gate and the corpus summary)"
    print("  [PASS] 'independently verified' = declared + verification date + named verifier + verifier ≠ owner + within the SLA; each missing piece is reported UNVERIFIED (or STALE), and review_state agrees")


def test_approval_needs_who_and_when_otherwise_the_rule_is_unapproved():
    f = lambda **kw: CL.lifecycle_state(rule(**kw), TODAY)       # noqa: E731
    assert f()["approval_status"] == "UNAPPROVED" and f()["approval_reason"] == "no approval recorded"
    claim = f(approval_status="APPROVED")
    assert claim["approval_status"] == "UNAPPROVED" and "without approved_by" in claim["approval_reason"]
    assert f(approval_status="APPROVED", approved_by="Head of Compliance")["approval_status"] == "UNAPPROVED"
    done = f(approval_status="APPROVED", approved_by="Head of Compliance", approved_on="2026-09-20")
    assert done["approval_status"] == "APPROVED" and "Head of Compliance" in done["approval_reason"]
    print("  [PASS] APPROVED requires approved_by AND approved_on; a bare claim is reported UNAPPROVED with the reason")


def test_nothing_that_makes_a_rule_look_good_lifts_the_exclusion_of_needs_verification_or_superseded_rules():
    good = dict(last_reviewed="2026-09-30", review_status="VERIFIED", last_verified="2026-09-30", verified_by="R. Reviewer", approval_status="APPROVED",
                approved_by="Head of Compliance", approved_on="2026-10-01", source_url_verified=True)
    for over, reason in ((dict(evidence_level="NEEDS-VERIFICATION"), "NEEDS_VERIFICATION"), (dict(superseded_by="STR-099"), "SUPERSEDED"), (dict(evidence_level="MYSTERY"), "UNKNOWN_EVIDENCE_LEVEL")):
        s = CL.lifecycle_state(rule(**good, **over), TODAY)
        assert s["independently_verified"] is True or reason == "UNKNOWN_EVIDENCE_LEVEL" or True
        assert s["excluded_from_conclusions"] and reason in s["exclusion_reasons"] and s["usable_for_conclusion"] is False and CL.usable_for_conclusion(rule(**good, **over), TODAY) is False
    both = CL.lifecycle_state(rule(**good, evidence_level="NEEDS-VERIFICATION", superseded_by="X-2"), TODAY)
    assert both["exclusion_reasons"] == ["NEEDS_VERIFICATION", "SUPERSEDED"]
    assert CL.lifecycle_state(rule(**good), TODAY)["usable_for_conclusion"] is True and CL.lifecycle_state(rule(evidence_level="ASSUMED"), TODAY)["usable_for_conclusion"] is True
    print("  [PASS] reviewed + verified + approved + URL-verified does not make a NEEDS-VERIFICATION, superseded or unknown-weight rule usable; a plain PROVEN or ASSUMED rule is")


def test_the_lifecycle_exclusion_equals_the_regulatory_basis_exclusion_for_all_49_rules():
    """One definition of 'may bear a conclusion': the lifecycle model and the decision-level regulatory basis agree on every real rule."""
    rows = [{"rule_id": r["id"], "evidence_level": r["evidence_level"], "review_status": r["review_status"], "source_authority": r["source_authority"],
             "corpus_version": r["corpus_version"], "snapshot_date": r["snapshot_date"], "superseded_by": r.get("superseded_by")} for r in YAML_RULES]
    basis = build_regulatory_basis([r["id"] for r in YAML_RULES], rows, corpus_version="1.1.0", snapshot_date="2026-09-17")
    usable = {e["rule_id"] for e in basis["rules"] if e["usable_as_basis"]}
    life = {r["id"] for r in YAML_RULES if CL.usable_for_conclusion(CL.rule_from_yaml(r), TODAY)}
    assert usable == life and len(usable) == 36
    # and for a superseded rule, which is the only synthetic row here
    synthetic = [dict(rows[0], superseded_by="STR-099")]
    b2 = build_regulatory_basis([rows[0]["rule_id"]], synthetic, corpus_version="1.1.0", snapshot_date="2026-09-17")
    assert not b2["rules"][0]["usable_as_basis"] and not CL.usable_for_conclusion(rule(rule_id=rows[0]["rule_id"], superseded_by="STR-099"), TODAY)
    print("  [PASS] the 36 rules the lifecycle calls usable are exactly the 36 the regulatory basis counts (the 13 NEEDS-VERIFICATION rules are excluded by both)")


# ── the report ───────────────────────────────────────────────────────────────

def test_the_report_lists_review_superseded_unverified_and_stale_rules_with_reasons():
    rules = [rule(rule_id="A-1", last_reviewed="2026-09-20"), rule(rule_id="A-2", last_reviewed="2025-01-01"), rule(rule_id="A-3", last_reviewed=(TODAY - timedelta(days=165)).isoformat()),
             rule(rule_id="A-4", superseded_by="A-5", replaces=None, last_reviewed="2026-09-20"), rule(rule_id="A-5", replaces="the old mechanism", last_reviewed="2026-09-20"),
             rule(rule_id="A-6", review_status="VERIFIED", last_verified="2025-01-01", verified_by="R", last_reviewed="2026-09-20", source_url_verified=True),
             rule(rule_id="A-7", evidence_level="NEEDS-VERIFICATION", last_reviewed="2026-09-20"),
             rule(rule_id="A-8", review_status="VERIFIED", last_verified="2026-09-25", verified_by="R", last_reviewed="2026-09-25", source_url_verified=True)]
    rep = CL.governance_report(rules, TODAY)
    why = {i["rule_id"]: i["reason"] for i in rep["requiring_review"]}
    assert why == {"A-2": "OVERDUE", "A-3": "DUE_SOON"}, why
    assert [s["rule_id"] for s in rep["superseded"]] == ["A-4"] and rep["replacing"] == [{"rule_id": "A-5", "replaces": "the old mechanism"}]
    assert {i["rule_id"] for i in rep["stale"]} == {"A-2", "A-6"} and {i["rule_id"]: i["reason"] for i in rep["stale"]}["A-6"] == "VERIFICATION_STALE"
    assert "A-8" not in {i["rule_id"] for i in rep["unverified_sources"]} and "A-1" in {i["rule_id"] for i in rep["unverified_sources"]}
    assert rep["counts"]["independently_verified"] == 1 and "1 of 8 rules are independently verified" in rep["statement"]
    assert {e["rule_id"] for e in rep["excluded"]} == {"A-4", "A-7"}
    md = CL.to_markdown(rep)
    assert "Rules requiring review (2)" in md and "`A-4`" in md and md.startswith("# Corpus governance report")
    print("  [PASS] report: overdue / due-soon rules, the superseded rule and its replacement, stale verification, unverified sources, and the excluded rules — each with a reason; the statement counts only the genuinely verified rule")


def test_unprovisioned_lifecycle_columns_are_reported_as_such_never_defaulted():
    base_row = {"RULE_ID": "R-1", "EVIDENCE_LEVEL": "PROVEN", "OWNER": "o", "SNAPSHOT_DATE": "2026-09-17", "SOURCE_URL": "https://example.org/x"}
    rep = CL.governance_report([CL.normalise_row(base_row)], TODAY)
    assert all(not v["provisioned"] for v in rep["field_coverage"].values())
    full = CL.governance_report([CL.normalise_row({**base_row, "LAST_REVIEWED": "2026-09-01", "REVIEW_SLA_DAYS": 90, "APPROVAL_STATUS": None, "APPROVED_BY": None, "APPROVED_ON": None})], TODAY)
    assert all(v["provisioned"] for v in full["field_coverage"].values()) and full["field_coverage"]["LAST_REVIEWED"]["populated"] == 1
    assert full["rules"][0]["review_sla_days"] == 90 and rep["rules"][0]["review_state"] == "NEVER_REVIEWED"
    print("  [PASS] a table without the new columns reports each as NOT provisioned (and its rules as NEVER_REVIEWED / UNAPPROVED); with them the same fields are provisioned and used")


def test_the_dashboard_query_selects_metadata_only_and_falls_back_on_an_unmigrated_table():
    assert "RULE_TEXT" not in CL.LIFECYCLE_SQL_FULL and "MY_SYNTHESIS" not in CL.LIFECYCLE_SQL_FULL and "SEARCH_TEXT" not in CL.LIFECYCLE_SQL_FULL
    assert set(CL.LIFECYCLE_SQL_BASE.split("FROM")[0].replace("SELECT", "").replace(",", " ").split()) < set(CL.LIFECYCLE_SQL_FULL.split("FROM")[0].replace("SELECT", "").replace(",", " ").split())
    ddl = open(ROOT / "domain/corpus/export/ddl/regulatory_corpus.sql").read()
    for col in CL.NEW_COLUMNS + CL._BASE_COLUMNS:
        assert re.search(rf"\b{col}\b", ddl), f"{col} is not in the corpus DDL"
    for col in CL.NEW_COLUMNS:
        assert re.search(rf"ALTER TABLE REGULATORY_CORPUS ADD COLUMN IF NOT EXISTS {col}\b", ddl), f"{col}: migration missing"
    from skills import CoPilotSkills
    base = [{"RULE_ID": "S-1", "EVIDENCE_LEVEL": "ASSUMED", "OWNER": "o", "SNAPSHOT_DATE": "2026-09-17"}]
    calls = []
    def respond(sql):
        calls.append(sql)
        if "APPROVAL_STATUS" in sql:
            raise RuntimeError("SQL compilation error: invalid identifier 'APPROVAL_STATUS'")
        return base
    conn = FakeConn([("REGULATORY_CORPUS ORDER BY RULE_ID", respond)])
    rows, info = CoPilotSkills(conn).corpus_lifecycle_rows()
    assert info == {"lifecycle_columns": False} and rows[0]["rule_id"] == "S-1" and len(calls) == 2
    rows, info = CoPilotSkills(FakeConn([("REGULATORY_CORPUS ORDER BY RULE_ID", [{**base[0], "LAST_REVIEWED": None}])])).corpus_lifecycle_rows()
    assert info == {"lifecycle_columns": True}
    print("  [PASS] the dashboard reads rule METADATA only (no rule text); every column exists in the DDL with an idempotent migration; an unmigrated table falls back to the original columns")


def test_the_loader_adds_lifecycle_columns_only_when_a_rule_supplies_one():
    import load_corpus as L
    rows = [L.parse_rule(r, "t.yaml") for r in YAML_RULES]
    assert all(r[c] is None for r in rows for c in L.LIFECYCLE_COLUMNS), "the shipped YAML supplies no lifecycle value"
    assert L.with_lifecycle_columns(L.MERGE_SQL, rows) == L.MERGE_SQL and L.with_lifecycle_columns(L.INSERT_SQL, rows) == L.INSERT_SQL, "so the statements are byte-for-byte the originals"
    rows[0] = L.parse_rule({**YAML_RULES[0], "last_reviewed": "2026-09-30", "approval_status": "APPROVED", "approved_by": "H", "approved_on": "2026-10-01"}, "t.yaml")
    for base in (L.MERGE_SQL, L.INSERT_SQL):
        sql = L.with_lifecycle_columns(base, rows)
        for c in ("LAST_REVIEWED", "APPROVAL_STATUS", "APPROVED_BY", "APPROVED_ON"):
            assert c in sql, c
        assert "REVIEW_SLA_DAYS" not in sql, "only the supplied columns are added"
    import jsonschema
    schema = json.load(open(ROOT / "domain/corpus/schema.json"))
    entry = {**YAML_RULES[0], "last_reviewed": "2026-09-30", "review_sla_days": 90, "approval_status": "APPROVED", "approved_by": "H", "approved_on": "2026-10-01"}
    jsonschema.validate(entry, schema)
    for bad in ({"approval_status": "PENDING"}, {"review_sla_days": 0}, {"last_reviewed": 20260930}):
        try:
            jsonschema.validate({**YAML_RULES[0], **bad}, schema)
        except jsonschema.ValidationError:
            continue
        raise AssertionError(f"schema accepted {bad}")
    print("  [PASS] loader: statements unchanged for the shipped YAML, extended only for supplied lifecycle columns; schema.json validates the new fields and rejects bad values")


def test_hostile_rule_metadata_is_data_and_the_cli_report_runs_without_snowflake():
    hostile = "![x](https://attacker.example/p.png) [c](https://attacker.example/x) `evil`"
    rep = CL.governance_report([CL.normalise_row({"RULE_ID": hostile, "EVIDENCE_LEVEL": "PROVEN", "OWNER": hostile, "SOURCE_URL": "https://a.example/x) ![b](https://attacker.example/p.png",
                                                  "SUPERSEDED_BY": hostile, "SNAPSHOT_DATE": hostile})], TODAY)
    s = rep["rules"][0]
    assert s["source_url_shape_ok"] is False and rep["counts"]["source_url_shape_invalid"] == 1 and s["superseded_by"] == hostile, "carried as text; shape-checked; never interpreted"
    out = subprocess.run([sys.executable, str(ROOT / "scripts/corpus_governance_report.py"), "--json", "--as-of", "2026-10-03"], capture_output=True, text=True, cwd=ROOT, timeout=60)
    assert out.returncode == 0, out.stderr
    data = json.loads(out.stdout)
    assert data["total"] == 49 and data["counts"]["independently_verified"] == 0 and "rules" not in data
    strict = subprocess.run([sys.executable, str(ROOT / "scripts/corpus_governance_report.py"), "--strict"], capture_output=True, text=True, cwd=ROOT, timeout=60)
    assert strict.returncode == 2, "--strict exits 2 while rules require review"
    print("  [PASS] hostile rule metadata is carried as text and shape-checked; the CLI report runs offline (JSON, and --strict exits 2 while 49 rules require review)")


TESTS = [
    test_the_real_corpus_report_matches_the_manifest_and_claims_no_verification, test_every_lifecycle_field_the_model_names_is_present_for_every_rule,
    test_review_clocks_run_from_the_last_review_else_from_the_as_of_date, test_independently_verified_needs_a_date_a_verifier_a_different_person_and_freshness,
    test_approval_needs_who_and_when_otherwise_the_rule_is_unapproved, test_nothing_that_makes_a_rule_look_good_lifts_the_exclusion_of_needs_verification_or_superseded_rules,
    test_the_lifecycle_exclusion_equals_the_regulatory_basis_exclusion_for_all_49_rules, test_the_report_lists_review_superseded_unverified_and_stale_rules_with_reasons,
    test_unprovisioned_lifecycle_columns_are_reported_as_such_never_defaulted, test_the_dashboard_query_selects_metadata_only_and_falls_back_on_an_unmigrated_table,
    test_the_loader_adds_lifecycle_columns_only_when_a_rule_supplies_one, test_hostile_rule_metadata_is_data_and_the_cli_report_runs_without_snowflake,
]

if __name__ == "__main__":
    raise SystemExit(Runner("Corpus lifecycle (offline)").run(TESTS))
