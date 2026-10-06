"""
The fabrication-catch benchmark (tests/fabrication_benchmark.py) as a test: it pins the claims the project publishes about its
deterministic evidence validator, so a validator change that costs a point of accuracy, or a doc that quotes a stale number, fails here.

Offline. Usage:  python3 tests/test_fabrication_benchmark.py     (or pytest)
Regenerate the evidence:  python3 scripts/eval_fabrication_benchmark.py --write
"""

from __future__ import annotations

import json
import sys

from _helpers import ROOT, Runner

sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))

import eval_fabrication_benchmark as script  # noqa: E402
import fabrication_benchmark as B  # noqa: E402

_RESULT: dict = {}


def result() -> dict:
    if not _RESULT:
        _RESULT.update(B.run())
    return _RESULT


def test_the_faithful_bases_pass_so_a_blocked_fabrication_means_something():
    for bid, text in B.BASES:
        r = B.validate(text)
        assert r["passed"] and not r["unverified_assertions"], (bid, r["unsupported_claims_by_type"], r["unverified_assertions"])
    assert B.faithful_narratives() == B.faithful_narratives(), "the benchmark is deterministic"
    assert len(B.faithful_narratives()) >= 60
    print(f"  [PASS] all {len(B.BASES)} hand-written bases and the {len(B.faithful_narratives())} faithful narratives are deterministic and start clean")


def test_no_fabricated_amount_is_accidentally_true():
    colliding = [fid for fid, cls, spec in B.FABRICATIONS if cls == "amount" and B.is_collision(spec[1] if isinstance(spec, tuple) else spec)]
    assert colliding == [], f"fabricated amounts that the record actually supports: {colliding}"
    print(f"  [PASS] none of the {sum(1 for _, c, _ in B.FABRICATIONS if c == 'amount')} fabricated amounts is within tolerance of a figure the record supports "
          f"({result()['record']['derivable_amounts']} derivable figures)")


def test_nothing_true_is_blocked_and_every_in_distribution_fabrication_is():
    r = result()
    f, h = r["faithful"], r["fabricated_hard"]
    assert f["hard_false_positives"]["k"] == 0, f["hard_fp_cases"][:3]
    assert f["soft_flags"]["k"] == 0, f["soft_flag_cases"][:3]
    o = f["other_alerts"]
    assert o["alerts"] == sorted(B.seed.EXPLICIT_TXNS) and len(o["alerts"]) >= 12 and o["narratives"] >= 50, o["alerts"]
    assert o["hard_false_positives"]["k"] == 0, o["hard_fp_cases"][:3]       # a validator that only works on ALERT-01 would fail here
    assert h["caught_any"]["k"] == h["caught_any"]["n"] >= 150, h["missed"][:3]
    assert h["caught_as_right_class"]["k"] == h["caught_any"]["n"], "every block names the right claim class"
    assert set(h["by_class"]) == {"amount", "date", "channel", "geography", "txn_id", "identifier", "entity", "profile_income", "profile_fact"}
    print(f"  [PASS] faithful: 0/{f['narratives']} wrongly blocked on ALERT-01 (95% upper bound {f['hard_false_positives']['wilson95_pct'][1]}%) and 0/{o['narratives']} across the other {len(o['alerts']) - 1} alerts with real rows as well; "
          f"in-distribution: {h['caught_any']['k']}/{h['caught_any']['n']} blocked, all as the right class (95% lower bound {h['caught_any']['wilson95_pct'][0]}%)")


def test_the_validator_improvement_is_measured_against_a_frozen_baseline_not_asserted():
    baselines = sorted((ROOT / "evidence" / "fabrication-benchmark").glob("*/baseline_before_fixes.json"))
    assert baselines, "evidence/fabrication-benchmark/*/baseline_before_fixes.json is the stress result frozen before the validator was extended"
    before = json.loads(baselines[0].read_text())["stress"]["S"]["caught"]
    after = result()["stress"]["S"]["caught"]
    assert (before["k"], before["n"]) == (7, 40), before
    assert after["k"] == after["n"] == 40, "stress set S (the set the fixes were written against) is a regression guard: it must stay fully caught"
    print(f"  [PASS] stress set S: {before['k']}/{before['n']} before the fixes (frozen), {after['k']}/{after['n']} now (a regression record, not an estimate)")


