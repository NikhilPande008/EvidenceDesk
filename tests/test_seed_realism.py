"""
The seeded alerts are credible evidence, not staged answers.

Fifteen of the nineteen alerts carry real transaction rows transcribed from domain/scenarios/*.md, the detector texts state observations and open items but
never a conclusion, the legitimate-looking cases are told apart by their EVIDENCE (a signal no flagged counterparty corroborates, relationships the KYC
record sources) and not by a label, one seeded contradiction is kept on purpose, and the 7-working-day clock is live in the queue. This suite pins those
properties so a later edit cannot quietly put an answer back into the data.

Offline. Usage:  python3 tests/test_seed_realism.py     (or pytest)
"""

from __future__ import annotations

import datetime as dt
import re
import sys

from _helpers import ROOT, Runner

sys.path.insert(0, str(ROOT / "scripts"))

import setup_alerts as seed  # noqa: E402
from skills import evidence_quality as Q  # noqa: E402
from skills import prioritisation as P  # noqa: E402
from skills.evidence import signal_brief  # noqa: E402
from skills.ledger import sla_days_remaining  # noqa: E402

NOW = dt.date(2026, 10, 5)
ALERT = {a["ALERT_ID"]: a for a in seed.ALERTS}


def rows(aid: str) -> list[dict]:
    return [{"txn_id": t["TXN_ID"], "date": t["TXN_DATE"], "type": t["TXN_TYPE"], "amount_inr": t["AMOUNT_INR"], "channel": t["CHANNEL"], "counterparty": t["COUNTERPARTY"],
             "is_flagged": t["IS_FLAGGED"]} for t in seed.TRANSACTIONS if t["ALERT_ID"] == aid]


def quality(aid: str) -> dict:
    return Q.assess(ALERT[aid], rows(aid), now=NOW)


def codes(aid: str) -> dict[str, str]:
    return {f["code"]: f["effect"] for f in quality(aid)["findings"]}


# ── no conclusions in the data ───────────────────────────────────────────────

CONCLUSION_WORDS = re.compile(
    r"false[- ]positive|legitimate|look-?alike|unmistak|consistent with (?:a )?coordinated|amplifier of intent|predicate offence|fully documented|evidence produced|"
    r"pattern suggests|\binvestigation:|two readings|contested|should be filed|\bDEFERRED\b|mule[- ]farm|documentary evidence|seasonal pattern|STR-reportable", re.I)


def test_no_detector_text_states_a_conclusion_and_no_counterparty_label_carries_exculpatory_documentation():
    for a in seed.ALERTS:
        hit = CONCLUSION_WORDS.search(a["ALERT_NARRATIVE"])
        assert not hit, f"{a['ALERT_ID']}: the alert text states a conclusion ({hit.group(0)!r}); a detector reports observations and open items"
    for t in seed.TRANSACTIONS:
        assert not re.search(r"invoice on file|documented|legitimate|false", t["COUNTERPARTY"], re.I), (t["TXN_ID"], t["COUNTERPARTY"])
    assert "invoice" not in ALERT["ALERT-16"]["ALERT_NARRATIVE"].lower() and "hospital" in ALERT["ALERT-16"]["ALERT_NARRATIVE"].lower()
    print(f"  [PASS] {len(seed.ALERTS)} alert texts state observations and open items only; {len(seed.TRANSACTIONS)} counterparty labels name the party and nothing more")


# ── real rows, traceable to the scenarios ────────────────────────────────────

SCENARIOS_PRESENT = any((ROOT / "domain/scenarios").glob("*-*.md"))


def traced(amounts: set[int], name: str) -> bool:
    """Every amount appears in the scenario file. The scenario files are private working notes (git-ignored), so a clean clone does not have them:
    there the structural assertions still run and only this traceability check is skipped."""
    return True if not SCENARIOS_PRESENT else amounts <= scenario_amounts(name)


def scenario_amounts(name: str) -> set[int]:
    """Every rupee amount a scenario file states (₹3,40,000 or ≈₹37.5L), as whole rupees."""
    text = next((ROOT / "domain/scenarios").glob(f"{name}-*.md")).read_text()
    out: set[int] = set()
    for m in re.finditer(r"₹\s?([\d,]+(?:\.\d+)?)\s?(L|Cr)?", text):
        v = float(m.group(1).replace(",", ""))
        out.add(int(round(v * {"L": 1e5, "Cr": 1e7}.get(m.group(2), 1))))
    return out


