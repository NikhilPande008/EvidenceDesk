"""
Product positioning and the claims lint.

The application is an AML decision-defensibility and investigation copilot: signals come from other systems; it investigates, prioritises, explains and supports a
defensible disposition by a human Principal Officer, and records why. It does not detect fraud, give legal advice, file reports, verify compliance or decide.

Two checks keep that true:
  * the positioning statement is on the screens and in the README, word for word;
  * a CLAIMS LINT reads the documents and every user-facing string and fails if one ever claims autonomous detection, autonomous filing, legal advice, verified compliance
    or immutability — unless the sentence negates the claim, quotes the word, or is a documented limitation.

Offline. Usage:  python3 tests/test_positioning.py     (or pytest)
"""

from __future__ import annotations

import re

from _helpers import ROOT, Runner

from skills import po_copy as T  # noqa: E402
from skills import readiness as R  # noqa: E402

RISKY = {
    "autonomous operation": re.compile(r"\bautonomous(?:ly)?\b", re.I),
    "automatic filing": re.compile(r"\bauto-?fil(?:e|es|ed|ing)\b", re.I),
    "the application files or submits": re.compile(r"\b(?:application|copilot|system|app|product|it)\b[^.\n]{0,40}\b(?:files|submits)\b[^.\n]{0,30}\b(?:STRs?|reports?)\b", re.I),
    "detects fraud": re.compile(r"\b(?:detects?|detecting|catches|identifies)\s+(?:fraud|mule accounts?|money laundering)\b", re.I),
    "legal advice": re.compile(r"\blegal advice\b", re.I),
    "verified compliance": re.compile(r"\b(?:ensures?|guarantees?|certif(?:y|ies)|verif(?:y|ies)|proves?)\s+(?:regulatory |legal |full )?compliance\b", re.I),
    "compliant": re.compile(r"\b(?:fully|is|are)\s+(?:regulatory )?compliant\b", re.I),
    "immutable": re.compile(r"\bimmutab(?:le|ility)\b", re.I),
    "real-time detection": re.compile(r"\breal-?time (?:fraud )?detection\b", re.I),
}
NEGATION = re.compile(r"\b(?:not|no|never|neither|nor|without|cannot|can't|does not|doesn't|isn't|is not|refuse[sd]?|rather than|instead of|before the word|required before|unless)\b|n't\b|\bnone\b", re.I)
QUOTED = re.compile(r"""["“`'‘][^"”`'’]{0,40}(?:autonomous|immutab|compliant|legal advice)[^"”`'’]{0,40}["”`'’]""", re.I)

THIRD_PARTY = re.compile(r"azure immutable blob(?: storage)?|immutable blob storage", re.I)      # a cloud product's feature name, not a claim about this ledger
LINTED_DOCS = ["README.md", "SECURITY.md", "DEPLOY.md"]
LINTED_CODE = ["skills/po_copy.py", "skills/readiness.py", "skills/kpis.py", "skills/feedback.py", "skills/audit.py", "skills/prioritisation.py", "skills/evidence_quality.py",
               "skills/relationships.py", "skills/corpus_lifecycle.py", "skills/identity.py"]


def sentences(text: str):
    text = THIRD_PARTY.sub(" ", text)
    text = re.sub(r"```.*?```", " ", text, flags=re.S)                         # code blocks and diagrams are not prose
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    for chunk in re.split(r"(?<=[.!?])\s+|\n\s*\n|\n(?=\s*(?:[-*|]|\d+\.)\s)", text):
        yield " ".join(chunk.split())


def violations(text: str, source: str) -> list[str]:
    out = []
    for s in sentences(text):
        if s.rstrip().endswith("?"):                      # a question ("Is the ledger immutable?") asserts nothing
            continue
        for label, rx in RISKY.items():
            if rx.search(s) and not NEGATION.search(s) and not QUOTED.search(s):
                out.append(f"{source}: [{label}] {s[:170]}")
    return out


def test_the_lint_itself_catches_a_claim_and_accepts_a_negation():
    bad = ["The copilot autonomously files the STR.", "This system detects fraud in real time.", "It provides legal advice to officers.",
           "The ledger is immutable.", "The product is fully compliant with PMLA.", "It guarantees compliance.", "Autonomous fraud detection for banks."]
    for s in bad:
        assert violations(s, "x"), f"the lint missed: {s}"
    good = ["Is the ledger immutable?", "It does not detect fraud, give legal advice or file reports.", "No autonomous filing is claimed.", "The ledger is append-only, not immutable.",
            'Required before the word "immutable" is used about anything.', "Nothing here verifies compliance; it cannot be called fully compliant."]
    for s in good:
        assert not violations(s, "x"), f"the lint rejected a negation: {violations(s, 'x')}"
    print("  [PASS] the lint flags 7 positive claims (autonomous filing, fraud detection, legal advice, immutable, compliant, guaranteed compliance) and accepts negations and quoted mentions")


