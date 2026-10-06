"""
Audit durability and the immutable-archival roadmap: the protection-status indicator, write-once PACKAGES that chain from one to the next and verify
offline, and the refusal ever to call the Snowflake ledger immutable.

Offline. Usage:  python3 tests/test_audit_durability.py     (or pytest)
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from _helpers import ROOT, Runner

sys.path.insert(0, str(ROOT / "scripts"))

from skills import audit as A  # noqa: E402


def led(i, tamper=False):
    h = f"{i:064x}"
    return {"DECISION_ID": f"d{i}", "ALERT_ID": f"ALERT-{i:02d}", "DISPOSITION": "FILE", "DECISION_MADE_AT_UTC": f"2026-10-{i:02d}T10:00:00.000000", "STORED_HASH": h,
            "COMPUTED_HASH": ("f" * 64) if tamper else h, "META_TEXT": json.dumps({"schema_version": "3"})}


def anchor_of(rows, previous=None):
    recs = A.export_records(rows, previous)
    return [{**r, "EXPORTED_AT": "2026-10-03 09:30:00.000 +0530", "EXPORT_ID": "e"} for r in recs]


NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


# ── the status indicator ─────────────────────────────────────────────────────

def test_protection_status_has_four_levels_and_each_says_what_is_and_is_not_detectable():
    rows = [led(i) for i in range(1, 5)]
    none = A.export_protection_status(A.reconcile(rows, None, anchor_error="audit export table not available (not provisioned)"), now=NOW)
    assert none["level"] == A.STATUS_NOT_PROVISIONED and not none["provisioned"] and not none["current"] and "would not be detected" in none["detail"]
    behind_a = anchor_of(rows[:2])
    behind = A.export_protection_status(A.reconcile(rows, behind_a), now=NOW)
    assert behind["level"] == A.STATUS_BEHIND and behind["pending_rows"] == 2 and "2 of 4" in behind["detail"] and "would not be detected" in behind["detail"]
    ok = A.export_protection_status(A.reconcile(rows, anchor_of(rows)), now=NOW)
    assert ok["level"] == A.STATUS_CURRENT and ok["current"] and "detectable" in ok["detail"] and "not write-once storage" in ok["detail"] and ok["pending_rows"] == 0
    broken_a = anchor_of(rows)
    broken_a[1]["CHAIN_HASH"] = "0" * 64
    bad = A.export_protection_status(A.reconcile(rows, broken_a), now=NOW)
    assert bad["level"] == A.STATUS_CHAIN_BROKEN and "compromised" in bad["detail"].lower()
    empty = A.export_protection_status(A.reconcile(rows, []), now=NOW)
    assert empty["level"] == A.STATUS_BEHIND and empty["pending_rows"] == 4, "an export that exists but covers nothing is provisioned and behind, not 'not provisioned'"
    print("  [PASS] NOT_PROVISIONED · BEHIND (N of M rows uncovered) · CURRENT · CHAIN_BROKEN — each states what a deletion would and would not reveal")


def test_the_indicator_never_claims_immutability_and_always_carries_the_residual_risk():
    rows = [led(i) for i in range(1, 4)]
    for rep in (A.reconcile(rows, None, anchor_error="x"), A.reconcile(rows, anchor_of(rows)), A.reconcile(rows, anchor_of(rows[:1]))):
        st = A.export_protection_status(rep, now=NOW)
        assert st["immutable_claim"] is False and "not immutable" in st["residual_risk"] and "owner role" in st["residual_risk"].lower() or "ledger-owner role" in st["residual_risk"]
        text = " ".join([st["headline"], st["detail"], st["external_detail"]]).lower()
        assert "immutable" not in text.replace("not immutable", ""), text
        assert len(st["worm_requirements"]) == len(A.WORM_REQUIREMENTS) >= 6
    assert "compliance mode" in " ".join(A.WORM_REQUIREMENTS).lower() and "another" in " ".join(A.WORM_REQUIREMENTS).lower() or "different" in " ".join(A.WORM_REQUIREMENTS).lower()
    print("  [PASS] no status text contains an immutability claim; the owner-role deletion residual risk and 7 external-store requirements accompany every level")


def test_the_external_copy_is_not_attested_unless_someone_attests_and_an_attestation_is_compared_not_trusted():
    rows = [led(i) for i in range(1, 4)]
    rep = A.reconcile(rows, anchor_of(rows))
    assert A.export_protection_status(rep, now=NOW)["external"] == A.EXTERNAL_NOT_ATTESTED
    head = rep["anchor"]["head"]
    assert A.export_protection_status(rep, attestation={"head_chain_hash": head}, now=NOW)["external"] == A.EXTERNAL_MATCHES
    earlier = rep["chain_heads"][0]
    assert A.export_protection_status(rep, attestation={"head_chain_hash": earlier}, now=NOW)["external"] == A.EXTERNAL_BEHIND
    mismatch = A.export_protection_status(rep, attestation={"head_chain_hash": "9" * 64}, now=NOW)
    assert mismatch["external"] == A.EXTERNAL_MISMATCH and "integrity incident" in mismatch["external_detail"]
    assert "claim about another system" in A.export_protection_status(rep, attestation={"head_chain_hash": head}, now=NOW)["external_detail"]
    assert A.export_protection_status(rep, attestation={}, now=NOW)["external"] == A.EXTERNAL_NOT_ATTESTED
    print("  [PASS] external write-once copy: NOT_ATTESTED by default; an attested head is compared (matches / behind / mismatch) and described as a claim about another system")


def test_export_age_is_read_from_a_snowflake_timestamp_string_and_flags_a_late_export():
    rows = [led(i) for i in range(1, 4)]
    rep = A.reconcile(rows, anchor_of(rows[:2]))
    st = A.export_protection_status(rep, now=datetime(2026, 10, 3, 4, 30, tzinfo=timezone.utc))
    assert abs(st["last_exported_age_hours"] - 0.5) < 0.01, st["last_exported_age_hours"]     # 09:30 +05:30 = 04:00 UTC, so 04:30 UTC is half an hour later
    assert st["behind_schedule"] is False
    late = A.export_protection_status(rep, now=datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc))
    assert late["behind_schedule"] is True and late["last_exported_age_hours"] > 24
    assert A._parse_ts("2026-10-02T10:05:23Z").hour == 10 and A._parse_ts("garbage") is None and A._parse_ts(None) is None
    print("  [PASS] the export's age is parsed from a Snowflake TIMESTAMP_TZ string (zone honoured); BEHIND plus an age beyond the limit is flagged behind schedule")


# ── packages ─────────────────────────────────────────────────────────────────

def make_packages(n_per=2, n=2):
    rows = [led(i) for i in range(1, n_per * n + 1)]
    pkgs, previous = [], None
    for k in range(n):
        recs = A.export_records(rows[k * n_per:(k + 1) * n_per], previous)
        pkgs.append(A.worm_package(recs, A.build_manifest(recs, exported_by="FIU_AUDIT_ROLE", exported_at="2026-10-03T00:00:00+00:00"), export_id=f"run{k + 1}"))
        previous = recs[-1]
    return pkgs


def test_a_package_verifies_and_every_kind_of_tampering_is_detected():
    p = make_packages(3, 1)[0]
    assert A.verify_package(p["ndjson"], p["manifest_json"])["ok"]
    assert p["manifest"]["format"] == A.PACKAGE_FORMAT and p["manifest"]["immutable_claim"] is False and len(p["manifest"]["write_once_requirements"]) >= 6
    lines = p["ndjson"].splitlines()
    cases = {
        "body altered": p["ndjson"].replace('"ALERT-02"', '"ALERT-99"'),
        "record removed": "\n".join(lines[:2] + lines[3:]) + "\n",
        "truncated": "\n".join(lines[:-1]) + "\n",
        "garbage line": p["ndjson"] + "not json\n",
    }
    for label, body in cases.items():
        r = A.verify_package(body, p["manifest_json"])
        assert not r["ok"] and r["problems"], label
    # With the manifest's body hash PATCHED to match a forged body, the chain still catches any change to a field it commits to
    # (decision id, row hash, time) …
    import hashlib
    for field, value in (("ROW_HASH", "e" * 64), ("DECISION_ID", "dX"), ("DECISION_MADE_AT_UTC", "2026-01-01T00:00:00.000000")):
        recs = [json.loads(ln) for ln in lines[1:]]
        recs[1][field] = value
        forged = "\n".join([lines[0]] + [json.dumps(r, sort_keys=True) for r in recs]) + "\n"
        r = A.verify_package(forged, dict(p["manifest"], ndjson_sha256=hashlib.sha256(forged.encode()).hexdigest()))
        assert not r["ok"] and any("altered" in x or "chain" in x for x in r["problems"]), (field, r["problems"])
    # … but ALERT_ID and DISPOSITION are convenience copies the chain does not cover: only the body hash protects them inside a package (and the body
    # hash lives in the same store), so reconcile() compares them with the live ledger — see the next test.
    recs = [json.loads(ln) for ln in lines[1:]]
    recs[1]["ALERT_ID"] = "ALERT-99"
    forged = "\n".join([lines[0]] + [json.dumps(r, sort_keys=True) for r in recs]) + "\n"
    assert A.verify_package(forged, dict(p["manifest"], ndjson_sha256=hashlib.sha256(forged.encode()).hexdigest()))["ok"] is True, "documented limit of the package check"
    for bad_man in ("{not json", json.dumps({**p["manifest"], "head": "1" * 64}), json.dumps({**p["manifest"], "count": 99}), json.dumps({**p["manifest"], "format": "x"})):
        assert not A.verify_package(p["ndjson"], bad_man)["ok"]
    print("  [PASS] a package verifies; an altered body, a removed or truncated record, junk, a patched manifest, a wrong head or count are each detected — even a patched body hash is caught by the chain")


def test_reconcile_compares_the_exports_convenience_fields_with_the_live_ledger():
    rows = [led(i) for i in range(1, 4)]
    anchor = anchor_of(rows)
    assert not [f for f in A.reconcile(rows, anchor)["findings"] if f["code"] == "EXPORT_FIELDS_DIFFER"]
    anchor[1]["ALERT_ID"] = "ALERT-99"
    anchor[2]["DISPOSITION"] = "NOT_FILE"
    rep = A.reconcile(rows, anchor)
    f = next(f for f in rep["findings"] if f["code"] == "EXPORT_FIELDS_DIFFER")
    assert f["severity"] == "COMPROMISED" and f["count"] == 2 and rep["verdict"] == A.VERDICT_COMPROMISED, rep["findings"]
    live_changed = [dict(r) for r in rows]
    live_changed[0]["DISPOSITION"] = "NOT_FILE"                              # the LEDGER row changed; its stored hash no longer matches (TAMPERED) and the export differs
    codes = {f["code"] for f in A.reconcile(live_changed, anchor_of(rows))["findings"]}
    assert "EXPORT_FIELDS_DIFFER" in codes
    print("  [PASS] reconcile: an export record whose alert id or disposition differs from the live ledger row is a COMPROMISED finding (the chain covers decision id, row hash and time; these two copies are checked here)")


def test_packages_chain_from_one_to_the_next_and_a_missing_or_reordered_package_is_found():
    p1, p2, p3 = make_packages(2, 3)
    pairs = lambda *ps: [(p["ndjson"], p["manifest"]) for p in ps]       # noqa: E731
    ok = A.verify_package_sequence(pairs(p1, p2, p3))
    assert ok["ok"] and ok["packages"] == 3 and ok["last_seq"] == 6 and ok["head"] == p3["manifest"]["head"]
    assert p2["manifest"]["prev_head"] == p1["manifest"]["head"] and p1["manifest"]["prev_head"] == A.GENESIS
    missing = A.verify_package_sequence(pairs(p1, p3))
    assert not missing["ok"] and any("does not chain from the previous package" in x for x in missing["problems"]) and any("missing or repeated" in x for x in missing["problems"])
    assert not A.verify_package_sequence(pairs(p2, p1, p3))["ok"] and not A.verify_package_sequence(pairs(p1, p1))["ok"]
    assert not A.verify_package_sequence(pairs(p2))["ok"], "a sequence must start at genesis"
    assert A.verify_package_sequence([])["ok"] and A.verify_package_sequence([])["head"] is None
    print("  [PASS] 3 packages chain genesis → head with contiguous SEQ; a missing, repeated, reordered or non-genesis-start package fails the sequence check")


def test_the_package_name_cannot_escape_and_an_empty_segment_is_not_packaged():
    recs = A.export_records([led(1)])
    p = A.worm_package(recs, A.build_manifest(recs), export_id="../../etc/passwd; DROP")
    assert ".." not in p["object_key"] and "/etc/" not in p["object_key"] and p["object_key"].startswith("fiu-ledger-audit/") and p["object_key"].endswith(".ndjson")
    assert p["manifest_object_key"].endswith(".manifest.json") and p["manifest"]["ndjson_object"] == p["object_key"]
    try:
        A.worm_package([], A.build_manifest([]))
        raise AssertionError("an empty segment was packaged")
    except ValueError:
        pass
    print("  [PASS] the object key is built from sanitised parts only (no path traversal); an empty export segment is refused")


# ── the local write-once SIMULATION and the offline verifier ─────────────────

def test_the_local_sink_refuses_to_overwrite_and_says_it_is_a_simulation():
    import audit_ledger as cli
    with tempfile.TemporaryDirectory() as d:
        sink = cli.LocalDirectorySink(Path(d))
        p = make_packages(2, 1)[0]
        body = sink.put(p["object_key"], p["ndjson"])
        assert body.read_text() == p["ndjson"] and not (os.stat(body).st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)), "created read-only"
        try:
            sink.put(p["object_key"], "replacement")
            raise AssertionError("an existing object was overwritten")
        except FileExistsError:
            pass
        assert body.read_text() == p["ndjson"]
        for escape in ("../outside.txt", "/tmp/abs.txt", "a/../../b.txt"):
            try:
                sink.put(escape, "x")
                raise AssertionError(f"wrote outside the sink: {escape}")
            except (ValueError, FileExistsError, OSError):
                pass
        assert "NOT immutable" in cli.LocalDirectorySink.__doc__ and "SIMULATION" in cli.LocalDirectorySink.__doc__
    print("  [PASS] the local sink creates exclusively and read-only, refuses an overwrite or a path outside its directory, and its docstring says it is a simulation, not WORM")


def test_the_offline_verifier_accepts_a_directory_of_packages_and_rejects_a_tampered_one():
    import audit_ledger as cli
    pkgs = make_packages(2, 3)
    with tempfile.TemporaryDirectory() as d:
        sink = cli.LocalDirectorySink(Path(d))
        for p in pkgs:
            sink.put(p["object_key"], p["ndjson"])
            sink.put(p["manifest_object_key"], p["manifest_json"])
        cmd = [sys.executable, str(ROOT / "scripts/audit_ledger.py"), "verify", d]
        env = {k: v for k, v in os.environ.items() if not k.startswith(("SNOWFLAKE_", "FIU_"))} | {"FIU_SKIP_DOTENV": "1"}
        ok = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=ROOT, timeout=60)
        assert ok.returncode == 0 and "VERIFIED" in ok.stdout and "3 package(s)" in ok.stdout and "does not prove they are the complete ledger" in ok.stdout, ok.stdout + ok.stderr
        victim = next(Path(d).rglob("*.ndjson"))
        os.chmod(victim, 0o644)
        # Alter bytes regardless of which package the filesystem yields first.
        # A field-specific replacement was brittle because package ordering is not
        # guaranteed and some packages do not contain ALERT-02.
        victim.write_text(victim.read_text() + "\n")
        bad = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=ROOT, timeout=60)
        assert bad.returncode == 1 and "FAILED" in bad.stdout
        os.chmod(victim, 0o644)
        victim.unlink()
        gone = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=ROOT, timeout=60)
        assert gone.returncode == 1
    print("  [PASS] `audit_ledger.py verify DIR` runs with no Snowflake: 3 chained packages VERIFIED (exit 0); an edited body or a missing one FAILS (exit 1); it states what a verified chain does not prove")


def test_no_audit_code_path_can_delete_update_or_overwrite_a_ledger_row():
    import re
    for rel in ("skills/audit.py", "scripts/audit_ledger.py"):
        src = open(ROOT / rel).read()
        code = "\n".join(re.sub(r"#.*$", "", ln) for ln in src.splitlines())
        for m in re.finditer(r"""(?:execute|_execute)\(\s*f?['"]{1,3}\s*(UPDATE|DELETE|TRUNCATE|DROP|MERGE|ALTER)\b""", code, re.I):
            raise AssertionError(f"{rel}: executes {m.group(1)}")
        assert not re.search(r"\b(?:DELETE FROM|TRUNCATE TABLE|DROP TABLE|UPDATE\s+\w+\s+SET)\b", code.replace("PROVISION", ""), re.I) or rel.endswith("audit.py") and "DROP" not in code
    print("  [PASS] neither the audit module nor the audit CLI contains an UPDATE / DELETE / TRUNCATE / DROP / MERGE / ALTER statement")


TESTS = [
    test_protection_status_has_four_levels_and_each_says_what_is_and_is_not_detectable, test_the_indicator_never_claims_immutability_and_always_carries_the_residual_risk,
    test_the_external_copy_is_not_attested_unless_someone_attests_and_an_attestation_is_compared_not_trusted, test_export_age_is_read_from_a_snowflake_timestamp_string_and_flags_a_late_export,
    test_a_package_verifies_and_every_kind_of_tampering_is_detected, test_reconcile_compares_the_exports_convenience_fields_with_the_live_ledger,
    test_packages_chain_from_one_to_the_next_and_a_missing_or_reordered_package_is_found,
    test_the_package_name_cannot_escape_and_an_empty_segment_is_not_packaged, test_the_local_sink_refuses_to_overwrite_and_says_it_is_a_simulation,
    test_the_offline_verifier_accepts_a_directory_of_packages_and_rejects_a_tampered_one, test_no_audit_code_path_can_delete_update_or_overwrite_a_ledger_row,
]

if __name__ == "__main__":
    raise SystemExit(Runner("Audit durability (offline)").run(TESTS))