def test_fifteen_alerts_have_real_rows_each_traceable_to_its_scenario_table():
    assert sorted(seed.EXPLICIT_TXNS) == ["ALERT-01", "ALERT-02", "ALERT-03", "ALERT-04", "ALERT-05", "ALERT-07", "ALERT-08", "ALERT-11", "ALERT-12", "ALERT-14", "ALERT-15", "ALERT-16", "ALERT-17", "ALERT-18", "ALERT-19"]
    amounts = lambda aid, side=None: sorted(int(t["AMOUNT_INR"]) for t in seed.TRANSACTIONS if t["ALERT_ID"] == aid and (side is None or t["TXN_TYPE"] == side))   # noqa: E731
    assert set(amounts("ALERT-11")) == {340000, 420000, 480000} and traced(set(amounts("ALERT-11")), "11")
    assert set(amounts("ALERT-14")) == {820000, 640000, 880000, 750000} and traced(set(amounts("ALERT-14")), "14")
    assert set(amounts("ALERT-05")) == {3750000, 2670000} and traced({3750000, 2670000}, "05"), "USD 45,000 ≈ ₹37.5L and USD 32,000 ≈ ₹26.7L, as the scenario states"
    assert all(abs(a - 1500000) / 1500000 < 0.01 for a in amounts("ALERT-12")) and len(amounts("ALERT-12")) == 2, "two attempts of ≈ ₹15L, as the scenario states"
    months: dict[str, int] = {}
    for t in seed.TRANSACTIONS:
        if t["ALERT_ID"] == "ALERT-15":
            months[str(t["TXN_DATE"])[:7]] = months.get(str(t["TXN_DATE"])[:7], 0) + int(t["AMOUNT_INR"])
            assert 6 <= int(str(t["TXN_DATE"])[8:10]) <= 10, "deposits are made between the 6th and the 10th"
    assert sorted(months.values()) == sorted([280000, 320000, 295000, 310000, 275000, 305000]) and traced(set(months.values()), "15"), months
    for t in seed.TRANSACTIONS:
        if t["CHANNEL"] == "CASH" and t["ALERT_ID"] in seed.EXPLICIT_TXNS:
            assert dt.date.fromisoformat(str(t["TXN_DATE"])).weekday() < 5, f"{t['TXN_ID']}: a counter cash deposit on a weekend"
    assert len(seed.TRANSACTIONS) == 92 and len({t["TXN_ID"] for t in seed.TRANSACTIONS}) == 92
    print("  [PASS] 15 of 19 alerts have real rows (92 in all): amounts match the scenario tables, ALERT-15's monthly sums match, no cash deposit falls on a weekend")


def test_every_explicit_alert_reconciles_except_the_one_contradiction_kept_on_purpose():
    assert set(seed.HEADER_AMOUNT_CONTRADICTIONS) == {"ALERT-12"} and seed.OUTWARD_FLOW_ALERTS == {"ALERT-05", "ALERT-12"}
    for aid in seed.EXPLICIT_TXNS:
        recon = codes(aid).get("AMOUNT_RECONCILIATION")
        assert (recon == Q.REQUIRES_MANUAL_REVIEW) == (aid in seed.HEADER_AMOUNT_CONTRADICTIONS), (aid, recon)
    f = next(x for x in quality("ALERT-12")["findings"] if x["code"] == "AMOUNT_RECONCILIATION")
    assert "Rs.25,05,000" in f["detail"] or "25.05" in f["detail"] or "2505000" in f["detail"].replace(",", ""), f["detail"]
    assert quality("ALERT-12")["amount_gap_pct"] == 20.0
    print("  [PASS] ALERT-12's header (Rs.25.05L) contradicts its rows (Rs.30.06L): reported as a manual-review finding; every other explicit alert reconciles")


def test_the_evidence_quality_outcome_of_each_alert_is_the_designed_one():
    for aid in seed.EXPLICIT_TXNS:
        assert "TXN_SUMMARY_ONLY" not in codes(aid) and "TXN_UNREADABLE" not in codes(aid), aid
    for aid in ("ALERT-06", "ALERT-09", "ALERT-10", "ALERT-13"):
        assert codes(aid)["TXN_SUMMARY_ONLY"] == Q.REQUIRES_ACKNOWLEDGEMENT and quality(aid)["sufficiency_pct"] <= 60, aid
    assert codes("ALERT-03")["DOCUMENTS_MISSING_STATED"] == Q.REQUIRES_MANUAL_REVIEW, "the open source-of-funds item is surfaced"
    assert codes("ALERT-11")["KYC_CURRENCY_FLAG"] == codes("ALERT-14")["KYC_CURRENCY_FLAG"] == Q.REQUIRES_MANUAL_REVIEW
    assert "TXN_NO_BASELINE" not in codes("ALERT-07") and "TXN_NO_BASELINE" in codes("ALERT-05"), "a 45-day window has a baseline; a 3-week one does not"
    assert "TXN_RECORD_STALE" in codes("ALERT-15"), "the last deposit is more than 30 days before the alert"
    for aid in ("ALERT-01", "ALERT-16"):
        assert set(codes(aid).values()) == {Q.INFORMATIONAL}, f"{aid}: the demo pair carries informational findings only, so the decision gate is unchanged"
    assert not any(quality(a["ALERT_ID"])["blocks_filing"] for a in seed.ALERTS)
    print("  [PASS] thin (aggregate-only) alerts need acknowledgement; open documents, stale KYC and the contradiction ask for manual review; the demo pair is informational only")