def test_the_positioning_statement_is_in_the_readme_word_for_word_and_says_what_the_product_is_not():
    readme = (ROOT / "README.md").read_text()
    for part in (T.POSITIONING_IS, T.POSITIONING_IS_NOT, T.POSITIONING_FLOW):
        assert part in readme, f"README must state: {part[:80]}…"
    assert "generated or ingested by other systems" in T.POSITIONING_IS and "investigates, prioritises, explains" in T.POSITIONING_IS and "records why" in T.POSITIONING_IS
    for denial in ("does not detect fraud", "give legal advice", "file reports", "verify regulatory compliance", "does not decide", "synthetic"):
        assert denial in T.POSITIONING_IS_NOT, denial
    assert R.POSITIONING["is"] == T.POSITIONING_IS and R.POSITIONING["is_not"] == T.POSITIONING_IS_NOT and R.POSITIONING["flow"] == T.POSITIONING_FLOW
    print("  [PASS] the README carries the three positioning sentences verbatim; the architecture module exposes the same text; the statement says signals come from elsewhere and the product does not detect, advise, file, verify or decide")


def test_the_documents_never_claim_autonomous_detection_filing_legal_advice_verified_compliance_or_immutability():
    problems = []
    for doc in LINTED_DOCS:
        problems += violations((ROOT / doc).read_text(), doc)
    assert not problems, "\n".join(problems[:12])
    print(f"  [PASS] {len(LINTED_DOCS)} documents: every sentence that mentions autonomy, auto-filing, fraud detection, legal advice, verified compliance or immutability also negates or quotes it")


def test_no_user_facing_string_makes_those_claims_either():
    problems = []
    for rel in LINTED_CODE:
        src = (ROOT / rel).read_text()
        problems += violations(src, rel)
    ui = (ROOT / "streamlit_app.py").read_text()
    literals = re.findall(r'"((?:[^"\\\n]|\\.){12,})"', ui)
    problems += violations("\n".join(literals), "streamlit_app.py")
    assert not problems, "\n".join(problems[:12])
    print(f"  [PASS] {len(LINTED_CODE)} modules and {len(literals)} string literals of the UI: no positive autonomy / detection / advice / compliance / immutability claim")


def test_the_first_screen_and_the_readme_say_who_it_is_for_what_it_replaces_what_it_needs_and_where_it_stops():
    """The relevance block: persona, current state it replaces (as an assumption), inputs it needs, scope limit. No invented figures."""
    from test_ui_states import run_app
    queue = run_app()
    shown = [str(m.value) for m in queue.markdown]
    assert T.WHO_TITLE in " ".join(shown) and all(line in shown for line in T.WHO_LINES), "the queue must open with the four lines"
    assert min(i for i, m in enumerate(shown) if m in T.WHO_LINES) < min(i for i, m in enumerate(shown) if "Judge demo path" in m), "before the demo guide"
    readme = (ROOT / "README.md").read_text()
    assert all(line in readme for line in T.WHO_LINES), "the README carries the same four lines word for word"
    text = " ".join(T.WHO_LINES)
    for word in ("Principal Officer", "global capability centre", "GCC", "email", "spreadsheets", "our assumption", "pilot", "feed", "Snowflake", "India only", "none has been measured"):
        assert word in text, word
    stripped = text.replace("7-working-day", "")
    assert not re.search(r"\d|%|\b(?:hours?|minutes?|days|crore|lakh|million|billion|per cent)\b", stripped, re.I), "no volume, saving or duration may be stated: none has been measured"
    assert not violations(text, "WHO_*")
    print("  [PASS] the first screen and the README state who it is for (Principal Officer, bank or GCC), what it replaces (as an assumption), what it needs (feed, Snowflake, corpus owner) and where it stops (India only); no figure appears in it")


def test_the_screens_that_matter_most_state_the_position():
    from test_ui_states import run_app
    queue = run_app()
    assert T.POSITIONING_IS in [c.value for c in queue.caption] and T.POSITIONING_IS_NOT in [c.value for c in queue.caption]
    arch = run_app(page="Architecture")
    assert T.POSITIONING_IS in [i.value for i in arch.info] and T.POSITIONING_FLOW in [c.value for c in arch.caption]
    print("  [PASS] My cases and Architecture & readiness both state the positioning (is / is not / flow)")


TESTS = [
    test_the_lint_itself_catches_a_claim_and_accepts_a_negation, test_the_positioning_statement_is_in_the_readme_word_for_word_and_says_what_the_product_is_not,
    test_the_documents_never_claim_autonomous_detection_filing_legal_advice_verified_compliance_or_immutability, test_no_user_facing_string_makes_those_claims_either,
    test_the_first_screen_and_the_readme_say_who_it_is_for_what_it_replaces_what_it_needs_and_where_it_stops,
    test_the_screens_that_matter_most_state_the_position,
]

if __name__ == "__main__":
    raise SystemExit(Runner("Positioning and claims lint (offline)").run(TESTS))
