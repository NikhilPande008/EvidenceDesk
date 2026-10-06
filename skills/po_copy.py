"""
Exact Principal-Officer-facing copy — the single source.

Everything a PO reads in the decision workflow that carries a *commitment* (an abstention, an acknowledgement, a decision
gate, a warning) lives here, not scattered through the UI. design/PO_WORKFLOW_SPEC.md quotes it verbatim: the spec's copy
appendix is RENDERED from this module (scripts/render_po_copy.py) and tests/test_po_workflow.py fails if the two differ.

Voice: plain, second person, short. A PO under an SLA clock reads the first sentence and acts. No stack traces, no SQL, no
developer commands. Never "we recommend" / "the AI decided" — the system assesses, the PO decides (design/UI_PRINCIPLES.md).
Pure strings and `.format()` templates: no imports, no side effects.
"""

from __future__ import annotations

# ── the four zones ───────────────────────────────────────────────────────────
ZONES = {
    "facts": ("SOURCE FACTS", "Computed from the transaction table. No AI is involved."),
    "basis": ("REGULATORY BASIS", "What the regulatory corpus says, and how sure it is."),
    "ai":    ("AI INFERENCE", "A proposal from a language model. Not a fact, and not your decision."),
    "human": ("HUMAN DECISION", "Yours. This is what gets recorded."),
}
CHALLENGE_TITLE = "WHAT ARGUES AGAINST THE LEADING CALL"
CHALLENGE_SUBTITLE = "Read this before you decide. If it does not change your mind, say why in your rationale."
CHALLENGE_NONE = "Nothing in the record argues against the leading call."
READ_ORDER_NOTE = "Read the source facts first. The AI inference below is optional and comes after the evidence."

# ── PROVEN / ASSUMED in plain language ───────────────────────────────────────
WEIGHT_LEGEND = {
    "PROVEN": "PROVEN — a primary source is cited by the corpus author. We have not re-checked it ourselves.",
    "ASSUMED": "ASSUMED — implied by a primary source but not stated word for word. Do not present it as verified law.",
    "NEEDS-VERIFICATION": "NEEDS-VERIFICATION — an internal tag only. Its text is never shown or used, and it never counts as a basis.",
}
VERIFIED_LINE = "{verified} of {usable} usable rules have been independently verified against their primary source."
BASIS_HEADER = "Corpus v{version} · snapshot {snapshot}"
BASIS_GRADE = {
    "PROVEN_ONLY": "Every rule this decision rests on is PROVEN.",
    "INCLUDES_ASSUMED": "This decision rests partly on ASSUMED rules. You must acknowledge that before you record it.",
}
BASIS_TABLE_COLUMNS = ("Rule", "Weight", "Authority", "Review", "Status")
AUTHORITY_LABEL = {
    "STATUTE": "Statute",
    "RBI_DIRECTION": "RBI direction",
    "FIU_IND_GUIDANCE": "FIU-IND guidance",
    "FIU_IND_PUBLICATION": "FIU-IND publication",
    "INTERNATIONAL_STANDARD": "International standard",
    "INDUSTRY_PRACTICE": "Industry practice",
    "PRODUCT_COMPILED": "Product-compiled, not a regulator's text",
    "UNCLASSIFIED": "Unclassified",
}
REVIEW_LABEL = {
    "AUTHOR_ASSERTED": "Author-asserted, not re-verified",
    "DRAFT": "Draft",
    "VERIFIED": "Independently verified",
    "STALE": "Verification out of date",
}
RULE_STATUS = {
    "counts": "Counts as basis",
    "NEEDS_VERIFICATION": "Tag only — does not count",
    "SUPERSEDED": "Superseded by {successor} — does not count",
    "NOT_IN_CORPUS": "Not in the corpus — does not count",
    "UNKNOWN_EVIDENCE_LEVEL": "Unknown weight — does not count",
}