def test_the_generalisation_estimate_is_the_unseen_set_and_its_misses_are_listed():
    r = result()
    base = json.loads(next((ROOT / "evidence" / "fabrication-benchmark").glob("*/baseline_before_round2.json")).read_text())["stress"]
    assert (base["S2"]["caught"]["k"], base["S2"]["caught"]["n"]) == (31, 42), "S2 before round 2 is frozen: 73.8%, the number first published"
    assert (base["S3"]["caught"]["k"], base["S3"]["caught"]["n"]) == (27, 38), "S3 before round 2 is frozen"
    s2, s3 = r["stress"]["S2"]["caught"], r["stress"]["S3"]["caught"]
    assert s2["k"] >= 31 and s3["k"] >= 27, "round 2 must not make either set worse than its frozen baseline"
    assert s3["k"] >= 29 and s3["n"] == 38, s3          # regression floor, deliberately below the measured value
    for key, c in (("S2", s2), ("S3", s3)):
        missed = [m for m in r["stress_missed"] if m["set"] == key]
        assert len(missed) == c["n"] - c["k"], f"every {key} miss is listed"
    print(f"  [PASS] unseen phrasings: S3 {base['S3']['caught']['k']}/{base['S3']['caught']['n']} -> {s3['k']}/{s3['n']} = {s3['rate_pct']}% "
          f"(95% interval {s3['wilson95_pct'][0]}-{s3['wilson95_pct'][1]}%); S2 {base['S2']['caught']['k']}/{base['S2']['caught']['n']} -> {s2['k']}/{s2['n']} (a regression record now)")


def test_attribution_is_measured_against_frozen_baselines_and_its_limits_are_published_with_numbers():
    r = result()
    root = ROOT / "evidence" / "fabrication-benchmark"
    base = json.loads(next(root.glob("*/baseline_before_attribution.json")).read_text())
    first = json.loads(next(root.glob("*/attribution_q_first_measurement.json")).read_text())
    assert (base["mis_attribution"]["detected"], base["mis_attribution"]["cases"]) == (0, 9), "frozen before any attribution logic existed"
    assert (base["mis_attribution_held_out"]["detected"], base["mis_attribution_held_out"]["cases"]) == (0, 15)
    assert (first["detected"]["k"], first["detected"]["n"], first["wrongly_flagged"]["k"], first["wrongly_flagged"]["n"]) == (14, 20, 1, 20), \
        "set Q as first measured, before any change made because of it: the figure to quote"
    ma, mh, aq, ca = r["mis_attribution"], r["mis_attribution_held_out"], r["attribution_q"], r["correct_attribution"]
    assert ma["detected"] >= 8 and mh["detected"] >= 14 and aq["detected"]["k"] >= 11, (ma["detected"], mh["detected"], aq["detected"])      # regression floors, below the measured values
    assert ca["wrongly_flagged"]["k"] == 0 and aq["wrongly_flagged"]["k"] == 0, (ca["flagged_cases"], aq["flagged_cases"])
    for aid, gid, sentence in B.REGRESSION_CORRECT:                                                # correct statements that once false-flagged stay unflagged
        rec = B.validate(sentence, B.build_record(aid))
        assert rec["passed"] and not rec["unverified_assertions"], (gid, rec["unverified_assertions"])
    bands = r["acceptance_bands"]["by_notation"]
    assert bands["whole lakh (Rs.4 lakh)"]["accepted_share_pct"] > bands["exact rupees (Rs.4,35,000)"]["accepted_share_pct"], "coarser notation accepts more"
    text = script.summary_markdown(r, {"run_utc": "t", "commit": "c", "dirty": False}, None, None, base, first)
    for needle in ("Attribution is checked only in unambiguous sentences", "FIRST measurement", "Coarser notation, wider acceptance", "Percentages are a soft check", "Lists, not understanding", "Wilson 95%",
                   "before the attribution check: 0/9", "On the fresh set Q it missed"):
        assert needle in text, needle
    missed = [c["id"] for c in aq["cases_detail"] if not c["detected"]]
    print(f"  [PASS] attribution: dev {ma['detected']}/9 (was 0/9), N {mh['detected']}/15 (was 0/15), fresh Q first measured {first['detected']['k']}/20 with {first['wrongly_flagged']['k']}/20 correct statements "
          f"wrongly flagged; now {aq['detected']['k']}/20 and {aq['wrongly_flagged']['k']}/20; Q misses published: {', '.join(missed)}")


def test_wilson_interval_matches_known_values():
    lo, hi = B.wilson(0, 40)
    assert lo == 0.0 and abs(hi - 0.0877) < 0.001, (lo, hi)
    lo, hi = B.wilson(154, 154)
    assert abs(lo - 0.9757) < 0.001 and hi == 1.0, (lo, hi)
    lo, hi = B.wilson(7, 40)
    assert abs(lo - 0.0875) < 0.002 and abs(hi - 0.3188) < 0.002, (lo, hi)
    print("  [PASS] Wilson 95% interval: (0/40) upper 8.8%, (154/154) lower 97.6%, (7/40) 8.8-31.9%")


TESTS = [
    test_the_faithful_bases_pass_so_a_blocked_fabrication_means_something, test_no_fabricated_amount_is_accidentally_true,
    test_nothing_true_is_blocked_and_every_in_distribution_fabrication_is, test_the_validator_improvement_is_measured_against_a_frozen_baseline_not_asserted,
    test_the_generalisation_estimate_is_the_unseen_set_and_its_misses_are_listed, test_attribution_is_measured_against_frozen_baselines_and_its_limits_are_published_with_numbers,
    test_wilson_interval_matches_known_values,
]

if __name__ == "__main__":
    raise SystemExit(Runner("Fabrication-catch benchmark (offline)").run(TESTS))
