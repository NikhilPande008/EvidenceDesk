#!/usr/bin/env python3
"""
Render the Principal-Officer copy appendix of design/PO_WORKFLOW_SPEC.md FROM THE CODE.

  python3 scripts/render_po_copy.py            # print the appendix
  python3 scripts/render_po_copy.py --write    # rewrite it in place, between the markers in the spec
  python3 scripts/render_po_copy.py --check    # exit 1 if the spec is out of date (tests/test_po_workflow.py does the same)

Sources: skills/po_copy.py (every PO-facing sentence), skills/errors.py (error categories), skills/defensibility.py (gate registry).
The spec never hand-copies a sentence: if the product's words change, this regenerates the appendix and the test fails until it does.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skills import defensibility as D  # noqa: E402
from skills import errors as E  # noqa: E402
from skills import po_copy as T  # noqa: E402

SPEC = ROOT / "design" / "PO_WORKFLOW_SPEC.md"
START, END = "<!-- copy:start -->", "<!-- copy:end -->"

GROUPS = [
    ("A. The four zones", ["ZONES", "READ_ORDER_NOTE", "CHALLENGE_TITLE", "CHALLENGE_SUBTITLE", "CHALLENGE_NONE"]),
    ("B. Source authority — what PROVEN and ASSUMED mean", [
        "WEIGHT_LEGEND", "VERIFIED_LINE", "BASIS_HEADER", "BASIS_GRADE", "BASIS_TABLE_COLUMNS", "AUTHORITY_LABEL", "REVIEW_LABEL", "RULE_STATUS"]),
    ("C. Abstentions — the copilot declines to give regulatory guidance", [
        "ABSTAIN_BASIS_TITLE", "ABSTAIN_BASIS_BODY", "ABSTAIN_BASIS_FILE", "ABSTAIN_BASIS_OTHER", "ABSTAIN_UNAVAILABLE_TITLE", "ABSTAIN_UNAVAILABLE_BODY",
        "ABSTAIN_NO_RULES_TITLE", "ABSTAIN_LOOKUP_TITLE", "ABSTAIN_LOOKUP_BODY", "ABSTAIN_SUPERSEDED_BODY",
        "ABSTAIN_SCOPE_TITLE", "ABSTAIN_SCOPE_BODY", "ABSTAIN_WEAK_TITLE", "ABSTAIN_WEAK_BODY", "ABSTAIN_WEAK_CONSIDERED", "LOOKUP_SCOPE_CAPTION",
        "SUPERSEDED_NOTE", "NOT_IN_CORPUS_NOTE"]),
    ("D. Acknowledgements and the override reason", [
        "ACK_ASSUMED_FILE", "ACK_ASSUMED_CLOSE", "ACK_UNVERIFIED", "OVERRIDE_LABEL", "OVERRIDE_REASON_GOS", "OVERRIDE_REASON_AI", "OVERRIDE_HELP",
        "ATTRIBUTION_WARNING", "CLOCK_BASIS_FEED", "AI_DRAFT_BANNER", "ACK_AI_DRAFT", "SUPERSEDE_LABEL", "SUPERSEDE_HELP", "ALREADY_DECIDED", "PRIOR_DECISIONS_TITLE", "PRIOR_DECISIONS_UNREADABLE"]),
    ("E. The decision and the record", [
        "DECISIONS", "DECISION_PROMPT", "DECISION_NONE", "RECORD_BUTTON", "RATIONALE_LABEL", "RATIONALE_HELP", "RECORD_SUMMARY_TITLE", "RECORD_SUMMARY_FOOTER"]),
    ("F. The decision checkpoint", [
        "CHECKPOINT_TITLE", "CHECKPOINT_ROWS", "STATUS_LABEL", "STATUS_MEANING", "SUMMARY_READY", "SUMMARY_READY_NOTES", "SUMMARY_NOT_READY",
        "C1_PASS", "C1_BLOCK", "C1_NOTE", "C1_NOTE_CONTEXT", "C2_PASS", "C2_BLOCK", "C2_NOTE", "C2_SHORT", "C2_UNCHECKED",
        "C3_VALID", "C3_NOT_RUN", "C3_UNAVAILABLE", "C3_INVALID", "C4_PASS", "C4_NEEDS", "C4_ACKED", "C4_BLOCK", "C4_NOTE", "C4_BLOCK_UNAVAILABLE",
        "C4_NOTE_UNAVAILABLE", "C4_SUPERSEDED_SUFFIX", "C5_NA", "C5_NA_OTHER", "C5_NEEDS", "C5_PASS", "C6_NA", "C6_NA_OTHER", "C6_NEEDS", "C6_PASS",
        "C7_PASS", "C7_BLOCK_PO", "C7_BLOCK_OTHER", "C7_BLOCK_IDENTITY",
        "CQ_BLOCK", "CQ_NEEDS", "CQ_NEEDS_ACK", "CQ_NEEDS_REVIEW", "CQ_ACKED", "CQ_NOTE", "CR_NEEDS", "CR_PASS", "CD_NEEDS", "CD_PASS", "RESPONSIBILITY_TITLE", "RESP_REASONING", "RESP_UNCHECKABLE", "RESP_ASSUMED", "RESP_SLA", "SLA_LEFT", "SLA_OVERDUE"]),
    ("G. The same-signal pair", [
        "PAIR_TITLE", "PAIR_THESIS", "PAIR_START", "PAIR_WHY_TITLE", "PAIR_SAME", "PAIR_ONWARD", "PAIR_FLAGGED_ONE", "PAIR_FLAGGED_MANY", "PAIR_FLAGGED_NONE",
        "PAIR_DOCUMENTED", "PAIR_UNDOCUMENTED", "PAIR_CONCLUSION", "PAIR_TAG", "PAIR_UNAVAILABLE"]),
    ("H. States that are not errors", [
        "EMPTY_QUEUE", "EMPTY_FILTER", "EMPTY_LEDGER", "EMPTY_CORPUS", "NO_TRANSACTIONS", "INTEGRITY_TAMPERED", "INTEGRITY_LEGACY", "STALE_QUALITY"]),
    ("K. The first screen — who this is for", ["WHO_TITLE", "WHO_USER", "WHO_REPLACES", "WHO_NEEDS", "WHO_SCOPE"]),
    ("L. Saved model responses — chosen by the officer, labelled, re-checked", ["SAVED_ASSESSMENT_BUTTON", "SAVED_DRAFT_BUTTON", "SAVED_AVAILABLE", "SAVED_NOTICE", "SAVED_UNAVAILABLE", "SAVED_RECORDED"]),
]


def _fmt(value) -> list[str]:
    if isinstance(value, str):
        return [f"> {value}"]
    if isinstance(value, dict):
        return [f"> **{k}** — {v if isinstance(v, str) else ' · '.join(map(str, v))}" for k, v in value.items()]
    if isinstance(value, (tuple, list)):
        out = []
        for item in value:
            if isinstance(item, (tuple, list)):
                out.append("> " + " — ".join(str(x) for x in item))
            else:
                out.append(f"> {item}")
        return out
    return [f"> {value}"]


def render() -> str:
    lines: list[str] = []
    for heading, names in GROUPS:
        lines += [f"#### {heading}", ""]
        for name in names:
            lines.append(f"`{name}`")
            lines += _fmt(getattr(T, name))
            lines.append("")
    lines += ["#### I. Errors — what went wrong, in words a PO can act on", "",
              "Format: `{area} is unavailable. {title} {action} Reference: {reference}.` — the reference is `SF-<Snowflake error number>` when there is one, else `REF-<8 hex>`. "
              "The original error text is classified and logged (redacted) on the server; it is never shown.", ""]
    for category, (title, action) in E.CATEGORIES.items():
        lines += [f"`{category}`", f"> {title} {action}", ""]
    lines += ["#### J. The decision gate registry — every condition the ledger re-checks", "",
              "| Code | Severity | Applies to | Meaning |", "|---|---|---|---|"]
    for code, (severity, applies, meaning) in D.CONDITIONS.items():
        lines.append(f"| `{code}` | {severity} | {applies} | {meaning} |")
    lines.append("")
    return "\n".join(lines)


def current_block(text: str) -> str:
    return text.split(START, 1)[1].split(END, 1)[0].strip("\n")


def main() -> int:
    body = render().rstrip("\n")
    if "--write" in sys.argv or "--check" in sys.argv:
        if not SPEC.exists():
            if "--check" in sys.argv:
                print("Principal-Officer workflow specification is intentionally private and not tracked in this public repository")
                return 0
            print(f"ERROR: {SPEC} is not available for writing")
            return 1
        text = SPEC.read_text()
        if START not in text or END not in text:
            print(f"ERROR: {SPEC} lacks the {START} / {END} markers")
            return 1
        if "--check" in sys.argv:
            ok = current_block(text) == body
            print("spec copy appendix is " + ("up to date" if ok else "OUT OF DATE — run: python3 scripts/render_po_copy.py --write"))
            return 0 if ok else 1
        head, rest = text.split(START, 1)
        tail = rest.split(END, 1)[1]
        SPEC.write_text(f"{head}{START}\n{body}\n{END}{tail}")
        print(f"wrote the copy appendix into {SPEC.relative_to(ROOT)} ({len(body.splitlines())} lines)")
        return 0
    print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