# ── abstentions: the copilot declines to give regulatory guidance ────────────
ABSTAIN_BASIS_TITLE = "No supported regulatory basis"
ABSTAIN_BASIS_BODY = ("The corpus has no PROVEN or ASSUMED rule that applies to this alert. The copilot abstains: it will not say what the law "
                      "requires here. Check the primary source, or ask your compliance counsel.")
ABSTAIN_BASIS_FILE = "A filing is a legal conclusion, so FILE is blocked."
ABSTAIN_BASIS_OTHER = "You can still record a deferral or a closure. It will be stored with a warning that it has no corpus authority."
ABSTAIN_UNAVAILABLE_TITLE = "Regulatory basis unavailable"
ABSTAIN_UNAVAILABLE_BODY = ("The corpus could not be read, so the copilot cannot say what applies. It abstains until the corpus is available. "
                            "FILE is blocked. You can still record a deferral or a closure; it will carry a warning.")
ABSTAIN_NO_RULES_TITLE = "This alert cites no corpus rules"
ABSTAIN_LOOKUP_TITLE = "No supported answer"
ABSTAIN_LOOKUP_BODY = ("No PROVEN or ASSUMED rule in the corpus matches this question. The copilot abstains and gives no regulatory guidance. "
                       "Rephrase the question, or consult the primary source or your compliance counsel.")
ABSTAIN_SUPERSEDED_BODY = ("Every matching rule has been superseded and the corpus holds no current replacement. The copilot abstains and gives "
                           "no regulatory guidance. Consult the primary source or your compliance counsel.")
ABSTAIN_SCOPE_TITLE = "Outside this corpus"
ABSTAIN_SCOPE_BODY = ("This corpus covers India only: PMLA 2002 and FIU-IND and RBI guidance for banks and financial institutions. "
                      "It has no rules for {subject}, so the copilot gives no regulatory guidance and shows no rules. {redirect}")
ABSTAIN_WEAK_TITLE = "No rule answers this question"
ABSTAIN_WEAK_BODY = ("The closest corpus rules share too little with the question to answer it, so the copilot shows none of them and gives "
                     "no regulatory guidance. Rephrase the question, or consult the primary source or your compliance counsel.")
ABSTAIN_WEAK_CONSIDERED = "Rules considered and not shown: {rules}."
LOOKUP_SCOPE_CAPTION = ("Scope: India only (PMLA 2002, and FIU-IND and RBI guidance for banks and financial institutions). These rules answer questions "
                        "about that regime, not another jurisdiction's. If your question is about another regime, they do not answer it.")
SUPERSEDED_NOTE = "{rule} is superseded by {successor}. It is not counted as a basis."
NOT_IN_CORPUS_NOTE = "{rule} is not in the corpus. It is not counted as a basis."

# ── acknowledgements the PO must give ────────────────────────────────────────
ACK_ASSUMED_FILE = ("I understand this filing rests partly on ASSUMED rules ({rules}). They are implied by a primary source, not stated word for "
                    "word. I take responsibility for relying on them and will not present them as verified law.")
ACK_ASSUMED_CLOSE = ("I understand this closure rests partly on ASSUMED rules ({rules}). They are implied by a primary source, not stated word for "
                     "word. I take responsibility for relying on them and will not present them as verified law.")
ACK_UNVERIFIED = "I have checked the unverified statements above myself and take responsibility for them."
OVERRIDE_LABEL = "Why are you proceeding? (at least {n} characters)"
OVERRIDE_REASON_GOS = "The AI quality check did not mark your narrative READY"
OVERRIDE_REASON_AI = "Your decision differs from the AI's ({ai})"
OVERRIDE_HELP = "This is recorded with the decision and read by anyone who reconstructs it."
# The suspicion clock, when the time came from the case feed rather than from a recorded decision.
CLOCK_BASIS_FEED = "Suspicion time supplied by the case feed, not yet confirmed in a recorded decision; Mon–Fri, no holiday calendar."
# The text attaches a real fact to the wrong party, direction, date or side (skills/attribution.py).
ATTRIBUTION_WARNING = ("**The record attaches these facts differently.** Each fact is in the record, but not as the sentence puts it. "
                       "Correct the sentence, or acknowledge it before filing:")