def test_the_twin_pair_differs_by_evidence_not_by_label():
    a01, a16 = signal_brief(rows("ALERT-01")), signal_brief(rows("ALERT-16"))
    assert a01["flagged_counterparties"] and not a16["flagged_counterparties"], "the difference is a flag in the rows"
    assert "SIGNAL_NOT_CORROBORATED" in codes("ALERT-16") and "SIGNAL_NOT_CORROBORATED" not in codes("ALERT-01"), "the I4C signal is matched by a flagged counterparty in one case, by none in the other"
    assert a01["onward_ratio_pct"] > 98 and a16["flagged_debit_total"] == 0
    assert len(a16["documented_counterparties"]) == 3 and "City General Hospital" not in a16["documented_counterparties"], "three KYC-sourced relationships; the payee carries no label"
    assert ALERT["ALERT-01"]["SIGNAL_SOURCE"] == ALERT["ALERT-16"]["SIGNAL_SOURCE"] and ALERT["ALERT-01"]["ALERT_AMOUNT_INR"] == ALERT["ALERT-16"]["ALERT_AMOUNT_INR"]
    clock = lambda aid: sla_days_remaining(seed.suspicion_formed_at(seed.SUSPICION_WD_AGO[aid], dt.datetime(2026, 10, 5, 12, tzinfo=seed.IST)), dt.datetime(2026, 10, 5, 12, tzinfo=seed.IST))   # noqa: E731
    p = lambda aid: P.prioritise(ALERT[aid], signal_brief(rows(aid)), quality(aid), sla_days_remaining=clock(aid), now=NOW)["score"]   # noqa: E731
    assert p("ALERT-01") > p("ALERT-16")
    print("  [PASS] same detector, source and amount; ALERT-01 has a flagged onward counterparty and ALERT-16 has none, so the I4C signal is uncorroborated there; ALERT-01 ranks higher")


# ── the suspicion clock ──────────────────────────────────────────────────────

def test_the_seeded_clock_gives_a_live_mix_of_deadlines_from_whatever_moment_the_seed_runs():
    for now in (dt.datetime(2026, 10, 5, 18, 54, tzinfo=seed.IST), dt.datetime(2026, 10, 10, 12, 0, tzinfo=seed.IST), dt.datetime(2026, 10, 11, 9, 0, tzinfo=seed.IST),
                dt.datetime(2026, 11, 3, 7, 30, tzinfo=seed.IST)):                                        # a Monday evening, a Saturday, a Sunday, a Tuesday morning
        left = {aid: sla_days_remaining(seed.suspicion_formed_at(n, now), now) for aid, n in seed.SUSPICION_WD_AGO.items()}
        assert left == {aid: 7 - n for aid, n in seed.SUSPICION_WD_AGO.items()}, (now, left)
        assert min(left.values()) < 0 and 0 in left.values() and max(left.values()) == 7, left
        assert all(seed.suspicion_formed_at(n, now) <= now for n in seed.SUSPICION_WD_AGO.values()), "never a future suspicion time"
    assert 5 <= len(seed.SUSPICION_WD_AGO) <= 12 and len(seed.SUSPICION_WD_AGO) < len(seed.ALERTS), "some alerts have a time, some deliberately have none"
    assert seed.SUSPICION_WD_AGO["ALERT-01"] > seed.SUSPICION_WD_AGO["ALERT-16"], "the demo pair: ALERT-01's clock is closer to its deadline"
    print("  [PASS] clock offsets give 1 WD overdue / due today / 1..7 WD left from any load moment (weekday, Saturday, Sunday); never in the future; 7 alerts carry none")


