#!/usr/bin/env python3
"""
Run the REAL model over every seeded alert through the same code the hosted app uses, and record what came back.

  python3 scripts/eval_live_replay.py                       # print the table and the summary
  python3 scripts/eval_live_replay.py --write               # also write evidence/live-replay/<UTC date>/{results.json,summary.md}
  python3 scripts/eval_live_replay.py --alerts ALERT-01,ALERT-16 --no-draft
  python3 scripts/eval_live_replay.py --write --write-saved         # also turn this run's replies into skills/saved_responses_data.py
  python3 scripts/eval_live_replay.py --saved-from evidence/live-replay/<date>   # build that module from an earlier run (no Snowflake)

For each alert: load the alert and its transactions from Snowflake (as the app does), call suspicion_evaluator (11-factor assessment,
one Cortex Complete call), check every triggered factor against the record, then call ground_of_suspicion_writer (the draft narrative
plus its quality-check call) and run the deterministic evidence gate over the draft. Nothing is written to Snowflake: no decision is
recorded, no ledger row is added. Every Cortex call costs credits and takes tens of seconds.

What it measures (synthetic data, one model, n = the seeded alerts, every figure is a count over that n and nothing more):
  * how often the model output was valid JSON for all 11 factors;
  * how many factors it called triggered, and how many of those the record supports (grounded);
  * what the evidence sufficiency summary recommended, set beside the scenario author's label;
  * how many draft narratives passed the hard evidence gate first time, and how many unsupported facts the gate found in those that did not;
  * seconds per call.

What it cannot show: accuracy against real cases (the labels are one author's), or that the gate catches every unsupported fact (that is
tests/fabrication_benchmark.py's job, with its own intervals). The author who wrote the alerts also wrote the labels.

Run it as the APP role (SNOWFLAKE_ROLE=FIU_APP_ROLE) so it exercises exactly the grants the hosted app has. The labels are read from the
seed module in this repository, never from Snowflake: the app role cannot read them and this script does not try.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import setup_alerts as seed  # noqa: E402
from skills import CoPilotSkills, connection as C  # noqa: E402
from skills import core as K  # noqa: E402


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=os.environ.get("EVAL_GIT_DIR", ROOT), capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _recorded(sk: CoPilotSkills) -> list[dict]:
    """Wrap the Cortex call so every prompt's hash, the model that answered, the seconds and the raw text are kept."""
    calls: list[dict] = []
    real = sk._cortex_complete

    def record(prompt: str, **kw) -> str:
        t0 = time.monotonic()
        out = real(prompt, **kw)
        calls.append({"prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(), "model": sk.last_model_used,
                      "seconds": round(time.monotonic() - t0, 1), "response_chars": len(out or ""), "raw_response": out,
                      "usage": sk.last_usage, "decoding": sk.last_decoding})
        return out

    sk._cortex_complete = record          # instance attribute: this object only
    return calls


def run_alert(sk: CoPilotSkills, calls: list[dict], alert_id: str, draft: bool) -> dict:
    alert = sk.load_alert(alert_id)
    txns = sk.load_transactions(alert_id)
    rec: dict = {"alert_id": alert_id, "label": seed.GOLD_LABELS.get(alert_id), "n_transactions": len(txns)}
    if not alert or not txns:
        return {**rec, "skipped": "no alert or no transactions in the environment"}
    ctx = sk.case_context_for(alert, txns)               # the call the app makes
    mark = len(calls)
    try:
        assessment = sk.suspicion_evaluator(ctx)
    except Exception as err:  # noqa: BLE001
        return {**rec, "error": C.redact(str(err)).splitlines()[0][:200]}
    validity = sk.assessment_validity(assessment)
    summ = sk.evidence_sufficiency_summary(assessment, ctx["transactions"])
    trig = [f for f in assessment if f.get("assessment") == "triggered"]
    rec.update({
        "assessment_valid": bool(validity["valid"]), "assessment_error": validity.get("error"),
        "model": calls[mark]["model"] if len(calls) > mark else None,
        "assessment_seconds": calls[mark]["seconds"] if len(calls) > mark else None,
        "assessment_tokens": (calls[mark].get("usage") or {}).get("total_tokens") if len(calls) > mark else None,
        "assessment_decoding": calls[mark].get("decoding") if len(calls) > mark else None,
        "assessment_prompt_sha256": calls[mark]["prompt_sha256"] if len(calls) > mark else None,
        "triggered": len(trig), "triggered_grounded": sum(1 for f in trig if f.get("grounded") is not False),
        "triggered_ungrounded": [{"factor_id": f["factor_id"], "issues": f.get("grounding_issues", {})} for f in trig if f.get("grounded") is False],
        "clear": sum(1 for f in assessment if f.get("assessment") == "clear"),
        "insufficient": sum(1 for f in assessment if f.get("assessment") == "insufficient_data"),
        "recommendation": summ["recommendation"], "grounded_nexus_factors": summ.get("grounded_nexus_factors", []),
        "discounted_nexus_factors": summ.get("discounted_nexus_factors", []),
        "recommendation_before_record_check": sk.evidence_sufficiency_summary(assessment)["recommendation"],
        "factors": [{k: f.get(k) for k in ("factor_id", "assessment", "grounded", "evidence_txn_ids")} for f in assessment],
    })
    if not draft or not validity["valid"]:
        return rec
    mark = len(calls)
    try:
        gos = sk.ground_of_suspicion_writer(ctx, assessment)
    except Exception as err:  # noqa: BLE001
        rec["draft_error"] = C.redact(str(err)).splitlines()[0][:200]
        return rec
    rec["draft"] = {
        "status": gos.get("status"), "hard_gate_passed": bool(gos.get("hard_gate_passed")), "quality_score": gos.get("quality_score"),
        "unsupported_facts": gos.get("unsupported_facts", []), "unsupported_claims_by_type": gos.get("unsupported_claims_by_type", {}),
        "unverified_assertions": gos.get("unverified_assertions", []), "hard_gate_failure": gos.get("hard_gate_failure", ""),
        "narrative_words": len((gos.get("narrative") or "").split()), "narrative": gos.get("narrative", ""),
        "repair": gos.get("repair"), "first_draft_passed_hard_gate": not gos.get("repair") and bool(gos.get("hard_gate_passed")),
        "calls": [{k: c.get(k) for k in ("prompt_sha256", "model", "seconds", "usage", "decoding")} for c in calls[mark:]],
    }
    return rec