# The AI's draft recorded as the officer's own words.
AI_DRAFT_BANNER = ("This text is the AI's draft, unchanged: not yet your words. Read it against the record and rewrite it in your own words. "
                   "If you adopt it as it stands, you confirm that below.")
ACK_AI_DRAFT = "I have read this AI draft against the record and adopt it as my own statement."
CD_NEEDS = "The text is the AI's draft, unchanged. Edit it into your own words, or tick the confirmation below that you adopt it as your own."
CD_PASS = "You confirmed that you adopt the AI's draft as your own statement. The record says it was adopted verbatim."
# A further decision on an alert that already has one (the ledger is append-only: the earlier decision is never changed or removed).
SUPERSEDE_LABEL = "Why does the earlier decision no longer stand? (at least {n} characters)"
SUPERSEDE_HELP = "An alert can be decided more than once. The earlier decision is never changed or removed: this one is added after it, with your reason."
CR_NEEDS = "This alert already has {n} recorded decision(s); the latest is {latest}. Write why that decision no longer stands (at least {chars} characters). Both stay in the ledger."
CR_PASS = "Your reason for superseding the earlier decision is recorded with this one. Both stay in the ledger."
ALREADY_DECIDED = ("A decision is already recorded for this alert: {disposition}, {when}. You can read it in the Decision Ledger. "
                   "Recording another needs a written reason, and the ledger keeps both.")
PRIOR_DECISIONS_TITLE = "Earlier decisions on this alert ({n})"
PRIOR_DECISIONS_UNREADABLE = "The earlier decisions on this alert could not be read. A new decision cannot be recorded until they can."

# ── the decision ─────────────────────────────────────────────────────────────
DECISIONS = (("FILE", "File STR"), ("DEFERRED", "Defer — more evidence needed"), ("NOT_FILE", "Close — no suspicion formed"))
DECISION_PROMPT = "Your decision"
DECISION_NONE = "Choose a decision to see exactly what it needs before it can be recorded."
RECORD_BUTTON = "Record: {label}"
RATIONALE_LABEL = "Your Ground of Suspicion (to file) or your reason (to defer or close)"
RATIONALE_HELP = "Write this yourself. An AI draft is a starting point, never the record."
RECORD_SUMMARY_TITLE = "You are about to record"
RECORD_SUMMARY_FOOTER = "This record is append-only in this app: it cannot be edited or deleted here."

# ── the checkpoint ───────────────────────────────────────────────────────────
CHECKPOINT_TITLE = "Decision checkpoint — {label}"
CHECKPOINT_ROWS = {
    "C1": "Transaction evidence available",
    "C2": "Narrative facts match the record",
    "C3": "AI output valid, or explicitly not used",
    "C4": "Regulatory basis available and labelled",
    "C5": "Unverified statements acknowledged",
    "C6": "Override reason recorded where needed",
    "C7": "Ledger record ready",
    "CQ": "Evidence quality addressed",     # shown only when the case record has an issue that gates this decision
    "CR": "Earlier decision on this alert",  # shown only when the alert already has a recorded decision
    "CD": "AI draft adopted as your own",    # shown only when the recorded text is the AI's draft, unchanged
}
STATUS_LABEL = {"PASS": "PASS", "NA": "NOT NEEDED", "NOTE": "NOTE", "NEEDS_YOU": "NEEDS YOU", "BLOCK": "BLOCKS RECORDING"}
STATUS_MEANING = {
    "PASS": "Met.",
    "NA": "Does not apply to this decision.",
    "NOTE": "Does not stop you. It is stored with the decision.",
    "NEEDS_YOU": "Stops you until you act (tick, or write a reason).",
    "BLOCK": "Stops you. Fix the underlying fact; you cannot override it.",
}
SUMMARY_READY = "Ready to record. Nothing blocks this decision."
SUMMARY_READY_NOTES = "Ready to record. Notes stored with the decision: {notes}."
SUMMARY_NOT_READY = "Not ready. Blocking recording: {blocks}. Needing your action: {needs}."

