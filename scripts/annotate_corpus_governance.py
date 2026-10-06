"""
annotate_corpus_governance.py — add explicit governance metadata to every corpus rule.

Inserts (text-level, preserving comments/formatting) after each rule's `evidence_level:` line:

    source_authority  who the primary source is (STATUTE / RBI_DIRECTION / FIU_IND_GUIDANCE / …)
    corpus_version    version of the corpus release that contains this rule (manifest.yaml)
    review_status     DRAFT (NEEDS-VERIFICATION) | AUTHOR_ASSERTED — never VERIFIED by default
    owner             accountable maintainer
    verified_by       reviewer who re-checked the live source (null until someone does)
    superseded_by     rule ID / instrument that replaces this rule (null if current)
    replaces          instrument this rule replaces (e.g. STR-006 replaces FINnet direct upload)

`last_verified` (existing field) is the verified date. Idempotent: rules that already carry
`source_authority` are skipped. Run:  python3 scripts/annotate_corpus_governance.py [--dry-run]
"""
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from skills.governance import classify_authority, default_review_status  # noqa: E402

RULES = sorted((ROOT / "domain/corpus/rules").glob("*.yaml"))
MANIFEST = yaml.safe_load((ROOT / "domain/corpus/manifest.yaml").read_text())
OWNER = MANIFEST["owner"]
VERSION = MANIFEST["corpus_version"]
REPLACES = {"STR-006": "FINnet direct-upload mechanism"}
# Explicit authority overrides where the classifier would overstate provenance (DG-19).
AUTHORITY_OVERRIDE = {"POE-001": "PRODUCT_COMPILED"}


def main(dry: bool) -> int:
    changed = 0
    for path in RULES:
        data = yaml.safe_load(path.read_text())
        meta = {r["id"]: r for r in data["rules"]}
        lines, out, rid, done = path.read_text().splitlines(keepends=True), [], None, set()
        for line in lines:
            out.append(line)
            m = re.match(r"^  - id:\s*(\S+)", line)
            if m:
                rid = m.group(1)
            if re.match(r"^    evidence_level:", line) and rid and rid not in done:
                r = meta[rid]
                done.add(rid)
                if "source_authority" in r:
                    continue
                authority = AUTHORITY_OVERRIDE.get(rid) or classify_authority((r.get("primary_source") or {}).get("document"))
                if authority == "UNCLASSIFIED":
                    print(f"ERROR: cannot classify authority for {rid}", file=sys.stderr)
                    return 1
                repl = REPLACES.get(rid)
                out.extend([
                    f"    source_authority: {authority}\n",
                    f"    corpus_version: \"{VERSION}\"\n",
                    f"    review_status: {default_review_status(r['evidence_level'])}\n",
                    f"    owner: \"{OWNER}\"\n",
                    "    verified_by: null\n",
                    "    superseded_by: null\n",
                    f"    replaces: {json.dumps(repl) if repl else 'null'}\n",
                ])
                changed += 1
                print(f"  {rid:8s} {r['evidence_level']:19s} {authority:22s} <- {(r.get('primary_source') or {}).get('document','')[:70]}")
        if not dry and any(True for _ in done):
            path.write_text("".join(out))
    print(f"\n{'would annotate' if dry else 'annotated'} {changed} rule(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main("--dry-run" in sys.argv))
