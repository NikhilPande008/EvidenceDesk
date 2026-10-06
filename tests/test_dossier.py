"""
The inspection pack (skills/dossier.py): a decision as a file that can be checked without the application or Snowflake.

  * the Python reproduction of the ledger's SQL row hash is checked against real ledger rows (the three decisions committed in the first clean room);
  * a dossier built from a decision the real recorder wrote verifies end to end, offline;
  * every kind of tampering is caught by the check that is meant to catch it, and re-sealing an edited file does NOT hide an edited decision row;
  * the printable page escapes everything, and carries no script and no external resource.

Offline. Usage:  python3 tests/test_dossier.py     (or pytest)
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone

from _helpers import FakeConn, HOSTILE_STRINGS, ROOT, Runner, case_context, recorder_kwargs

REAL_ROWS = ROOT / "evidence" / "cleanroom-2026-10-02" / "ledger-rows-for-offline-hash-check.json"
WHEN = datetime(2026, 10, 5, 12, 0, 0, 123456, tzinfo=timezone.utc)


def test_sf_json_matches_the_serialisation_snowflake_was_observed_to_use():
    from skills.dossier import sf_json
    # Observed on the live account (TO_JSON(OBJECT_CONSTRUCT_KEEP_NULL(...)) on a nested VARIANT): keys sorted at every level, compact, UTF-8 kept,
    # 1.50 -> 1.5, strings escaped as JSON. This literal is the account's own output.
    live = ('{"a":2,"m":null,"n":{"b":[3,1,{"c":null,"q":true}],"s":"a\\"b\\\\c\\n","t":0.30000000000000004,"y":1.5,"é":"ü ₹ 😀"},'
            '"t":"2026-09-29T21:35:11.123456","z":1}')
    value = {"z": 1, "a": 2, "m": None, "n": {"y": 1.50, "b": [3, 1, {"q": True, "c": None}], "é": "ü ₹ 😀", "s": 'a"b\\c\n', "t": 0.1 + 0.2},
             "t": "2026-09-29T21:35:11.123456"}
    assert sf_json(value) == live
    assert sf_json({"f": 98.80, "i": 5, "sla": 7, "arr": ["b", "a"]}) == '{"arr":["b","a"],"f":98.8,"i":5,"sla":7}'
    assert sf_json(84.0) == "84" and sf_json(True) == "true" and sf_json([]) == "[]" and sf_json({}) == "{}" and sf_json(float("nan")) == "null"
    print("  [PASS] sf_json reproduces the live account's TO_JSON output: sorted keys, compact, UTF-8, 1.50 -> 1.5, 84.0 -> 84")


def test_the_python_row_hash_equals_the_hash_the_ledger_computed_in_sql_for_every_real_row():
    from skills.dossier import row_hash
    if not REAL_ROWS.is_file():
        print("  [SKIP] the recorded ledger rows are not in this checkout")
        return
    rows = json.loads(REAL_ROWS.read_text())["rows"]
    assert len(rows) == 3
    for r in rows:
        assert row_hash(r["row"]) == r["row_hash"], r["row"]["decision_id"]
        assert len(json.dumps(r["row"]["metadata"])) > 3000, "these are full provenance rows, not toy rows"
    edited = copy.deepcopy(rows[0])
    edited["row"]["rationale_text"] += " "
    assert row_hash(edited["row"]) != edited["row_hash"]
    print("  [PASS] 3 of 3 real ledger rows (5 to 6 KB of provenance each): the hash recomputed in Python equals the SQL hash; one added space breaks it")


_CACHE: dict = {}


def _recorded_file_decision():
    """A FILE decision written by the real recorder (FakeConn: the SQL is not run), then assembled into the reconstruction shape the dossier is built from.
    Built once per process: the decision id is a fresh UUID, and a Streamlit rerun must see the same decision."""
    if "built" not in _CACHE:
        _CACHE["built"] = _build_recorded_file_decision()
    return copy.deepcopy(_CACHE["built"])


def _build_recorded_file_decision():
    from skills import CoPilotSkills, dossier as D
    from _helpers import factors_json
    kw = recorder_kwargs()
    result = CoPilotSkills(FakeConn()).alert_disposition_recorder(**kw)
    meta = json.loads(json.dumps(result["provenance"]))
    meta.update(written_by_role="FIU_APP_ROLE", written_by_user="TEST_USER")        # the INSERT stamps these two in SQL, after the recorder built the rest
    ctx = kw["case_context"]
    decision = {"DECISION_ID": result["decision_id"], "ALERT_ID": kw["alert_id"], "CUSTOMER_REF": kw["customer_ref"], "DISPOSITION": "FILE", "DECISION_MAKER_ID": kw["decision_maker_id"],
                "SUSPICION_FORMED_AT": WHEN, "DECISION_MADE_AT": WHEN, "SLA_DAYS_REMAINING": result["sla_days_remaining"], "RATIONALE_TEXT": kw["rationale_text"].strip(),
                "RULES_CITED": json.dumps(kw["rules_cited"]), "POE_FACTORS_ASSESSED": json.dumps({f["factor_id"]: f["assessment"] for f in json.loads(factors_json())}),
                "RFI_TRIGGERS": json.dumps(kw["rfi_triggers"]), "STR_REFERENCE": "PENDING-FINGATEREF", "INTEGRITY_STATUS": "INTACT"}
    decision["ROW_HASH"] = D.row_hash(D.ledger_row(decision, meta))
    alert = {"ALERT_ID": kw["alert_id"], "CUSTOMER_REF": kw["customer_ref"], "ALERT_DATE": "2026-08-19", "ALERT_TYPE": "MULE_PASSTHROUGH", "SIGNAL_SOURCE": "I4C",
             "ACCOUNT_TYPE": "SAVINGS", "CUSTOMER_PROFILE": ctx["customer_kyc"], "ALERT_AMOUNT_INR": 555000, "ALERT_NARRATIVE": ctx["alert_narrative"]}
    recon = {"found": True, "decision": decision, "provenance": meta, "checks": {"row_hash": {"ok": True, "detail": "stored hash reproduced from the stored row"}}}
    return recon, alert, ctx["transactions"]


def test_a_dossier_from_a_decision_the_recorder_wrote_verifies_offline_and_says_what_it_proved():
    from skills import dossier as D
    recon, alert, txns = _recorded_file_decision()
    dossier = D.build(recon, alert, txns, generated_at=WHEN, app_version="test")
    assert dossier["schema"] == D.SCHEMA and dossier["dossier_sha256"] == D.seal(dossier) and "Synthetic data" in dossier["notice"]
    v = D.verify(json.loads(json.dumps(dossier)))              # through JSON, exactly as a downloaded file would be
    assert v["verdict"] in ("VERIFIED", "INCOMPLETE") and not v["failed"], v
    for name in ("file_sealed", "ledger_row_hash", "summary_matches_row", "provenance_complete", "gate_consistent", "regulatory_basis_intact", "rationale_digest",
                 "evidence_digest", "evidence_gate_replay", "override_recorded"):
        assert v["checks"][name]["ok"] is True, (name, v["checks"][name])
    assert v["checks"]["supersession_recorded"]["ok"] is None and "first decision" in v["checks"]["supersession_recorded"]["detail"]
    s = dossier["summary"]
    assert s["disposition"] == "FILE" and s["decided_by"] == "PO-TEST" and s["basis"]["proven"] and s["evidence_txn_ids"] is not None
    print("  [PASS] a FILE decision written by the real recorder: sealed, row hash, gate, basis, rationale digest, evidence digest and the evidence gate replay all pass offline")


def test_each_kind_of_tampering_is_caught_by_the_check_meant_to_catch_it():
    from skills import dossier as D
    recon, alert, txns = _recorded_file_decision()
    good = json.loads(json.dumps(D.build(recon, alert, txns, generated_at=WHEN)))

    def failed(mutate, reseal=False):
        d = copy.deepcopy(good)
        mutate(d)
        if reseal:
            d["dossier_sha256"] = D.seal(d)
        return set(D.verify(d)["failed"])

    assert failed(lambda d: d["decision"].__setitem__("rationale_text", "edited")) >= {"file_sealed"}
    assert failed(lambda d: (d["decision"].__setitem__("rationale_text", "edited"), d["ledger_row"].__setitem__("rationale_text", "edited")), reseal=True) >= {"ledger_row_hash", "rationale_digest"}, \
        "re-sealing an edited decision row does not hide it: the ledger's own hash no longer matches"
    assert "evidence_digest" in failed(lambda d: d["case_record"]["transactions"][0].__setitem__("amount_inr", 1.0), reseal=True)
    def break_gate(d):
        g = d["ledger_row"]["metadata"]["defensibility_gate"]
        g["conditions"] = [c for c in g["conditions"]][:-1] if g["conditions"] else [{"code": "X", "severity": "BLOCK", "satisfied": False}]
        g["status"] = "PASS" if g["status"] != "PASS" else "BLOCKED"
    assert "gate_consistent" in failed(break_gate, reseal=True)
    assert "regulatory_basis_intact" in failed(lambda d: d["ledger_row"]["metadata"]["regulatory_basis"].__setitem__("grade", "PROVEN_ONLY" if d["ledger_row"]["metadata"]["regulatory_basis"].get("grade") != "PROVEN_ONLY" else "INCLUDES_ASSUMED"), reseal=True)
    assert "override_recorded" in failed(lambda d: d["ledger_row"]["metadata"].update(override=True, override_reason="short"), reseal=True)

    def fabricate(d):
        text = d["ledger_row"]["rationale_text"] + " The customer wired Rs.25,00,000 by SWIFT to Dubai on 2026-08-27."
        d["decision"]["rationale_text"] = d["ledger_row"]["rationale_text"] = text
        d["ledger_row_hash"]["stored"] = D.row_hash(d["ledger_row"])          # a forger who also fixes the row hash still fails the evidence gate replay
    assert "evidence_gate_replay" in failed(fabricate, reseal=True)
    assert D.verify({"schema": "other"})["verdict"] == "FAILED" and D.verify("not a dossier")["verdict"] == "FAILED"
    print("  [PASS] edited text, a re-sealed edit, changed transactions, a broken gate, an edited basis, an override with no reason and a fabricated rationale are each caught")


def test_a_supersession_without_its_reason_is_caught_and_with_it_passes():
    from skills import dossier as D
    recon, alert, txns = _recorded_file_decision()
    base = D.build(recon, alert, txns, generated_at=WHEN)
    base = json.loads(json.dumps(base))
    base["ledger_row"]["metadata"]["supersession"] = {"prior_count": 1, "supersedes_decision_id": "earlier-id", "prior_decision_ids": ["earlier-id"], "prior_dispositions": ["NOT_FILE"], "reason": "New evidence"}
    base["dossier_sha256"] = D.seal(base)
    assert D.verify(base)["checks"]["supersession_recorded"]["ok"] is False
    base["ledger_row"]["metadata"]["supersession"]["reason"] = "The documents produced on 2026-09-30 contradict the earlier closure."
    base["dossier_sha256"] = D.seal(base)
    assert D.verify(base)["checks"]["supersession_recorded"]["ok"] is True
    print("  [PASS] a repeat decision's supersession must name the earlier decision and give a written reason")


def test_the_printable_page_escapes_everything_and_has_no_script_or_external_resource():
    from skills import dossier as D
    recon, alert, txns = _recorded_file_decision()
    for hostile in HOSTILE_STRINGS[:9] + ["<script>alert(1)</script>", '"><img src=https://attacker.example/p.png>', "[x](https://attacker.example)"]:
        r = copy.deepcopy(recon)
        r["decision"]["RATIONALE_TEXT"] = hostile + " " + r["decision"]["RATIONALE_TEXT"]
        r["decision"]["DECISION_MAKER_ID"] = hostile[:40]
        page = D.render_html(D.build(r, alert, [dict(t, counterparty=hostile[:60]) for t in txns], generated_at=WHEN))
        assert "<script" not in page.lower() and "<img" not in page.lower(), hostile
        assert 'src="' not in page and "href=" not in page and "@import" not in page and "url(" not in page
    page = D.render_html(D.build(recon, alert, txns, generated_at=WHEN))
    assert "Verification (replayed from this file alone)" in page and "Synthetic data" in page and "PROVEN means a primary source is cited" in page
    print("  [PASS] the page escapes hostile text in every field and carries no script, image, link or stylesheet import")


def _pack_harness():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path.cwd() / "tests"))
    import streamlit_app as ui
    import test_dossier as T
    recon, alert, txns = T._recorded_file_decision()

    class Skills:
        def reconstruct_decision(self, decision_id):
            return recon

        def load_alert(self, alert_id):
            return alert

        def load_transactions(self, alert_id):
            return txns
    ui.get_skills = lambda: Skills()
    ui._render_reconstruction(recon["decision"]["DECISION_ID"])


def test_the_decision_archive_builds_the_pack_only_when_asked_and_it_verifies():
    from streamlit.testing.v1 import AppTest
    import streamlit_app as ui
    original = ui.get_skills                          # the harness replaces it; a stale stub must not leak into the suites that run after this one
    try:
        at = AppTest.from_function(_pack_harness, default_timeout=60).run()
        assert not at.exception, [e.value for e in at.exception]
        assert "_inspection_packs" not in at.session_state or not at.session_state["_inspection_packs"], "nothing is built until the officer asks"
        button = next(b for b in at.button if b.label == "Prepare inspection pack")
        button.click()
        at.run()
        assert not at.exception, [e.value for e in at.exception]
        packs = at.session_state["_inspection_packs"]
    finally:
        ui.get_skills = original
    assert len(packs) == 1
    pack = next(iter(packs.values()))
    assert pack["verdict"] in ("VERIFIED", "INCOMPLETE") and not pack["failed"], pack["failed"]
    from skills import dossier as D
    again = D.verify(json.loads(pack["json"]))
    assert again["verdict"] == pack["verdict"] and "Verification (replayed from this file alone)" in pack["html"]
    print("  [PASS] the Decision archive prepares the pack on request; the file it offers verifies offline")


def test_the_verifier_script_checks_a_file_without_the_application_and_reports_failure_by_exit_status():
    import subprocess
    import sys
    import tempfile
    from pathlib import Path
    from skills import dossier as D
    recon, alert, txns = _recorded_file_decision()
    dossier = json.loads(json.dumps(D.build(recon, alert, txns, generated_at=WHEN)))
    with tempfile.TemporaryDirectory() as tmp:
        good, bad = Path(tmp) / "good.json", Path(tmp) / "bad.json"
        good.write_text(json.dumps(dossier))
        forged = copy.deepcopy(dossier)
        forged["decision"]["rationale_text"] = forged["ledger_row"]["rationale_text"] = "A rationale the officer never wrote, long enough to be plausible as one."
        forged["dossier_sha256"] = D.seal(forged)
        bad.write_text(json.dumps(forged))
        run = lambda *a: subprocess.run([sys.executable, str(ROOT / "scripts" / "verify_dossier.py"), *a], capture_output=True, text=True, env={"FIU_SKIP_DOTENV": "1", "PATH": ""})  # noqa: E731
        ok = run(str(good), "--html", str(Path(tmp) / "page.html"))
        assert ok.returncode == 0 and "Verdict:" in ok.stdout and "ledger row hash" in ok.stdout and (Path(tmp) / "page.html").is_file(), ok.stdout + ok.stderr
        fail = run(str(bad))
        assert fail.returncode == 1 and "FAILED" in fail.stdout and "ledger row hash" in fail.stdout, fail.stdout
        assert run(str(Path(tmp) / "missing.json")).returncode == 2
    print("  [PASS] scripts/verify_dossier.py: exit 0 for a good file, 1 for a forged one (even re-sealed), 2 for an unreadable one")


def test_the_sample_pack_in_the_repository_verifies_offline_says_what_it_is_and_fails_when_edited():
    """docs/sample/decision-pack-sample.json is what a reviewer without Snowflake can run the verifier on. It must stay valid, and it must not pass for a hosted decision."""
    import subprocess
    import sys
    import tempfile
    from pathlib import Path
    sample = ROOT / "docs" / "sample" / "decision-pack-sample.json"
    pack = json.loads(sample.read_text())
    assert "Synthetic data" in pack["notice"] and pack["app"]["version"].startswith("sample: built by the real recorder against a stub database"), "the sample says what it is"
    run = lambda *a: subprocess.run([sys.executable, str(ROOT / "scripts" / "verify_dossier.py"), *a], capture_output=True, text=True, env={"FIU_SKIP_DOTENV": "1", "PATH": ""})  # noqa: E731
    ok = run(str(sample))
    assert ok.returncode == 0 and "FAILED" not in ok.stdout and "ledger row hash" in ok.stdout, ok.stdout
    with tempfile.TemporaryDirectory() as tmp:
        edited = Path(tmp) / "edited.json"
        pack["decision"]["disposition"] = "NOT_FILE"
        edited.write_text(json.dumps(pack))
        assert run(str(edited)).returncode == 1, "an edited copy of the sample must fail"
    print("  [PASS] the sample pack verifies offline (exit 0), is labelled as built against a stub database, and fails (exit 1) once edited")


TESTS = [
    test_sf_json_matches_the_serialisation_snowflake_was_observed_to_use,
    test_the_python_row_hash_equals_the_hash_the_ledger_computed_in_sql_for_every_real_row,
    test_a_dossier_from_a_decision_the_recorder_wrote_verifies_offline_and_says_what_it_proved,
    test_each_kind_of_tampering_is_caught_by_the_check_meant_to_catch_it,
    test_a_supersession_without_its_reason_is_caught_and_with_it_passes,
    test_the_printable_page_escapes_everything_and_has_no_script_or_external_resource,
    test_the_decision_archive_builds_the_pack_only_when_asked_and_it_verifies,
    test_the_verifier_script_checks_a_file_without_the_application_and_reports_failure_by_exit_status,
    test_the_sample_pack_in_the_repository_verifies_offline_says_what_it_is_and_fails_when_edited,
]


if __name__ == "__main__":
    raise SystemExit(Runner("Inspection pack (decision dossier)").run(TESTS))