C1_PASS = "{n} transactions on record, {first} to {last}."
C1_BLOCK = "No transactions on record. A filing cannot be checked against nothing."
C1_NOTE = "No transactions on record. Your rationale could not be checked against the record."
C1_NOTE_CONTEXT = "The case record was not available. Your rationale was not checked against it."
C2_PASS = "No unsupported facts were detected by the pattern checks. Matching values or IDs does not verify a whole sentence, its causal claims, or your conclusion."
C2_BLOCK = "These are not in the case record: {claims}. Remove or correct them. You cannot override this for a filing."
C2_NOTE = "These are not in the case record: {claims}. They will be recorded as written and marked unsupported."
C2_SHORT = "Write your rationale first (at least {n} characters)."
C2_UNCHECKED = "Cannot be checked: there is nothing to check it against."
C3_VALID = "The AI assessed this alert: {rec}. You decide. If you disagree, give your reason below."
C3_NOT_RUN = "You have not used the AI assessment. This decision will be recorded as fully human (AI: NOT_RUN)."
C3_UNAVAILABLE = "The AI was unavailable. You can still decide. This will be recorded as fully human (AI: NOT_RUN)."
C3_INVALID = "The AI output was invalid and has been withheld. This decision will be recorded as NEEDS_MANUAL_REVIEW."
C4_PASS = "{weights}. Corpus v{version}, snapshot {snapshot}."
C4_NEEDS = "Includes ASSUMED rules ({rules}). Tick the acknowledgement below."
C4_ACKED = "ASSUMED rules acknowledged ({rules}). Corpus v{version}, snapshot {snapshot}."
C4_BLOCK = "No PROVEN or ASSUMED rule supports this decision. The copilot abstains. A filing cannot rest on nothing."
C4_NOTE = "No PROVEN or ASSUMED rule supports this decision. It will be recorded with a warning that it has no corpus authority."
C4_BLOCK_UNAVAILABLE = "The corpus could not be read, so the basis cannot be established. A filing is blocked until it can."
C4_NOTE_UNAVAILABLE = "The corpus could not be read, so the basis cannot be established. This decision will carry a warning."
C4_SUPERSEDED_SUFFIX = " Superseded and not counted: {rules}."
C5_NA = "No unverifiable statements found."
C5_NA_OTHER = "Not required for this decision."
C5_NEEDS = "{n} statement(s) cannot be checked against the record: {examples}. Tick the acknowledgement below."
C5_PASS = "You acknowledged {n} unverified statement(s)."
C6_NA = "Not needed: your decision matches the AI and the quality check is READY."
C6_NA_OTHER = "Not needed: your decision is consistent with the AI."
C6_NEEDS = "{reasons}. Write why you are proceeding (at least {n} characters)."
C6_PASS = "Your reason is recorded with the decision."
C7_PASS = ("Will be written: your PO ID, your rationale, a fingerprint of the evidence, the regulatory basis (corpus v{version}), this checkpoint's "
           "result and your acknowledgements — sealed with a SHA-256 row hash.")
C7_BLOCK_PO = "Enter your Principal Officer ID."
C7_BLOCK_OTHER = "Resolve the items above first."
C7_BLOCK_IDENTITY = "The ID being recorded is not your signed-in identity. A decision is recorded under the signed-in identity only."

CQ_BLOCK = "A filing cannot be recorded while these stand: {titles}. Fix the underlying record; you cannot override this."
CQ_NEEDS = "Before you record: {needs}."
CQ_NEEDS_ACK = "tick that you have read the evidence-quality issues ({titles})"
CQ_NEEDS_REVIEW = "check {titles} yourself and write what you did (at least {n} characters)"
CQ_ACKED = "Evidence-quality issues addressed: {titles}."
CQ_NOTE = "Recorded with a warning, because a filing would be blocked on this record: {titles}."