def summarise(rows: list[dict]) -> dict:
    done = [r for r in rows if "assessment_valid" in r]
    drafted = [r for r in done if "draft" in r]
    trig = sum(r["triggered"] for r in done if r["assessment_valid"])
    grounded = sum(r["triggered_grounded"] for r in done if r["assessment_valid"])
    table = Counter((r["label"], r["recommendation"]) for r in done if r["assessment_valid"])
    secs = [r["assessment_seconds"] for r in done if r.get("assessment_seconds") is not None]
    draft_secs = [sum(c["seconds"] for c in r["draft"]["calls"]) for r in drafted]
    return {
        "alerts_run": len(done), "alerts_skipped_or_failed": len(rows) - len(done),
        "assessment_valid": sum(1 for r in done if r["assessment_valid"]),
        "triggered_factors": trig, "triggered_grounded": grounded,
        "label_by_recommendation": {f"{a} -> {b}": n for (a, b), n in sorted(table.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1])))},
        "drafts": len(drafted), "drafts_passing_hard_gate": sum(1 for r in drafted if r["draft"]["hard_gate_passed"]),
        "drafts_passing_hard_gate_first_time": sum(1 for r in drafted if r["draft"].get("first_draft_passed_hard_gate")),
        "repairs_attempted": sum(1 for r in drafted if (r["draft"].get("repair") or {}).get("attempted")),
        "repairs_that_passed": sum(1 for r in drafted if (r["draft"].get("repair") or {}).get("repaired")),
        "drafts_with_unsupported_facts": sum(1 for r in drafted if r["draft"]["unsupported_facts"]),
        "unsupported_facts_total": sum(len(r["draft"]["unsupported_facts"]) for r in drafted),
        "drafts_with_unverified_assertions": sum(1 for r in drafted if r["draft"]["unverified_assertions"]),
        "assessment_seconds": {"median": sorted(secs)[len(secs) // 2] if secs else None, "max": max(secs) if secs else None},
        "draft_seconds_both_calls": {"median": sorted(draft_secs)[len(draft_secs) // 2] if draft_secs else None, "max": max(draft_secs) if draft_secs else None},
        "models": sorted({r["model"] for r in done if r.get("model")}),
    }


def render_summary(meta: dict, s: dict, rows: list[dict]) -> str:
    L = [f"# Live model replay over the seeded alerts — {meta['date']}", "",
         "**Synthetic data. One model. Counts over the seeded alerts; none of this is accuracy on real cases.**", "",
         f"- Code: commit `{meta['git_commit']}`{' + uncommitted changes' if meta['git_dirty'] else ''}; prompt version `{meta['prompt_version']}`; "
         f"corpus read from the environment below; environment: `{meta['environment']}`; role: `{meta['role']}`.",
         f"- Model requested: `{meta.get('model_requested')}`{' (no fallback model allowed)' if meta.get('no_fallback') else ''}; model(s) that answered: "
         f"{', '.join(f'`{m}`' for m in s['models']) or '—'}. Decoding: temperature {meta.get('temperature')}, structured outputs "
         f"{'on' if meta.get('structured_outputs') else 'off'}. Nothing was recorded to the ledger.", "",
         "## Result", "",
         f"- Assessments valid (all 11 factors parsed): **{s['assessment_valid']} of {s['alerts_run']}**" + (f" ({s['alerts_skipped_or_failed']} alerts skipped or failed)" if s["alerts_skipped_or_failed"] else "") + ".",
         f"- Factors the model called *triggered*: **{s['triggered_factors']}**, of which the record supports **{s['triggered_grounded']}** (grounded).",
         f"- Drafts written: **{s['drafts']}**; passing the hard evidence gate: **{s['drafts_passing_hard_gate']}** "
         f"(first draft: **{s['drafts_passing_hard_gate_first_time']}**; one-shot repair tried on **{s['repairs_attempted']}**, passed on **{s['repairs_that_passed']}**); "
         f"drafts containing at least one unsupported fact: **{s['drafts_with_unsupported_facts']}** ({s['unsupported_facts_total']} facts in total); "
         f"drafts with unverified assertions listed for the officer: **{s['drafts_with_unverified_assertions']}**.",
         f"- Seconds: assessment median {s['assessment_seconds']['median']}, max {s['assessment_seconds']['max']}; "
         f"draft plus quality check median {s['draft_seconds_both_calls']['median']}, max {s['draft_seconds_both_calls']['max']}.", "",
         "## Recommendation beside the scenario author's label", "",
         "| Label (author) | Recommendation | Alerts |", "|---|---|---|"]
    for k, n in s["label_by_recommendation"].items():
        a, b = k.split(" -> ")
        L.append(f"| {a} | {b} | {n} |")
    L += ["", "FILE / NOT_FILE labels are the author's expectation; CONTESTED means the scenario has no pre-determined answer. "
          "REVIEW and INSUFFICIENT_EVIDENCE are the application declining to recommend, which is not an error.", "",
          "## Per alert", "", "| Alert | Label | Recommendation | Triggered | Grounded | Draft | Hard gate | Unsupported facts | Model | Assessment s |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if "assessment_valid" not in r:
            L.append(f"| {r['alert_id']} | {r.get('label')} | — | — | — | — | — | {r.get('skipped') or r.get('error') or ''} | — | — |")
            continue
        d = r.get("draft")
        L.append(f"| {r['alert_id']} | {r['label']} | {r['recommendation'] if r['assessment_valid'] else 'invalid output'} | {r['triggered']} | {r['triggered_grounded']} | "
                 f"{d['status'] if d else '—'} | {('pass' if d['hard_gate_passed'] else 'BLOCKED') if d else '—'} | {len(d['unsupported_facts']) if d else '—'} | "
                 f"{r.get('model') or '—'} | {r.get('assessment_seconds') if r.get('assessment_seconds') is not None else '—'} |")
    L += ["", "## How to read this", "",
          "- The assessment and the draft come from the live model; every check after them is deterministic and runs against the record in the environment.",
          "- A draft that fails the hard gate is the gate working: the officer would be told which fact is unsupported before anything is recorded.",
          "- The same author wrote the alerts, the labels and the validator. The fabrication benchmark (`evidence/fabrication-benchmark/`) is where the gate's own catch rate is measured.", ""]
    return "\n".join(L)


def saved_entries(rows: list[dict], raw_by_hash: dict, captured_at: str) -> dict:
    """The replies worth saving: a VALID 11-factor assessment, and a draft with BOTH of its calls (the draft and its quality check).
    Anything the model got wrong in a way that failed parsing is not offered as a shortcut."""
    wanted: list[str] = []
    for r in rows:
        if r.get("assessment_valid") and r.get("assessment_prompt_sha256"):
            wanted.append(r["assessment_prompt_sha256"])
        d = r.get("draft")
        if d and d.get("narrative_words") and len(d.get("calls", [])) == 2:
            wanted += [c["prompt_sha256"] for c in d["calls"]]
    out = {}
    for h in wanted:
        c = raw_by_hash.get(h)
        if c and c.get("raw_response") and c.get("model"):
            out[h] = {"model": c["model"], "captured_at": captured_at, "raw_response": c["raw_response"]}
    return out


def saved_from_folders(spec: str) -> dict:
    """Saved replies from one evidence folder or several (comma-separated). When two runs saved the same prompt, the folder named first wins."""
    entries: dict = {}
    for part in spec.split(","):
        src = Path(part.strip())
        res = json.loads((src / "results.json").read_text())
        raw = json.loads((src / "raw_responses.json").read_text())
        for h, e in saved_entries(res["alerts"], raw, res["meta"]["generated_at_utc"]).items():
            entries.setdefault(h, e)
    return entries


def write_saved_module(entries: dict) -> Path:
    path = ROOT / "skills" / "saved_responses_data.py"
    body = ('"""GENERATED by `python3 scripts/eval_live_replay.py --write-saved` (or --saved-from) from a real run. Do not edit by hand.\n'
            'Keys are SHA-256 of the exact prompt text; see skills/saved_responses.py."""\n\n'
            f"SAVED: dict = {json.dumps(entries, indent=1, ensure_ascii=False)}\n")
    path.write_text(body)
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--alerts", help="comma-separated alert ids (default: every alert in the environment)")
    ap.add_argument("--no-draft", action="store_true", help="assessment only (halves the Cortex calls)")
    ap.add_argument("--write", action="store_true", help="write evidence/live-replay/<UTC date>/{results.json,summary.md}")
    ap.add_argument("--write-saved", action="store_true", help="also write this run's valid replies to skills/saved_responses_data.py")
    ap.add_argument("--label", help="write into evidence/live-replay/<UTC date>/<label>/ instead of the date folder itself (for model comparisons)")
    ap.add_argument("--saved-from", help="build skills/saved_responses_data.py from an earlier run's evidence folder (or several, comma-separated), then exit (no Snowflake)")
    args = ap.parse_args()
    if args.saved_from:
        entries = saved_from_folders(args.saved_from)
        print(f"wrote {write_saved_module(entries)}: {len(entries)} saved replies from {args.saved_from}")
        return 0
    C.load_env()
    if not C.has_credentials():
        print("No Snowflake credentials: set them in .env (see .env.example), preferably with the app role.")
        return 2
    try:
        conn = C.connect_from_env()
    except Exception as err:  # noqa: BLE001
        print("Could not connect:", C.redact(str(err)).splitlines()[0][:240])
        return 2
    sk = CoPilotSkills(conn)
    calls = _recorded(sk)
    cur = conn.cursor()
    cur.execute("SELECT CURRENT_ROLE(), CURRENT_DATABASE()")
    role, db = cur.fetchone()
    cur.close()
    ids = [a.strip() for a in args.alerts.split(",")] if args.alerts else [r["ALERT_ID"] for r in sk._execute("SELECT ALERT_ID FROM FIU_COPILOT.AML.ALERTS_CURRENT ORDER BY ALERT_ID")]
    rows = []
    for aid in ids:
        r = run_alert(sk, calls, aid, draft=not args.no_draft)
        rows.append(r)
        d = r.get("draft")
        draft_cell = (d["status"] + ("" if d["hard_gate_passed"] else " BLOCKED") + " unsupported=" + str(len(d["unsupported_facts"]))) if d else "—"
        print(f"{aid}: label={r.get('label')} rec={r.get('recommendation', '—')} triggered={r.get('triggered', '—')} grounded={r.get('triggered_grounded', '—')} "
              f"draft={draft_cell} {r.get('error') or r.get('skipped') or ''}", flush=True)
    conn.close()
    s = summarise(rows)
    meta = {"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "git_commit": _git("rev-parse", "--short", "HEAD") or "unknown", "git_dirty": bool(_git("status", "--porcelain")), "prompt_version": K.PROMPT_VERSION,
            "environment": db, "role": role, "draft": not args.no_draft, "label": args.label,
            "model_requested": K.CORTEX_MODEL, "no_fallback": K.NO_MODEL_FALLBACK, "temperature": K.COMPLETE_TEMPERATURE,
            "structured_outputs": K.STRUCTURED_OUTPUTS}
    text = render_summary(meta, s, rows)
    print("\n" + text)
    if args.write:
        out = ROOT / "evidence" / "live-replay" / meta["date"] / (args.label or "")
        out.mkdir(parents=True, exist_ok=True)
        (out / "results.json").write_text(json.dumps({"meta": meta, "summary": s, "alerts": rows, "calls": [{k: v for k, v in c.items() if k != "raw_response"} for c in calls]}, indent=2, default=str) + "\n")
        (out / "summary.md").write_text(text)
        (out / "raw_responses.json").write_text(json.dumps({c["prompt_sha256"]: {"model": c["model"], "seconds": c["seconds"], "raw_response": c["raw_response"]} for c in calls}, indent=1) + "\n")
        print(f"\nwrote {out}/results.json, summary.md, raw_responses.json")
        if args.write_saved:
            raw = {c["prompt_sha256"]: c for c in calls}
            entries = saved_entries(rows, raw, meta["generated_at_utc"])
            print(f"wrote {write_saved_module(entries)}: {len(entries)} saved replies")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