def test_the_feed_time_is_a_stated_optional_field_the_application_never_infers():
    assert "SUSPICION_FORMED_AT" in seed.CREATE_TABLE_SQL and "SUSPICION_FORMED_AT" in seed.MERGE_SQL
    assert "SUSPICION_FORMED_AT" in (ROOT / "domain/corpus/export/ddl/alerts.sql").read_text() and "SUSPICION_FORMED_AT" in (ROOT / "domain/corpus/export/ddl/views.sql").read_text()
    migration = (ROOT / "deploy/09_alert_feed_suspicion_time.sql").read_text()
    assert "ADD COLUMN IF NOT EXISTS SUSPICION_FORMED_AT" in migration
    sys.path.insert(0, str(ROOT))
    from streamlit_app import _feed_suspicion_ist, case_clock, effective_suspicion
    alert = {"ALERT_ID": "A", "ALERT_DATE": "2026-09-01"}
    assert effective_suspicion(alert, {}) == (None, None), "no recorded time and no feed time: no clock. The alert date is never a suspicion time"
    assert case_clock(alert, *effective_suspicion(alert, {}))["days"] is None
    feed = {**alert, "SUSPICION_FORMED_AT": "2026-10-01T10:30:00+05:30"}
    assert effective_suspicion(feed, {}) == ("2026-10-01T10:30:00+05:30", "feed")
    assert effective_suspicion(feed, {"A": "2026-09-30T09:00:00+00:00"}) == ("2026-09-30T09:00:00+00:00", "ledger"), "a recorded decision takes precedence over the feed"
    assert _feed_suspicion_ist({"SUSPICION_FORMED_AT": "2999-01-01T00:00:00+00:00"}) is None and _feed_suspicion_ist({"SUSPICION_FORMED_AT": "garbage"}) is None
    assert _feed_suspicion_ist({}) is None and _feed_suspicion_ist({"SUSPICION_FORMED_AT": "2026-10-01T10:30:00+05:30"}).hour == 10
    print("  [PASS] SUSPICION_FORMED_AT: optional feed field in the DDL, view and seed; a ledger time beats it; absent, future or unreadable means no clock, never a guess from the alert date")

def test_the_documents_quote_the_seeds_real_size():
    """The readiness tables (rendered into ARCHITECTURE.md) said '31 rows' after the seed grew to 69. The numbers they quote must be the seed's."""
    text = (ROOT / "skills/readiness.py").read_text() + (ROOT / "domain/corpus/export/ddl/alerts.sql").read_text()
    n = len(seed.TRANSACTIONS)
    assert f"{n} synthetic transactions" in text and f"{n} transactions in batch" in text and f"{n} rows; the queue" in text and f"-- {n}" in text
    assert not re.search(r"\b31 (synthetic )?(transactions|rows)\b", text), "a stale row count"
    print(f"  [PASS] readiness tables and DDL comments quote {n} transactions, the seed's real size")


def test_every_ddl_and_deploy_statement_has_balanced_quotes():
    """An unescaped apostrophe inside a COMMENT ('the author's labels') is a compile error that only a real Snowflake run reveals
    (found by the first fresh deploy, 2026-10-05). The deploy tool splits files with Snowflake's own splitter; so does this test."""
    import io
    from snowflake.connector.util_text import split_statements
    bad = []
    files = sorted([*(ROOT / "domain/corpus/export/ddl").glob("*.sql"), *(ROOT / "deploy").glob("*.sql")])
    for f in files:
        for stmt, _ in split_statements(io.StringIO(f.read_text()), remove_comments=True):
            body = re.sub(r"\$\$.*?\$\$", "", stmt.strip(), flags=re.S)
            if body.replace("''", "").count("'") % 2:
                bad.append(f"{f.relative_to(ROOT)}: {' '.join(body.split())[:80]}")
    assert not bad, bad
    print(f"  [PASS] {len(files)} SQL files: every statement has balanced quotes")


TESTS = [
    test_no_detector_text_states_a_conclusion_and_no_counterparty_label_carries_exculpatory_documentation,
    test_fifteen_alerts_have_real_rows_each_traceable_to_its_scenario_table, test_every_explicit_alert_reconciles_except_the_one_contradiction_kept_on_purpose,
    test_the_evidence_quality_outcome_of_each_alert_is_the_designed_one, test_the_twin_pair_differs_by_evidence_not_by_label,
    test_the_seeded_clock_gives_a_live_mix_of_deadlines_from_whatever_moment_the_seed_runs, test_the_feed_time_is_a_stated_optional_field_the_application_never_infers,
    test_the_documents_quote_the_seeds_real_size, test_every_ddl_and_deploy_statement_has_balanced_quotes,
]

if __name__ == "__main__":
    raise SystemExit(Runner("Seed realism (offline)").run(TESTS))