RESPONSIBILITY_TITLE = "What stays your responsibility"
RESP_REASONING = "The checks compare facts with the record. They do not check your reasoning or your judgement."
RESP_UNCHECKABLE = "Anything the checks cannot verify is yours: interpretations, third-party characterisations and inferences about people."
RESP_ASSUMED = "ASSUMED rules are the corpus author's reading of a source, not verified law."
RESP_SLA = "The 7-working-day STR clock: {sla}."
SLA_LEFT = "{n} working day(s) left"
SLA_OVERDUE = "overdue by {n} working day(s)"

# ── the same-signal pair ─────────────────────────────────────────────────────
PAIR_TITLE = "Same signal, different evidence"
PAIR_THESIS = "A detector firing tells you the money moved in a suspicious shape. Whether the shape is suspicious depends on the evidence behind it."
PAIR_START = "Start with either alert. Both open on the source facts, not on an AI answer."
PAIR_WHY_TITLE = "Why equal signals do not mean equal dispositions"
PAIR_SAME = "Same detection rule ({rule}), same signal source ({source}), same alert amount ({amount})."
PAIR_ONWARD = "{alert}: {debits} ({ratio}%) of the {credits} received was sent onward."
PAIR_FLAGGED_ONE = "{alert}: {amount} ({share}% of credits) went to {n} flagged counterparty ({names})."
PAIR_FLAGGED_MANY = "{alert}: {amount} ({share}% of credits) went to {n} flagged counterparties ({names})."
PAIR_FLAGGED_NONE = "{alert}: no flagged counterparty received any of it."
PAIR_DOCUMENTED = "{alert}: {documented} of {total} counterparties are documented ({names})."
PAIR_UNDOCUMENTED = "{alert}: none of the {total} counterparties is documented."
PAIR_CONCLUSION = "The rule fired equally. The record differs, so the defensible decisions differ."
PAIR_TAG = "same-signal pair with {other}"
PAIR_UNAVAILABLE = "The comparison needs both alerts' transactions, and they could not be loaded."

# ── states that are not errors ───────────────────────────────────────────────
EMPTY_QUEUE = "No alerts are loaded. Ask your administrator to load the alert feed."
EMPTY_FILTER = "No alerts match these filters. Clear a filter to see more."
EMPTY_LEDGER = "No decisions have been recorded yet. Your first decision will appear here."
EMPTY_CORPUS = "The regulatory corpus is empty. The copilot abstains from regulatory guidance until it is loaded."
NO_TRANSACTIONS = "No transactions are on record for this alert. A filing cannot be checked against nothing, so FILE is blocked. You can still defer or close with a reason."
INTEGRITY_TAMPERED = ("{n} ledger row(s) failed their integrity check. They may have been edited after they were written. Do not rely on them: "
                      "tell your system owner and keep a copy of this screen.")
INTEGRITY_LEGACY = "{n} older row(s) predate integrity sealing and cannot be verified."
STALE_QUALITY = "You edited the text after the last AI quality check. It counts as not checked until you re-check."

# ── independent-review protocol (feature-flagged: FIU_HUMAN_REVIEW) ───────────
# These sentences are NOT in the PO_WORKFLOW_SPEC exact-copy appendix yet (the protocol UI is a new,
# flag-gated increment — see design/HUMAN_REVIEW_SPEC.md). They are rendered only when the flag is on.
HR_PROVISIONAL_TITLE = "First impression"
HR_PROVISIONAL_FRAMING = ("First impression — provisional and expected to change after further evidence. "
                          "Record your current view before AI advice is shown.")
