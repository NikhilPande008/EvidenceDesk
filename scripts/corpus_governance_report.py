#!/usr/bin/env python3
"""
Corpus governance report — which rules need review, which are superseded, which sources are unverified, which content is stale.

  python3 scripts/corpus_governance_report.py                 # Markdown report for the YAML corpus (domain/corpus/rules/*.yaml), no Snowflake
  python3 scripts/corpus_governance_report.py --json          # the same, machine-readable
  python3 scripts/corpus_governance_report.py --as-of 2027-01-15   # evaluate the review clocks on another date
  python3 scripts/corpus_governance_report.py --strict        # exit 2 if any rule requires review, 1 if the report finds an inconsistency

Reads only local files and never connects anywhere. The same model (skills/corpus_lifecycle.py) drives the *Corpus governance* page for the
live table. It reports what the DATA proves: a rule with no recorded review is NEVER_REVIEWED, an unapproved rule is UNAPPROVED, and
"independently verified" requires a verification date, a verifier and a verifier who is not the owner.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skills import corpus_lifecycle as CL  # noqa: E402


def load_rules() -> list[dict]:
    rules = []
    for f in sorted(glob.glob(str(ROOT / "domain/corpus/rules/*.yaml"))):
        rules += [CL.rule_from_yaml(r) for r in yaml.safe_load(open(f))["rules"]]
    return rules


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--as-of", help="YYYY-MM-DD (default: today)")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--out", help="write the report to this file instead of stdout")
    args = ap.parse_args()
    rep = CL.governance_report(load_rules(), date.fromisoformat(args.as_of) if args.as_of else date.today())
    text = json.dumps({k: v for k, v in rep.items() if k != "rules"}, indent=2, sort_keys=True, default=str) if args.json else CL.to_markdown(rep)
    if args.out:
        Path(args.out).write_text(text)
        print(f"wrote {args.out}")
    else:
        print(text)
    inconsistent = rep["counts"]["independently_verified"] > rep["counts"]["proven"] + rep["counts"]["assumed"]
    if inconsistent:
        return 1
    return 2 if (args.strict and rep["counts"]["requiring_review"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
