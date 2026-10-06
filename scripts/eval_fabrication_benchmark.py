#!/usr/bin/env python3
"""
Fabrication-catch benchmark for the deterministic evidence validator (skills/grounding.py). Offline: no model, no Snowflake.

  python3 scripts/eval_fabrication_benchmark.py                    # print the numbers
  python3 scripts/eval_fabrication_benchmark.py --write            # also write evidence/fabrication-benchmark/<UTC date>/{results.json,summary.md}
  python3 scripts/eval_fabrication_benchmark.py --write-baseline   # freeze the stress-set numbers as baseline_before_fixes.json (run BEFORE changing the validator)

The method, the narratives and the caveats are in tests/fabrication_benchmark.py. Every number is regenerated from code on each run.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import fabrication_benchmark as B  # noqa: E402


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _pct(r: dict) -> str:
    lo, hi = r["wilson95_pct"]
    return f"{r['k']}/{r['n']} ({r['rate_pct']}%, 95% interval {lo}-{hi}%)"


SET_LABELS = {
    "S": "Stress set S (regression record: round-1 fixes were written against it)",
    "S2": "Stress set S2 (regression record: its misses motivated round 2)",
    "S3": "Stress set S3 (**the estimate to quote**: written before round 2, never tuned on; 3 of its 38 phrasings are in the shapes round 2 patched)",
}


def summary_markdown(res: dict, meta: dict, baseline: dict | None, baseline2: dict | None = None, attr_baseline: dict | None = None, q_first: dict | None = None) -> str:
    f, h, s, st, ma, abx = res["faithful"], res["fabricated_hard"], res["fabricated_soft"], res["stress"], res["mis_attribution"], res["acceptance_bands"]
    L = [
        "# Fabrication-catch benchmark: deterministic evidence validator", "",
        f"- Run (UTC): {meta['run_utc']}  ·  commit `{meta['commit']}`{' (uncommitted changes present)' if meta['dirty'] else ''}",
        f"- Record: {res['record']['alert']} as seeded ({res['record']['transactions']} UPI transactions; {res['record']['derivable_amounts']} figures derivable from them: transactions, totals, subset sums, income). No model, no Snowflake.", "",
        "## Read this first", "",
        "The author wrote both the validator and these narratives. The in-distribution set mostly shows that the validator keeps catching what it was built to catch; the **stress set** is the generalisation estimate, and the **limits** below are what it cannot see. Intervals are Wilson 95%.", "",
        "## Headline numbers", "",
        "| Question | Result |", "|---|---|",
        f"| Faithful narratives wrongly blocked (hard) | {_pct(f['hard_false_positives'])} |",
        f"| Faithful narratives wrongly flagged for acknowledgement (soft) | {_pct(f['soft_flags'])} |",
        f"| Faithful narratives for the other alerts with real rows ({', '.join(f['other_alerts']['alerts'])}) wrongly blocked | {_pct(f['other_alerts']['hard_false_positives'])} |",
        f"| Fabricated narratives blocked, in-distribution ({h['narratives']} narratives, {len(h['by_class'])} claim classes) | {_pct(h['caught_any'])}; named the right class {_pct(h['caught_as_right_class'])} |",
        f"| Soft fabrications flagged for acknowledgement ({s['narratives']} narratives) | {_pct(s['flagged_for_acknowledgement'])} |",
    ]
    for key in ("S", "S2", "S3"):
        if key in st:
            L.append(f"| {SET_LABELS[key]} | {_pct(st[key]['caught'])} |")
    mh, aq, ca = res["mis_attribution_held_out"], res["attribution_q"], res["correct_attribution"]
    ab = attr_baseline or {}
    was = lambda key, n: f" (before the attribution check: {ab[key]['detected']}/{ab[key]['cases']})" if ab.get(key) else ""   # noqa: E731
    L.append(f"| Mis-attribution, development set M (every fact real, claim false; the check was built against it) | {ma['detected']}/{ma['cases']}{was('mis_attribution', 9)} |")
    L.append(f"| Mis-attribution, set N (written before the check; partly seen while designing it) | {mh['detected']}/{mh['cases']}{was('mis_attribution_held_out', 15)} |")
    if q_first:
        qd, qf = q_first["detected"], q_first["wrongly_flagged"]
        L.append(f"| **Mis-attribution, fresh set Q across alerts 01, 02, 04, 16: the FIRST measurement, never tuned (the figure to quote)** | **{_pct(qd)}**; correct statements wrongly flagged {_pct(qf)} |")
    L.append(f"| Set Q on the current code (a regression record: two changes were made after Q was first measured) | {aq['detected']['k']}/{aq['detected']['n']}; correct statements wrongly flagged {aq['wrongly_flagged']['k']}/{aq['wrongly_flagged']['n']} |")
    L.append(f"| Correctly bound statements (set P) wrongly flagged | {ca['wrongly_flagged']['k']}/{ca['wrongly_flagged']['n']} |")
    L += ["", "## In-distribution, by claim class", "", "| Class | Narratives | Blocked | Named the right class |", "|---|---|---|---|"]
    L += [f"| {k} | {v['n']} | {v['caught_any']['rate_pct']}% | {v['caught_as_right_class']['rate_pct']}% |" for k, v in h["by_class"].items()]
    L += ["", "## Stress sets, by claim class", ""]
    for key in sorted(st):
        L += [f"**Set {key}**: " + "; ".join(f"{c} {v['k']}/{v['n']}" for c, v in st[key]["by_class"].items()), ""]
    if baseline:
        b = baseline["stress"]["S"]["caught"]
        L += ["## Before and after the validator fixes", "",
              f"Stress set S, frozen before any validator change: **{b['k']}/{b['n']} caught ({b['rate_pct']}%)**. After the fixes: **{_pct(st['S']['caught'])}**. "
              "S is the set the round-1 fixes were written against, so the after-figure on S is a regression record.", ""]
    if baseline2:
        L += ["## Round 2: four pattern gaps found by S2 (`rupees 6,50,000`, non-padded ISO date, \"wired\", \"withdrew cash\")", "",
              "| Set | Before round 2 (frozen) | After round 2 |", "|---|---|---|"]
        for key in ("S2", "S3"):
            b = baseline2["stress"][key]["caught"]
            L.append(f"| {key} | {b['k']}/{b['n']} ({b['rate_pct']}%) | {_pct(st[key]['caught'])} |")
        L += ["", "S3's gain is exactly the phrasings in the patched shapes; every remaining miss is a list or meaning gap (unlisted places and companies, a wallet, an occupation, an age), not a pattern gap.", ""]
    if res["stress_missed"]:
        L += ["## Stress phrasings still not caught", ""] + [f"- **{m['id']}** ({m['cls']}, set {m['set']}): {m['sentence']}" for m in res["stress_missed"]] + [""]
    if h["missed"]:
        L += ["## In-distribution misses", ""] + [f"- **{m['id']}** ({m['cls']}): ...{m['text']}" for m in h["missed"]] + [""]
    if s["missed"]:
        L += ["## Soft fabrications not flagged, and why", "",
              "A percentage passes when it is within 0.6 points of any ratio derivable from the transactions. Fabricated figures that happen to land there are not flagged:", ""]
        L += [f"- **{m['id']}** ({m['cls']}): ...{m['text']}" for m in s["missed"]] + [""]
    qmiss = [c for c in aq["cases_detail"] if not c["detected"]]
    L += ["## Published limits", "",
          "1. **Attribution is checked only in unambiguous sentences, and only some of it.** The check (skills/attribution.py) reads one amount that is a single transaction with one named party, "
          "a direction cue, a date, a total's side, a ratio's side, \"all credits/debits\" and a flagged party. A sentence with several parties and amounts, a negation, a hypothetical, or an amount that is also a "
          "sum of transactions is skipped, not guessed at. Findings are SOFT (the officer acknowledges them before filing), because the extraction is heuristic. On the fresh set Q it missed:", ""]
    L += [f"   - {c['id']} ({c['kind']}): \"{c['sentence']}\"" for c in qmiss]
    L += ["", "   Anything outside those patterns (causal links, \"X is the largest sender\", paraphrase the cues do not read) is still accepted wherever the text places it.", ""]
    pc = abx["percentages"]
    L += [
          "2. **Coarser notation, wider acceptance.** A stated amount is accepted within half a displayed unit of any derivable figure, which is exactly a correct rounding of a record figure. The share of displayed figures accepted:", ""]
    L += [f"   - {k}: {v['accepted']}/{v['displayed_figures_tested']} ({v['accepted_share_pct']}%)" for k, v in abx["by_notation"].items()]
    L += ["", f"3. **Percentages are a soft check with a wide band.** {pc['accepted_without_a_flag']} of 99 whole percentages pass unflagged ({pc['accepted_share_pct']}%): {pc['accepted']}.",
          "4. **Lists, not understanding.** Geographies, companies and channels are matched against lists and patterns. Anything outside them is not seen (see the stress sets).",
          "5. **English, INR, India-centric.** No other language or currency is checked beyond foreign amounts being unsupported unless the record contains them.", ""]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--write-baseline", action="store_true")
    ap.add_argument("--write-attribution-baseline", action="store_true", help="freeze the attribution results as measured BEFORE any attribution logic existed")
    ap.add_argument("--write-round2-baseline", action="store_true", help="freeze stress sets S2 and S3 as measured BEFORE the second round of validator fixes")
    args = ap.parse_args()
    res = B.run()
    run_utc = datetime.now(timezone.utc)
    meta = {"run_utc": run_utc.strftime("%Y-%m-%d %H:%M:%SZ"), "commit": _git("rev-parse", "--short", "HEAD"), "dirty": bool(_git("status", "--porcelain"))}
    out = ROOT / "evidence" / "fabrication-benchmark" / run_utc.strftime("%Y-%m-%d")
    if args.write_baseline:
        out.mkdir(parents=True, exist_ok=True)
        frozen = {"meta": meta, "note": "Frozen before any change to skills/grounding.py. Stress set S only.",
                  "stress": {"S": res["stress"]["S"]}, "stress_missed": res["stress_missed"],
                  "in_distribution_caught": res["fabricated_hard"]["caught_any"], "faithful_hard_false_positives": res["faithful"]["hard_false_positives"]}
        (out / "baseline_before_fixes.json").write_text(json.dumps(frozen, indent=1, ensure_ascii=False))
        print("froze", (out / "baseline_before_fixes.json").relative_to(ROOT))
        return 0
    if args.write_attribution_baseline:
        out.mkdir(parents=True, exist_ok=True)
        frozen = {"meta": meta, "note": "Frozen before any attribution logic was added to skills/grounding.py. M = development set, N = held-out set, P = correctly bound statements.",
                  "mis_attribution": res["mis_attribution"], "mis_attribution_held_out": res["mis_attribution_held_out"], "correct_attribution": res["correct_attribution"]}
        (out / "baseline_before_attribution.json").write_text(json.dumps(frozen, indent=1, ensure_ascii=False))
        print("froze", (out / "baseline_before_attribution.json").relative_to(ROOT))
        return 0
    if args.write_round2_baseline:
        out.mkdir(parents=True, exist_ok=True)
        frozen = {"meta": meta, "note": "Frozen before the second round of changes to skills/grounding.py (the four S2 pattern gaps). Stress sets S2 and S3.",
                  "stress": {k: res["stress"][k] for k in ("S2", "S3")}, "stress_missed": [m for m in res["stress_missed"] if m["set"] in ("S2", "S3")]}
        (out / "baseline_before_round2.json").write_text(json.dumps(frozen, indent=1, ensure_ascii=False))
        print("froze", (out / "baseline_before_round2.json").relative_to(ROOT))
        return 0
    baseline_path = out / "baseline_before_fixes.json"
    baseline = json.loads(baseline_path.read_text()) if baseline_path.exists() else None
    baseline2_path = out / "baseline_before_round2.json"
    baseline2 = json.loads(baseline2_path.read_text()) if baseline2_path.exists() else None
    attr_path, q_path = out / "baseline_before_attribution.json", out / "attribution_q_first_measurement.json"
    text = summary_markdown(res, meta, baseline, baseline2, json.loads(attr_path.read_text()) if attr_path.exists() else None,
                            json.loads(q_path.read_text()) if q_path.exists() else None)
    print(text)
    if args.write:
        out.mkdir(parents=True, exist_ok=True)
        (out / "results.json").write_text(json.dumps({"meta": meta, **res}, indent=1, ensure_ascii=False))
        (out / "summary.md").write_text(text)
        print("wrote", out.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