HR_VIEWS = {
    "SUSPICION_SUPPORTED": "Suspicion supported",
    "INNOCENT_EXPLANATION_SUPPORTED": "Innocent explanation supported",
    "INSUFFICIENT_EVIDENCE": "Insufficient evidence",
}
HR_PROVISIONAL_REF_LABEL = "At least one piece of evidence that informs this view (pick a transaction, a cited rule, or a source fact)"
HR_PROVISIONAL_Q_LABEL = "One question or uncertainty you still have"
HR_PROVISIONAL_SAVE = "Save first impression"
HR_PROVISIONAL_REVISE = "Revise first impression"
HR_PROVISIONAL_SAVED = "First impression saved. You may revise it until you reveal AI advice. Changing it later is expected, not an error."
HR_AI_LOCKED = ("AI advice is held back until you record your first impression above. This is deliberate — it keeps your "
                "initial read your own. It is not a judgement of your view, and you can revise that view before revealing AI.")
HR_RECONCILE_TITLE = "Reconcile before you record"
HR_RECONCILE_WHY = "This decision is higher-risk, so it needs an evidence-linked reconciliation:"
HR_RECONCILE_COUNTER = "Your response to the most material point against this decision"
HR_RECONCILE_NONE_MATERIAL = "None of the listed points is material (say why in the box above)"
HR_RECONCILE_FILE_JUSTIFY = "Why you file despite the strongest reason not to"
HR_RECONCILE_ACCEPTED = "The innocent explanation you accept, and the supplied evidence for it"
HR_RECONCILE_UNCERTAINTY = "What remains uncertain"
HR_RECONCILE_NEXT = "The concrete next evidence needed"
HR_RECONCILE_REF_LABEL = "A supplied reference that supports this (transaction / cited rule / source fact)"
HR_RECONCILE_INCOMPLETE = "Complete the reconciliation above to enable recording."
HR_RECON_SECTION = "Independent review (recorded)"
HR_RECON_PROVISIONAL = "First impression (before AI): {view} · refs: {refs} · open question: {q}"
HR_RECON_AI = "AI revealed: {used} · recommendation: {rec}"
HR_RECON_FINAL = "Final: {decision} · changed since first impression: {changed}"
HR_RECON_ENFORCEMENT = ("Scope: the order was enforced in the normal UI path only. The saved times are client-supplied; this is "
                        "not cryptographic proof the officer had not already seen AI advice.")


# ── product positioning (what this application is, and is not) ───────────────
# One statement, used by the queue page, the architecture page and the README (tests/test_positioning.py keeps them in step).
POSITIONING_TITLE = "What this application is"
POSITIONING_IS = ("An AML decision-defensibility and investigation copilot. Fraud and mule-risk signals are generated or ingested by other "
                  "systems; this application investigates, prioritises, explains and supports a defensible disposition by a Principal "
                  "Officer, and records why.")
POSITIONING_IS_NOT = ("It does not detect fraud, give legal advice, file reports or verify regulatory compliance, and it does not decide: "
                      "a human Principal Officer decides. All data shown here is synthetic.")
POSITIONING_FLOW = ("Signal from another system → prioritised case → evidence and regulatory basis → optional AI proposal → "
                    "Principal Officer decision → decision record.")

# ── who this is for (the first screen; plain words, no volume and no time-saved figure) ──
# Every figure that could be quoted here would be invented: none has been measured. tests/test_positioning.py keeps the screen, the README
# and this text in step, and fails if a number, a percentage or a duration appears in it.
WHO_TITLE = "Who this is for"
WHO_USER = ("**Who it is for.** The Principal Officer, and the financial-crime operations team that prepares each decision, in a bank's India operations "
            "or in a global capability centre (GCC) that works its alerts. For every alert someone must decide whether to report it to FIU-IND, and later show why.")
WHO_REPLACES = ("**What it replaces (our assumption; a pilot would confirm it).** The reasoning lives in email, spreadsheets and free-text case notes, "
                "where it is hard to show afterwards what the officer saw, what a model suggested and what was checked.")
WHO_NEEDS = ("**What it needs.** A feed of alerts and their transactions from your detection system, a Snowflake account with the roles in DEPLOY.md, "
             "and a named owner for the regulatory corpus. The feed may also say when suspicion was formed; that starts the 7-working-day clock.")
