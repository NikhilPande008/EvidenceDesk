#!/usr/bin/env python3
"""
Run the gold regulatory queries through the REAL lookup path (Cortex Search + the scope guard) and record what happened.

  python3 scripts/eval_retrieval_gold.py             # print the table and the summary
  python3 scripts/eval_retrieval_gold.py --write     # also write evidence/retrieval-gold/<UTC date>/{results.json,summary.md}

Read-only: SEARCH_PREVIEW and SELECT statements through the role in .env (use the app role). Needs Snowflake credentials.
Offline equivalent (lexical layers only, no Snowflake): tests/test_scope_guard.py.

Re-run it whenever the corpus or the search service's embedding model changes: skills/scope_guard.MIN_COSINE is calibrated
against these scores, and the holdout block (H01-H10) is how you check the calibration was not just a fit to the others.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import retrieval_gold as RG  # noqa: E402
from skills import CoPilotSkills, connection as C  # noqa: E402
from skills import scope_guard as SG  # noqa: E402


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=os.environ.get("EVAL_GIT_DIR", ROOT), capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def run_query(sk: CoPilotSkills, question: str) -> dict:
    res = sk.regulatory_lookup_with_basis(question, limit=5)
    scope = res.get("scope") or {}
    answered = bool(res["rules"])
    return {
        "decision": "answer" if answered else "abstain",
        "reason": None if answered else (scope.get("reason_code") if scope.get("status") != SG.SCOPE_IN else "NO_SOURCES"),
        "rules": [r["rule_id"] for r in res["rules"]],
        "mode": res.get("mode"),
        "cosine": scope.get("cosine"),
        "coverage": scope.get("coverage"),
        "signals": scope.get("signals"),
        "considered": scope.get("considered_rule_ids"),
    }


def summary_markdown(meta: dict, main: dict, hold: dict, rows: list[dict], hold2: dict | None = None, hold3: dict | None = None) -> str:
    miss = [r for r in rows if not r["ok"]]
    lines = [
        "# Regulatory reference: gold query run", "",
        f"- Run (UTC): {meta['run_utc']}  ·  commit `{meta['commit']}`{' (uncommitted changes present)' if meta['dirty'] else ''}",
        f"- Corpus {meta['corpus']}  ·  semantic floor `MIN_COSINE = {SG.MIN_COSINE}`  ·  lexical coverage floor `{SG.MIN_COVERAGE}`",
        f"- Path under test: `CoPilotSkills.regulatory_lookup_with_basis` (Cortex Search + scope guard) against the live account; {meta['fallback_count']} of {len(rows)} queries were served by the keyword fallback.", "",
        "## Results", "",
        "| Set | Answerable answered | Unanswerable refused | Missed (answered but should abstain) | False refusals | Expected rule in top 5 |",
        "|---|---|---|---|---|---|",
        f"| Calibration (G, X, W, K: {main['queries']} queries) | {main['in_scope_answered']}/{main['in_scope']} | {main['out_of_scope_abstained']}/{main['out_of_scope']} ({main['out_of_scope_abstain_rate_pct']}%) | {', '.join(main['wrongly_answered']) or 'none'} | {', '.join(main['false_abstentions']) or 'none'} | {main['expected_rule_hit_at_5']}/{main['in_scope']} |",
        f"| Holdout (H01-H10: {hold['queries']} queries, not used to set any threshold) | {hold['in_scope_answered']}/{hold['in_scope']} | {hold['out_of_scope_abstained']}/{hold['out_of_scope']} ({hold['out_of_scope_abstain_rate_pct']}%) | {', '.join(hold['wrongly_answered']) or 'none'} | {', '.join(hold['false_abstentions']) or 'none'} | {hold['expected_rule_hit_at_5']}/{hold['in_scope']} |",
        *([f"| Holdout 2 (J01-J25: {hold2['queries']} queries, written before the generic foreign-regime screen) | {hold2['in_scope_answered']}/{hold2['in_scope']} | {hold2['out_of_scope_abstained']}/{hold2['out_of_scope']} ({hold2['out_of_scope_abstain_rate_pct']}%) | {', '.join(hold2['wrongly_answered']) or 'none'} | {', '.join(hold2['false_abstentions']) or 'none'} | {hold2['expected_rule_hit_at_5']}/{hold2['in_scope']} |"] if hold2 else []),
        *([f"| Holdout 3 (L01-L20: {hold3['queries']} queries, written after the generic screen was built, measured once) | {hold3['in_scope_answered']}/{hold3['in_scope']} | {hold3['out_of_scope_abstained']}/{hold3['out_of_scope']} ({hold3['out_of_scope_abstain_rate_pct']}%) | {', '.join(hold3['wrongly_answered']) or 'none'} | {', '.join(hold3['false_abstentions']) or 'none'} | {hold3['expected_rule_hit_at_5']}/{hold3['in_scope']} |"] if hold3 else []),
        "", f"Known gaps in the calibration set: {main['known_gaps']}; caught: {', '.join(main['known_gaps_caught']) or 'none'}.", "",
        "## What this does and does not show", "",
        "- The queries are written by the corpus author, so this is a regression and calibration record, not an independent benchmark.",
        "- The semantic floor and the unknown-acronym rule were set or added after seeing calibration results; the holdout is the fairer number.",
        "- Questions about a foreign regime that reuse Indian STR vocabulary score high on similarity (0.5-0.65) and are caught only by the named-regime screen. Where the screen does not list the regime, the guard can miss them. Misses are listed, not hidden.", "",
        "## Misses against expectation", "",
    ]
    lines += [f"- **{r['id']}** (expected {r['expect']}, got {r['decision']}, cosine {r['cosine']}, coverage {r['coverage']}): {r['question']}" for r in miss] or ["- none"]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--write", action="store_true", help="write evidence/retrieval-gold/<UTC date>/")
    ap.add_argument("--label", help="write into evidence/retrieval-gold/<UTC date>/<label>/ (keeps a baseline beside the later run)")
    args = ap.parse_args()

    C.load_env()
    if not C.has_credentials():
        print("No Snowflake credentials found: set them in .env (see .env.example). Offline equivalent: python3 tests/test_scope_guard.py")
        return 2
    try:
        conn = C.connect_from_env()
    except Exception as err:  # noqa: BLE001
        print("Could not connect:", C.redact(str(err)).splitlines()[0][:240])
        return 2
    sk = CoPilotSkills(conn)
    gold = RG.load_gold()
    decisions: dict[str, dict] = {}
    for q in gold:
        decisions[q["id"]] = run_query(sk, q["question"])
    summary = sk.corpus_summary()
    conn.close()

    rows = []
    for q in gold:
        d = decisions[q["id"]]
        ok = d["decision"] == q["expect"] and (q["expect"] == "answer" or d["reason"] == q.get("reason") or q.get("known_gap"))
        if q.get("known_gap"):
            ok = d["decision"] == "abstain"
        rows.append({"id": q["id"], "kind": q["kind"], "expect": q["expect"], "question": q["question"], "ok": ok, **d,
                     "expected_rules": q.get("expected_rules"), "known_gap": bool(q.get("known_gap"))})
    main_gold = [q for q in gold if q["id"][0] not in "HJL"]
    hold_gold = [q for q in gold if q["id"].startswith("H")]
    hold2_gold = [q for q in gold if q["id"].startswith("J")]
    main = RG.score(main_gold, {q["id"]: decisions[q["id"]] for q in main_gold})
    hold = RG.score(hold_gold, {q["id"]: decisions[q["id"]] for q in hold_gold})
    hold2 = RG.score(hold2_gold, {q["id"]: decisions[q["id"]] for q in hold2_gold}) if hold2_gold else None
    hold3_gold = [q for q in gold if q["id"].startswith("L")]
    hold3 = RG.score(hold3_gold, {q["id"]: decisions[q["id"]] for q in hold3_gold}) if hold3_gold else None

    for r in rows:
        print(f"{'ok ' if r['ok'] else 'XX '} {r['id']:4} {r['expect'][:3]}->{r['decision'][:3]} {str(r['reason'] or ''):20} cos={r['cosine']} cov={r['coverage']} {r['mode']}")
    print(json.dumps({"calibration": main, "holdout": hold, "holdout2": hold2, "holdout3": hold3}, indent=1))

    if args.write:
        run_utc = datetime.now(timezone.utc)
        meta = {"run_utc": run_utc.strftime("%Y-%m-%d %H:%M:%SZ"), "commit": _git("rev-parse", "--short", "HEAD"), "dirty": bool(_git("status", "--porcelain")),
                "corpus": f"v{summary.get('version')} (snapshot {summary.get('snapshot_date')}, {summary.get('proven')} PROVEN, {summary.get('assumed')} ASSUMED)",
                "fallback_count": sum(1 for r in rows if r["mode"] == "keyword_fallback")}
        out = ROOT / "evidence" / "retrieval-gold" / run_utc.strftime("%Y-%m-%d") / (args.label or "")
        out.mkdir(parents=True, exist_ok=True)
        (out / "results.json").write_text(json.dumps({"meta": meta, "min_cosine": SG.MIN_COSINE, "min_coverage": SG.MIN_COVERAGE, "calibration": main, "holdout": hold, "holdout2": hold2, "holdout3": hold3, "rows": rows}, indent=1, ensure_ascii=False))
        (out / "summary.md").write_text(summary_markdown(meta, main, hold, rows, hold2, hold3))
        print(f"wrote {out.relative_to(ROOT)}/results.json and summary.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