WHO_SCOPE = ("**Where it stops.** India only (PMLA, PML Rules, FIU-IND, RBI). A GCC often serves several regimes; a question about another one is screened and usually "
             "declined, not guessed, and every lookup shows its scope. No time-saved figure is claimed, because none has been measured.")
WHO_LINES = (WHO_USER, WHO_REPLACES, WHO_NEEDS, WHO_SCOPE)

# ── saved model responses (the officer asks for them; they are never substituted silently) ──
SAVED_ASSESSMENT_BUTTON = "Load the saved assessment (no wait)"
SAVED_DRAFT_BUTTON = "Load the saved draft (no wait)"
SAVED_AVAILABLE = ("A real model reply captured {when} by {model} matches this case exactly. Loading it sends nothing to a model; every check after it "
                   "runs again now, against the record as it stands.")
SAVED_NOTICE = ("This is a saved model response captured {when} by {model}, not generated now. The checks on it ran just now against the current record.")
SAVED_UNAVAILABLE = ("No saved response matches this case as it stands, because the record, the corpus or the prompt has changed since one was captured. "
                     "Run it live.")
SAVED_RECORDED = "AI output: a saved model response captured {when} by {model} ({parts}); not generated at the time of the decision."

# ── case priority ────────────────────────────────────────────────────────────
PRIORITY_COLUMN = "Priority"
PRIORITY_CAPTION = "Priority orders the work. It is not a risk rating and not a recommendation to file; you decide separately."
PRIORITY_WHY_TITLE = "Why this case is prioritized"
PRIORITY_UNAVAILABLE = "Priority could not be computed (the transaction record is unavailable), so cases are shown in recorded-deadline, then oldest-first order."
SORT_OPTIONS = ("Recorded deadline, then priority", "Priority score only", "Oldest first", "Largest amount")
SORT_LABEL = "Sort by"

# ── evidence quality ─────────────────────────────────────────────────────────
EQ_TITLE = "Evidence quality"
EQ_SUBTITLE = ("What is missing, stale, contradictory, unavailable or unresolved in this case's record, and what each issue means for your decision.")
EQ_NONE = "None of the checks found an issue. That does not mean the record is complete: see what these checks cannot see."
EQ_POLICY_NOTE = "What each issue means is this product's policy, not a regulatory requirement."
EQ_LIMITS_TITLE = "What these checks cannot see"
EQ_NEXT_TITLE = "Recommended next evidence"
EQ_NEXT_NOTE = "Suggested investigation steps — not conclusions. You decide which, if any, to take."
EQ_TEXT_PATTERN_NOTE = "Detected from free text by pattern; confirm it in the source record."
ACK_EVIDENCE_QUALITY = ("I have read the evidence-quality issues listed for this case ({titles}) and take responsibility for deciding on this "
                        "record despite them.")
OVERRIDE_REASON_EQ = "The record has issues that need your own check"

# ── relationships ────────────────────────────────────────────────────────────
REL_TITLE = "Relationships and network"
REL_SUBTITLE = "Who is connected to this case, and how we know. Sourced links are stated by the record; inferred links are rule matches computed here."
REL_NOT_TESTED_TITLE = "Link types that cannot be tested with the data supplied"
REL_INFERRED_NOTE = "An inferred link is a rule match, not a finding and not entity resolution."

# ── decision-maker identity ──────────────────────────────────────────────────
ID_SESSION = "Signed in as {who} (Snowflake session identity). This cannot be edited."
ID_TYPED = ("Typed by you and not authenticated. Production requirement: bind the decision-maker to the single-sign-on identity so it cannot be "
            "typed.")
ID_RECORDED_NOTE = "The database also stamps the Snowflake user and role that wrote the row."

# ── feedback capture ─────────────────────────────────────────────────────────
FB_REASON_LABEL = "Closure reason (structured, optional)"
FB_REASON_NONE = "— not stated —"
FB_REASON_HELP = "Used for monitoring only. It never changes how cases are prioritised or what the gate allows."
FB_NOTE = "Feedback is used for monitoring and future calibration only. Nothing here retrains a model or changes a policy."
