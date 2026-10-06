"""
The decision-defensibility gate — ONE deterministic function that decides, before anything is written, whether a
disposition may be recorded and what the Principal Officer still has to do or acknowledge.

  * the UI calls it to enable/disable the decision buttons and to list every condition;
  * the ledger recorder calls the SAME function on the SAME inputs at write time (the UI is never trusted), refuses
    to write unless `can_record`, and stores the full result + the acknowledgements in the row's provenance
    (METADATA_JSON.defensibility_gate / .acknowledgements), so an inspector can see exactly what the PO was shown.

Pure Python, no Snowflake, no model call, no clock: the same inputs always give the same result.

Severities (a code has exactly ONE severity — see CONDITIONS):
  BLOCK              cannot be recorded; nothing the PO writes or ticks can change that (fix the underlying fact)
  ACK_REQUIRED       blocks until the PO explicitly acknowledges it (recorded: satisfied=True)
  OVERRIDE_REQUIRED  blocks until the PO records a written reason of at least MIN_OVERRIDE_REASON_CHARS characters
  WARN               recorded, shown, never blocks
  INFO               recorded for the reviewer; not a warning

Status:
  BLOCKED            any BLOCK                                   → can_record False
  ACTION_REQUIRED    no BLOCK, but an ACK/OVERRIDE is unsatisfied → can_record False
  PASS_WITH_WARNINGS no BLOCK, everything required satisfied, ≥ 1 WARN → can_record True
  PASS               otherwise                                    → can_record True
"""

from __future__ import annotations

from typing import Any

from skills import po_copy as T
from skills.governance import GRADE_NO_SUPPORTED_BASIS, GRADE_UNAVAILABLE, UNUSABLE_NEEDS_VERIFICATION, UNUSABLE_SUPERSEDED
from skills.ledger import MIN_OVERRIDE_REASON_CHARS, is_override

GATE_VERSION = "1"            # unchanged: the new conditions below are additive and are evaluated only when their inputs are supplied
MIN_RATIONALE_CHARS = 20
DISPOSITIONS = ("FILE", "NOT_FILE", "ESCALATE", "DEFERRED")

BLOCK, ACK_REQUIRED, OVERRIDE_REQUIRED, WARN, INFO = "BLOCK", "ACK_REQUIRED", "OVERRIDE_REQUIRED", "WARN", "INFO"
STATUS_BLOCKED, STATUS_ACTION_REQUIRED, STATUS_PASS_WITH_WARNINGS, STATUS_PASS = (
    "BLOCKED", "ACTION_REQUIRED", "PASS_WITH_WARNINGS", "PASS")

# code → (severity, applies to, one-line meaning). The ONLY place a code's severity is defined.
CONDITIONS: dict[str, tuple[str, str, str]] = {
    "INVALID_DISPOSITION":                    (BLOCK, "all", "the disposition is not FILE / NOT_FILE / ESCALATE / DEFERRED"),
    "PO_ID_MISSING":                          (BLOCK, "all", "no Principal Officer ID — the decision cannot be attributed"),
    "RATIONALE_TOO_SHORT":                    (BLOCK, "all", f"the rationale / Ground of Suspicion is under {MIN_RATIONALE_CHARS} characters"),
    "CASE_CONTEXT_MISSING":                   (BLOCK, "FILE", "no case record to run the evidence gate against"),
    "NO_TRANSACTION_RECORD":                  (BLOCK, "FILE", "the alert has no transactions — nothing to verify the narrative against"),
    "EVIDENCE_GATE_FAILED":                   (BLOCK, "FILE", "the narrative states facts that are not in the case record"),
    "NO_SUPPORTED_REGULATORY_BASIS":          (BLOCK, "FILE", "no PROVEN or ASSUMED, current corpus rule supports a legal conclusion"),
    "REGULATORY_BASIS_UNAVAILABLE":           (BLOCK, "FILE", "the regulatory basis could not be established (corpus unreadable)"),
    "ASSUMED_RULES_IN_FILING_BASIS":          (ACK_REQUIRED, "FILE", "the filing rests partly on ASSUMED rules (implied, not verbatim)"),
    "ASSUMED_RULES_IN_CLOSURE_BASIS":         (ACK_REQUIRED, "NOT_FILE / ESCALATE", "the closure rests partly on ASSUMED rules (implied, not verbatim)"),
    "UNVERIFIED_ASSERTIONS_IN_NARRATIVE":     (ACK_REQUIRED, "FILE", "the narrative contains assertions that cannot be checked against the record"),
    "GOS_NOT_READY":                          (OVERRIDE_REQUIRED, "FILE", "the AI quality gate is not READY for this exact text"),
    "DECISION_DIFFERS_FROM_AI":               (OVERRIDE_REQUIRED, "all", "the decision contradicts the AI recommendation"),
    "UNSUPPORTED_FACTS_IN_RATIONALE":         (WARN, "non-FILE", "the rationale states facts that are not in the case record"),
    "EVIDENCE_GATE_NOT_RUN":                  (WARN, "non-FILE", "no case record was supplied, so the rationale was not fact-checked"),
    "NO_SUPPORTED_BASIS_FOR_CLOSURE":         (WARN, "non-FILE", "no PROVEN or ASSUMED, current corpus rule backs this decision"),
    "REGULATORY_BASIS_UNAVAILABLE_FOR_CLOSURE": (WARN, "non-FILE", "the regulatory basis could not be established (corpus unreadable)"),
    "SLA_OVERDUE":                            (WARN, "all", "the 7-working-day window had already elapsed at decision time"),
    "NO_AI_RECOMMENDATION":                   (WARN, "all", "no usable AI recommendation — the decision is fully human"),
    "SUPERSEDED_RULE_CITED":                  (WARN, "all", "a cited rule is superseded and was not counted as basis"),
    "BASIS_REVIEW_STALE":                     (WARN, "all", "a rule's last verification is older than the review policy"),
    # Phase 14 — evidence quality (skills/evidence_quality.py), decision-maker identity (skills/identity.py), closure reason (skills/feedback.py).
    # Each is evaluated ONLY when its input is supplied, so a caller that predates it behaves exactly as before.
    "EVIDENCE_QUALITY_BLOCKS_FILING":         (BLOCK, "FILE", "the case record has an issue that blocks a filing (for example no KYC profile, malformed rows, an amount that cannot be reconciled)"),
    "EVIDENCE_QUALITY_ISSUES_ON_CLOSURE":     (WARN, "NOT_FILE / ESCALATE", "the case record has an issue that would block a filing; the closure is recorded with this warning"),
    "EVIDENCE_QUALITY_ACK_REQUIRED":          (ACK_REQUIRED, "FILE / NOT_FILE / ESCALATE", "the case record has issues that must be acknowledged before the decision is recorded"),
    "EVIDENCE_QUALITY_MANUAL_REVIEW":         (OVERRIDE_REQUIRED, "FILE / NOT_FILE / ESCALATE", "the case record has issues the officer must check manually and say so in writing"),
    "IDENTITY_NOT_AUTHENTICATED":             (WARN, "all", "the decision-maker ID was typed, not taken from an authenticated session"),
    "PO_ID_DIFFERS_FROM_SESSION_IDENTITY":    (BLOCK, "all", "the ID being recorded is not the authenticated session identity"),
    "CLOSURE_REASON_NOT_STATED":              (WARN, "NOT_FILE / ESCALATE", "no structured closure reason was stated"),
    "AI_DRAFT_ADOPTED_VERBATIM":              (ACK_REQUIRED, "all", "the text being recorded is the AI's draft, unchanged; the officer must say it is adopted as their own statement"),
    "REPEAT_DECISION_NEEDS_REASON":           (OVERRIDE_REQUIRED, "all", "the alert already has a recorded decision; a further one needs a written reason why the earlier decision no longer stands"),
    "ASSUMED_RULES_IN_BASIS":                 (INFO, "DEFERRED", "the basis includes ASSUMED rules (a deferral concludes nothing, so no acknowledgement)"),
    "NEEDS_VERIFICATION_RULES_AS_TAGS":       (INFO, "all", "NEEDS-VERIFICATION rules are internal tags, not citations"),
    "BASIS_NOT_INDEPENDENTLY_VERIFIED":       (INFO, "all", "no cited rule has been independently re-verified against its primary source"),
}

_NO_AI = ("", "NOT_RUN", "NEEDS_MANUAL_REVIEW")
_CLIP = 160
_MAX_ITEMS = 5


def _clip(value: Any, n: int = _CLIP) -> str:
    """Bound anything that may originate from hostile text before it is stored or shown."""
    s = " ".join(str(value).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _claims(by_type: dict | None) -> dict[str, list[str]]:
    out = {}
    for k, vals in (by_type or {}).items():
        if vals:
            out[str(k)] = [_clip(v) for v in list(vals)[:_MAX_ITEMS]] + ([f"(+{len(vals) - _MAX_ITEMS} more)"] if len(vals) > _MAX_ITEMS else [])
    return out


def _fmt_claims(claims: dict[str, list[str]]) -> str:
    return "; ".join(f"{k.replace('_', ' ')}: {', '.join(v)}" for k, v in claims.items())


def _cond(code: str, message: str, satisfied: bool | None = None, detail: dict | None = None) -> dict:
    severity = CONDITIONS[code][0]
    if severity in (ACK_REQUIRED, OVERRIDE_REQUIRED):
        satisfied = bool(satisfied)
    elif severity == BLOCK:
        satisfied = False
    else:
        satisfied = None
    return {"code": code, "severity": severity, "satisfied": satisfied, "message": message, "detail": detail or {}}


def summarise(conditions: list[dict]) -> dict:
    """Status + lists derived from a condition list ONLY (also used to re-check a stored gate)."""
    blocking = [c["code"] for c in conditions if c["severity"] == BLOCK]
    pending = [c["code"] for c in conditions if c["severity"] in (ACK_REQUIRED, OVERRIDE_REQUIRED) and not c.get("satisfied")]
    warnings = [c["code"] for c in conditions if c["severity"] == WARN]
    if blocking:
        status = STATUS_BLOCKED
    elif pending:
        status = STATUS_ACTION_REQUIRED
    elif warnings:
        status = STATUS_PASS_WITH_WARNINGS
    else:
        status = STATUS_PASS
    return {"status": status, "can_record": status in (STATUS_PASS, STATUS_PASS_WITH_WARNINGS),
            "blocking_codes": blocking, "pending_codes": pending, "warning_codes": warnings,
            "info_codes": [c["code"] for c in conditions if c["severity"] == INFO],
            "satisfied_codes": [c["code"] for c in conditions if c["severity"] in (ACK_REQUIRED, OVERRIDE_REQUIRED) and c.get("satisfied")]}


def evaluate(
    *,
    disposition: str,
    rationale_text: str | None,
    has_case_context: bool,
    transaction_count: int,
    evidence_gate: dict | None,
    gos_status: str | None,
    ai_recommendation: str | None,
    regulatory_basis: dict | None,
    override_reason: str | None = None,
    unverified_claims_acknowledged: bool | None = None,
    assumed_basis_acknowledged: bool | None = None,
    sla_days_remaining: int | None = None,
    include_basis: bool = True,
    decision_maker_id: str | None = None,
    evidence_quality: dict | None = None,
    evidence_quality_acknowledged: bool | None = None,
    identity: dict | None = None,
    closure_reason_stated: bool | None = None,
    prior_decisions: list[dict] | None = None,
    supersede_reason: str | None = None,
    ai_draft_adopted_verbatim: bool | None = None,
    ai_draft_adoption_acknowledged: bool | None = None,
) -> dict:
    """Evaluate every condition for recording `disposition`. See the module docstring for the contract.

    `prior_decisions` is the ledger's earlier decisions on THIS alert, newest first (None = not looked up: no repeat-decision condition; [] = looked up,
    none exist). A non-empty list demands `supersede_reason` (≥ MIN_OVERRIDE_REASON_CHARS): the ledger is append-only, so a second decision is added after the
    first, never instead of it, and it must say why the first no longer stands.

    `evidence_quality` is skills.evidence_quality.gate_summary's result (None = not evaluated: no evidence-quality condition at all).
    `identity` is skills.identity.clean's result (None = not evaluated). `closure_reason_stated` None = not evaluated.
    `decision_maker_id=None` means "not evaluated" (older callers); a blank string is a BLOCK (PO_ID_MISSING).
    `include_basis=False` skips the regulatory-basis conditions: the recorder uses it for a first, database-free pass so a
    write that is already refused (fabricated facts, missing override …) never reads — let alone writes — anything.

    `evidence_gate` is skills.core.validate_gos_evidence's result for THIS text (None = could not be run).
    `regulatory_basis` is skills.governance.build_regulatory_basis's object (None = not established)."""
    c: list[dict] = []
    is_file = disposition == "FILE"
    reason_ok = len((override_reason or "").strip()) >= MIN_OVERRIDE_REASON_CHARS

    if disposition not in DISPOSITIONS:
        c.append(_cond("INVALID_DISPOSITION", f"Invalid disposition: {_clip(disposition, 40)}"))
    short = len((rationale_text or "").strip()) < MIN_RATIONALE_CHARS
    if short:
        c.append(_cond("RATIONALE_TOO_SHORT", f"rationale_text is mandatory and must be substantive (≥ {MIN_RATIONALE_CHARS} characters)."))
    if decision_maker_id is not None and not str(decision_maker_id).strip():
        c.append(_cond("PO_ID_MISSING", "Enter your Principal Officer ID so the decision can be attributed to you."))
    if disposition not in DISPOSITIONS:
        return _result(disposition, c, evidence_gate, regulatory_basis, unverified_claims_acknowledged, assumed_basis_acknowledged, reason_ok)

    # ── the narrative against the case record (nothing to check in a text that is already too short) ──
    if short:
        pass
    elif is_file:
        if not has_case_context or evidence_gate is None:
            c.append(_cond("CASE_CONTEXT_MISSING", "FILE requires case_context (the case record) so the evidence gate can run on the exact text being recorded."))
        elif transaction_count <= 0:
            c.append(_cond("NO_TRANSACTION_RECORD", "The alert has no transactions on record, so the narrative cannot be verified — FILE is blocked."))
        elif not evidence_gate.get("passed"):
            claims = _claims(evidence_gate.get("unsupported_claims_by_type"))
            c.append(_cond("EVIDENCE_GATE_FAILED",
                           "FILE blocked by the deterministic evidence gate — the narrative cites facts not in the case record: " + _fmt_claims(claims),
                           detail={"unsupported_claims_by_type": claims}))
    elif evidence_gate is None:
        c.append(_cond("EVIDENCE_GATE_NOT_RUN", "No case record was supplied, so this rationale was not checked against the transactions."))
    elif not evidence_gate.get("passed"):
        claims = _claims(evidence_gate.get("unsupported_claims_by_type"))
        c.append(_cond("UNSUPPORTED_FACTS_IN_RATIONALE",
                       "The rationale states facts that are NOT in the case record (recorded as written, not as verified): " + _fmt_claims(claims),
                       detail={"unsupported_claims_by_type": claims}))

    # ── regulatory basis ─────────────────────────────────────────────────────
    basis = regulatory_basis if isinstance(regulatory_basis, dict) else None
    grade = (basis or {}).get("grade")
    if not include_basis:
        pass
    elif basis is None or grade == GRADE_UNAVAILABLE:
        c.append(_cond("REGULATORY_BASIS_UNAVAILABLE" if is_file else "REGULATORY_BASIS_UNAVAILABLE_FOR_CLOSURE",
                       "The regulatory basis could not be established from the corpus" + (" — FILE is blocked." if is_file else "."),
                       detail={"error": _clip((basis or {}).get("error") or "no basis supplied")}))
    else:
        excluded = basis.get("excluded") or []
        if grade == GRADE_NO_SUPPORTED_BASIS:
            c.append(_cond("NO_SUPPORTED_REGULATORY_BASIS" if is_file else "NO_SUPPORTED_BASIS_FOR_CLOSURE",
                           "No PROVEN or ASSUMED, current corpus rule supports this decision" +
                           (" — a filing is a legal conclusion and cannot rest on nothing." if is_file else " — record it, but it has no corpus authority."),
                           detail={"excluded": excluded[:_MAX_ITEMS]}))
        elif basis.get("requires_assumed_acknowledgement"):
            ids = list(basis.get("assumed_rule_ids") or [])
            if is_file:
                c.append(_cond("ASSUMED_RULES_IN_FILING_BASIS",
                               "The filing rests partly on ASSUMED rules (" + ", ".join(ids) + ") — implied by a primary source, not stated verbatim. "
                               "Acknowledge that you are relying on them and will not present them as verified legal conclusions.",
                               satisfied=bool(assumed_basis_acknowledged), detail={"assumed_rule_ids": ids}))
            elif disposition == "DEFERRED":
                c.append(_cond("ASSUMED_RULES_IN_BASIS", "The basis includes ASSUMED rules (" + ", ".join(ids) + ").", detail={"assumed_rule_ids": ids}))
            else:                                                           # NOT_FILE / ESCALATE conclude something
                c.append(_cond("ASSUMED_RULES_IN_CLOSURE_BASIS",
                               "The closure rests partly on ASSUMED rules (" + ", ".join(ids) + ") — implied by a primary source, not stated verbatim. "
                               "Acknowledge that you are relying on them and will not present them as verified legal conclusions.",
                               satisfied=bool(assumed_basis_acknowledged), detail={"assumed_rule_ids": ids}))
        sup = [e for e in excluded if e.get("reason") == UNUSABLE_SUPERSEDED]
        if sup:
            c.append(_cond("SUPERSEDED_RULE_CITED",
                           "Superseded rule(s) cited and not counted as basis: " + ", ".join(f"{e['rule_id']} → {e.get('superseded_by')}" for e in sup),
                           detail={"superseded": [{"rule_id": e["rule_id"], "superseded_by": e.get("superseded_by")} for e in sup]}))
        if any(e.get("reason") == UNUSABLE_NEEDS_VERIFICATION for e in excluded):
            ids = [e["rule_id"] for e in excluded if e.get("reason") == UNUSABLE_NEEDS_VERIFICATION]
            c.append(_cond("NEEDS_VERIFICATION_RULES_AS_TAGS", "NEEDS-VERIFICATION rules are internal tags, never citations: " + ", ".join(ids),
                           detail={"rule_ids": ids}))
        if basis.get("stale_review_rule_ids"):
            c.append(_cond("BASIS_REVIEW_STALE", "Review of " + ", ".join(basis["stale_review_rule_ids"]) + " is older than the review policy.",
                           detail={"rule_ids": list(basis["stale_review_rule_ids"])}))
        usable = len(basis.get("proven_rule_ids") or []) + len(basis.get("assumed_rule_ids") or [])
        if usable and int(basis.get("independently_verified_count") or 0) < usable:
            c.append(_cond("BASIS_NOT_INDEPENDENTLY_VERIFIED",
                           "None of the cited rules has been independently re-verified against its primary source (PROVEN means a source is cited).",
                           detail={"usable": usable, "independently_verified": int(basis.get("independently_verified_count") or 0)}))

    # ── evidence quality: the case record's own issues ───────────────────────
    eq = evidence_quality if isinstance(evidence_quality, dict) else None
    if eq is not None:
        titles = lambda key: "; ".join(_clip(x.get("title"), 80) for x in (eq.get(key) or [])[:_MAX_ITEMS])   # noqa: E731 - static catalogue titles only
        codes_of = lambda key: [str(x.get("code")) for x in (eq.get(key) or [])][:_MAX_ITEMS * 2]             # noqa: E731
        concludes = disposition in ("FILE", "NOT_FILE", "ESCALATE")
        if eq.get("blocking") and is_file:
            c.append(_cond("EVIDENCE_QUALITY_BLOCKS_FILING", "The case record has an issue that blocks a filing: " + titles("blocking") + ".",
                           detail={"issue_codes": codes_of("blocking")}))
        elif eq.get("blocking") and disposition in ("NOT_FILE", "ESCALATE"):
            c.append(_cond("EVIDENCE_QUALITY_ISSUES_ON_CLOSURE", "A filing would be blocked on this record (" + titles("blocking") + "); the closure is recorded with this warning.",
                           detail={"issue_codes": codes_of("blocking")}))
        if concludes and eq.get("acknowledgement"):
            c.append(_cond("EVIDENCE_QUALITY_ACK_REQUIRED", "Acknowledge the evidence-quality issues before recording: " + titles("acknowledgement") + ".",
                           satisfied=bool(evidence_quality_acknowledged), detail={"issue_codes": codes_of("acknowledgement")}))
        if concludes and eq.get("manual_review"):
            c.append(_cond("EVIDENCE_QUALITY_MANUAL_REVIEW",
                           "Check these yourself and write what you did (≥" + str(MIN_OVERRIDE_REASON_CHARS) + " characters): " + titles("manual_review") + ".",
                           satisfied=reason_ok, detail={"issue_codes": codes_of("manual_review")}))

    # ── who is recording ─────────────────────────────────────────────────────
    ident = identity if isinstance(identity, dict) else None
    if ident is not None:
        if not ident.get("authenticated"):
            c.append(_cond("IDENTITY_NOT_AUTHENTICATED", "The decision-maker ID was typed and is not authenticated (production requirement: single sign-on identity).",
                           detail={"source": _clip(ident.get("source"), 20)}))
        elif decision_maker_id is not None and " ".join(str(decision_maker_id).split()).casefold() != " ".join(str(ident.get("id") or "").split()).casefold():
            c.append(_cond("PO_ID_DIFFERS_FROM_SESSION_IDENTITY", "The ID being recorded is not the authenticated session identity; a decision is recorded under the signed-in identity only.",
                           detail={"source": _clip(ident.get("source"), 20)}))
    if closure_reason_stated is False and disposition in ("NOT_FILE", "ESCALATE"):
        c.append(_cond("CLOSURE_REASON_NOT_STATED", "No structured closure reason was stated (recorded as not stated)."))

    # ── the AI's words recorded as the officer's own ─────────────────────────
    draft_unedited = bool(ai_draft_adopted_verbatim)
    if draft_unedited:
        c.append(_cond("AI_DRAFT_ADOPTED_VERBATIM",
                       "The text you are recording is the AI's draft, unchanged. Confirm that you have read it against the record and adopt it as your own statement; "
                       "it is recorded as adopted verbatim.", satisfied=bool(ai_draft_adoption_acknowledged)))

    # ── an earlier decision on the same alert ────────────────────────────────
    repeat = bool(prior_decisions)
    supersede_ok = len((supersede_reason or "").strip()) >= MIN_OVERRIDE_REASON_CHARS
    if repeat:
        latest = prior_decisions[0] if isinstance(prior_decisions[0], dict) else {}
        c.append(_cond("REPEAT_DECISION_NEEDS_REASON",
                       f"This alert already has {len(prior_decisions)} recorded decision(s); the latest is {_clip(latest.get('disposition'), 20)}. "
                       f"Record why it no longer stands (≥{MIN_OVERRIDE_REASON_CHARS} characters). The earlier decision stays in the ledger.",
                       satisfied=supersede_ok,
                       detail={"prior_count": len(prior_decisions), "latest_decision_id": _clip(latest.get("decision_id"), 40),
                               "latest_disposition": _clip(latest.get("disposition"), 20)}))

    # ── the PO's own obligations ─────────────────────────────────────────────
    if is_file:
        if evidence_gate is not None and evidence_gate.get("unverified_assertions"):
            texts = [_clip(a.get("text"), 80) for a in evidence_gate["unverified_assertions"][:3]]
            c.append(_cond("UNVERIFIED_ASSERTIONS_IN_NARRATIVE",
                           "The narrative contains assertions that cannot be verified from the case record (" + "; ".join(texts) + "). Acknowledge them explicitly before filing.",
                           satisfied=bool(unverified_claims_acknowledged),
                           detail={"count": len(evidence_gate["unverified_assertions"]), "examples": texts}))
        if gos_status != "READY":
            c.append(_cond("GOS_NOT_READY",
                           f"GoS status is {gos_status or 'NOT_CHECKED'}, not READY. Filing requires a written override_reason (≥{MIN_OVERRIDE_REASON_CHARS} characters).",
                           satisfied=reason_ok, detail={"gos_status": gos_status or "NOT_CHECKED"}))
    if is_override(ai_recommendation, disposition):
        c.append(_cond("DECISION_DIFFERS_FROM_AI",
                       f"Your decision ({disposition}) differs from the AI recommendation ({ai_recommendation}). Record why in override_reason (≥{MIN_OVERRIDE_REASON_CHARS} characters).",
                       satisfied=reason_ok, detail={"ai_recommendation": ai_recommendation, "decision": disposition}))
    if (ai_recommendation or "").upper() in _NO_AI:
        c.append(_cond("NO_AI_RECOMMENDATION", "No usable AI recommendation — this decision is fully human."))
    if sla_days_remaining is not None and sla_days_remaining < 0:
        c.append(_cond("SLA_OVERDUE", f"The 7-working-day window had already elapsed by {-sla_days_remaining} working day(s) at decision time.",
                       detail={"sla_days_remaining": int(sla_days_remaining)}))

    return _result(disposition, c, evidence_gate, regulatory_basis, unverified_claims_acknowledged, assumed_basis_acknowledged, reason_ok,
                   eq_ack=evidence_quality_acknowledged, eq_evaluated=eq is not None, supersede_ok=supersede_ok if repeat else None,
                   draft_ack=bool(ai_draft_adoption_acknowledged) if draft_unedited else None)


def _result(disposition, conditions, evidence_gate, basis, unverified_ack, assumed_ack, reason_ok, eq_ack=None, eq_evaluated=False, supersede_ok=None, draft_ack=None) -> dict:
    s = summarise(conditions)
    return {
        "gate_version": GATE_VERSION,
        "disposition": disposition if disposition in DISPOSITIONS else _clip(disposition, 40),
        **s,
        "conditions": conditions,
        # what the PO explicitly did — persisted next to the gate so the two can be read together
        "acknowledgements": {
            "unverified_claims": None if unverified_ack is None else bool(unverified_ack),
            "unverified_assertion_count": len((evidence_gate or {}).get("unverified_assertions") or []),
            "assumed_basis": None if assumed_ack is None else bool(assumed_ack),
            "assumed_rule_ids": list((basis or {}).get("assumed_rule_ids") or []) if isinstance(basis, dict) else [],
            "override_reason_recorded": bool(reason_ok),
            # present only when the case record's quality was evaluated (older rows and callers do not carry these keys)
            **({"evidence_quality": None if eq_ack is None else bool(eq_ack)} if eq_evaluated else {}),
            # present only on a decision that follows an earlier one on the same alert
            **({"supersede_reason_recorded": bool(supersede_ok)} if supersede_ok is not None else {}),
            # present only when the recorded text is the AI's draft, unchanged
            **({"ai_draft_adoption": bool(draft_ack)} if draft_ack is not None else {}),
        },
    }


def blocking_message(gate: dict) -> str:
    """One human sentence per condition that stops the write (BLOCK first, then unsatisfied ACK/OVERRIDE)."""
    msgs = [c["message"] for c in gate["conditions"] if c["severity"] == BLOCK]
    msgs += [c["message"] for c in gate["conditions"] if c["severity"] in (ACK_REQUIRED, OVERRIDE_REQUIRED) and not c.get("satisfied")]
    return "  ".join(msgs)


def gate_consistent(gate: Any) -> bool:
    """A stored gate's status/lists must follow from its own conditions (detects a hand-edited gate)."""
    if not isinstance(gate, dict) or not isinstance(gate.get("conditions"), list):
        return False
    try:
        s = summarise(gate["conditions"])
    except (KeyError, TypeError):
        return False
    return all(gate.get(k) == v for k, v in s.items()) and all(
        CONDITIONS.get(c.get("code"), (None,))[0] == c.get("severity") for c in gate["conditions"])


# ── the checkpoint: the gate, as a seven-row checklist a time-pressured PO can read ──────────────
CP_PASS, CP_NA, CP_NOTE, CP_NEEDS, CP_BLOCK = "PASS", "NA", "NOTE", "NEEDS_YOU", "BLOCK"
AI_VALID, AI_NOT_RUN, AI_INVALID, AI_UNAVAILABLE = "VALID", "NOT_RUN", "INVALID", "UNAVAILABLE"
_DECISION_LABEL = dict(T.DECISIONS) | {"ESCALATE": "Escalate"}


def _row(rid: str, status: str, detail: str, codes: list[str] | None = None) -> dict:
    return {"id": rid, "label": T.CHECKPOINT_ROWS[rid], "status": status, "status_label": T.STATUS_LABEL[status],
            "detail": detail, "codes": codes or []}


def _weights(basis: dict | None) -> str:
    b = basis or {}
    parts = []
    if b.get("proven_rule_ids"):
        parts.append("PROVEN: " + ", ".join(b["proven_rule_ids"]))
    if b.get("assumed_rule_ids"):
        parts.append("ASSUMED: " + ", ".join(b["assumed_rule_ids"]))
    return " · ".join(parts)


def checkpoint(gate: dict, *, disposition: str, ai_state: str = AI_NOT_RUN, ai_recommendation: str | None = None,
               transaction_count: int = 0, window: tuple | None = None, basis: dict | None = None,
               sla_days_remaining: int | None = None) -> dict:
    """The decision checkpoint: the gate's conditions plus the case state, as seven rows with one status each —
    PASS · NOT NEEDED · NOTE (stored, does not stop you) · NEEDS YOU (stops you until you act) · BLOCKS RECORDING (cannot be overridden).
    Pure and deterministic. Every sentence is in skills/po_copy.py. It adds no rule of its own: a row blocks only if the gate does."""
    conds = {c["code"]: c for c in gate.get("conditions", [])}
    codes = set(conds)
    is_file = disposition == "FILE"
    version = (basis or {}).get("corpus_version") or "UNKNOWN"
    snapshot = (basis or {}).get("snapshot_date") or "unknown"
    rows: list[dict] = []

    # C1 — transaction evidence
    if transaction_count > 0 and "EVIDENCE_GATE_NOT_RUN" in codes:
        rows.append(_row("C1", CP_NOTE, T.C1_NOTE_CONTEXT, ["EVIDENCE_GATE_NOT_RUN"]))
    elif transaction_count > 0:
        first, last = (window or ("?", "?"))
        rows.append(_row("C1", CP_PASS, T.C1_PASS.format(n=transaction_count, first=first, last=last)))
    elif is_file:
        rows.append(_row("C1", CP_BLOCK, T.C1_BLOCK, [c for c in ("NO_TRANSACTION_RECORD", "CASE_CONTEXT_MISSING") if c in codes]))
    else:
        rows.append(_row("C1", CP_NOTE, T.C1_NOTE))

    # C2 — narrative facts match the record
    if "RATIONALE_TOO_SHORT" in codes:
        rows.append(_row("C2", CP_BLOCK, T.C2_SHORT.format(n=MIN_RATIONALE_CHARS), ["RATIONALE_TOO_SHORT"]))
    elif transaction_count <= 0:
        rows.append(_row("C2", CP_BLOCK if is_file else CP_NOTE, T.C2_UNCHECKED))
    elif "EVIDENCE_GATE_FAILED" in codes or "UNSUPPORTED_FACTS_IN_RATIONALE" in codes:
        code = "EVIDENCE_GATE_FAILED" if "EVIDENCE_GATE_FAILED" in codes else "UNSUPPORTED_FACTS_IN_RATIONALE"
        claims = _fmt_claims(conds[code]["detail"].get("unsupported_claims_by_type") or {})
        rows.append(_row("C2", CP_BLOCK if code == "EVIDENCE_GATE_FAILED" else CP_NOTE,
                         (T.C2_BLOCK if code == "EVIDENCE_GATE_FAILED" else T.C2_NOTE).format(claims=claims), [code]))
    else:
        rows.append(_row("C2", CP_PASS, T.C2_PASS))

    # C3 — AI output valid, or explicitly not used
    if ai_state == AI_VALID:
        rows.append(_row("C3", CP_PASS, T.C3_VALID.format(rec=(ai_recommendation or "—").replace("_", " "))))
    elif ai_state == AI_INVALID:
        rows.append(_row("C3", CP_NOTE, T.C3_INVALID, ["NO_AI_RECOMMENDATION"] if "NO_AI_RECOMMENDATION" in codes else []))
    elif ai_state == AI_UNAVAILABLE:
        rows.append(_row("C3", CP_PASS, T.C3_UNAVAILABLE))
    else:
        rows.append(_row("C3", CP_PASS, T.C3_NOT_RUN))

    # C4 — regulatory basis available and labelled
    ack = next((conds[c] for c in ("ASSUMED_RULES_IN_FILING_BASIS", "ASSUMED_RULES_IN_CLOSURE_BASIS") if c in conds), None)
    unavailable = [c for c in ("REGULATORY_BASIS_UNAVAILABLE", "REGULATORY_BASIS_UNAVAILABLE_FOR_CLOSURE") if c in codes]
    nosupport = [c for c in ("NO_SUPPORTED_REGULATORY_BASIS", "NO_SUPPORTED_BASIS_FOR_CLOSURE") if c in codes]
    sup_note = ""
    if "SUPERSEDED_RULE_CITED" in conds:
        sup_note = T.C4_SUPERSEDED_SUFFIX.format(rules=", ".join(x["rule_id"] for x in conds["SUPERSEDED_RULE_CITED"]["detail"].get("superseded", [])))
    if unavailable:
        rows.append(_row("C4", CP_BLOCK if is_file else CP_NOTE, T.C4_BLOCK_UNAVAILABLE if is_file else T.C4_NOTE_UNAVAILABLE, unavailable))
    elif nosupport:
        rows.append(_row("C4", CP_BLOCK if is_file else CP_NOTE, (T.C4_BLOCK if is_file else T.C4_NOTE) + sup_note, nosupport))
    elif ack is not None and not ack["satisfied"]:
        rows.append(_row("C4", CP_NEEDS, T.C4_NEEDS.format(rules=", ".join(ack["detail"].get("assumed_rule_ids", []))) + sup_note, [ack["code"]]))
    elif ack is not None:
        rows.append(_row("C4", CP_PASS, T.C4_ACKED.format(rules=", ".join(ack["detail"].get("assumed_rule_ids", [])), version=version, snapshot=snapshot) + sup_note, [ack["code"]]))
    else:
        rows.append(_row("C4", CP_PASS, T.C4_PASS.format(weights=_weights(basis) or "No rule counted", version=version, snapshot=snapshot) + sup_note))

    # C5 — unverified statements acknowledged (a filing's narrative only)
    unv = conds.get("UNVERIFIED_ASSERTIONS_IN_NARRATIVE")
    if unv is None:
        rows.append(_row("C5", CP_NA, T.C5_NA if is_file else T.C5_NA_OTHER))
    elif unv["satisfied"]:
        rows.append(_row("C5", CP_PASS, T.C5_PASS.format(n=unv["detail"].get("count", 0)), ["UNVERIFIED_ASSERTIONS_IN_NARRATIVE"]))
    else:
        rows.append(_row("C5", CP_NEEDS, T.C5_NEEDS.format(n=unv["detail"].get("count", 0), examples="; ".join(unv["detail"].get("examples", []))),
                         ["UNVERIFIED_ASSERTIONS_IN_NARRATIVE"]))

    # C6 — override reason recorded where needed
    overrides = [conds[c] for c in ("GOS_NOT_READY", "DECISION_DIFFERS_FROM_AI") if c in conds]
    if not overrides:
        rows.append(_row("C6", CP_NA, T.C6_NA if is_file else T.C6_NA_OTHER))
    elif all(o["satisfied"] for o in overrides):
        rows.append(_row("C6", CP_PASS, T.C6_PASS, [o["code"] for o in overrides]))
    else:
        why = [T.OVERRIDE_REASON_GOS if o["code"] == "GOS_NOT_READY" else T.OVERRIDE_REASON_AI.format(ai=(ai_recommendation or "—").replace("_", " "))
               for o in overrides if not o["satisfied"]]
        rows.append(_row("C6", CP_NEEDS, T.C6_NEEDS.format(reasons="; ".join(why), n=MIN_OVERRIDE_REASON_CHARS), [o["code"] for o in overrides]))

    # CQ — evidence quality addressed. Present ONLY when the gate carries an evidence-quality condition for this decision, so a
    # decision on a record with nothing to address keeps exactly the seven rows (and a caller that predates the feature, none).
    eq_codes = [k for k in ("EVIDENCE_QUALITY_BLOCKS_FILING", "EVIDENCE_QUALITY_ISSUES_ON_CLOSURE", "EVIDENCE_QUALITY_ACK_REQUIRED", "EVIDENCE_QUALITY_MANUAL_REVIEW") if k in conds]
    if eq_codes:
        from skills.evidence_quality import CATALOG
        names = lambda code: "; ".join(CATALOG[i][1] for i in conds[code]["detail"].get("issue_codes", []) if i in CATALOG)   # noqa: E731 - static titles
        if "EVIDENCE_QUALITY_BLOCKS_FILING" in conds:
            rows.append(_row("CQ", CP_BLOCK, T.CQ_BLOCK.format(titles=names("EVIDENCE_QUALITY_BLOCKS_FILING")), ["EVIDENCE_QUALITY_BLOCKS_FILING"]))
        else:
            ack_c, rev_c = conds.get("EVIDENCE_QUALITY_ACK_REQUIRED"), conds.get("EVIDENCE_QUALITY_MANUAL_REVIEW")
            todo = ([T.CQ_NEEDS_ACK.format(titles=names("EVIDENCE_QUALITY_ACK_REQUIRED"))] if ack_c and not ack_c["satisfied"] else []) + \
                   ([T.CQ_NEEDS_REVIEW.format(titles=names("EVIDENCE_QUALITY_MANUAL_REVIEW"), n=MIN_OVERRIDE_REASON_CHARS)] if rev_c and not rev_c["satisfied"] else [])
            if todo:
                rows.append(_row("CQ", CP_NEEDS, T.CQ_NEEDS.format(needs=" and ".join(todo)), [c for c in eq_codes if c in ("EVIDENCE_QUALITY_ACK_REQUIRED", "EVIDENCE_QUALITY_MANUAL_REVIEW")]))
            elif ack_c or rev_c:
                done = [x for x in (ack_c, rev_c) if x]
                rows.append(_row("CQ", CP_PASS, T.CQ_ACKED.format(titles="; ".join(names(x["code"]) for x in done)), [x["code"] for x in done]))
            else:
                rows.append(_row("CQ", CP_NOTE, T.CQ_NOTE.format(titles=names("EVIDENCE_QUALITY_ISSUES_ON_CLOSURE")), ["EVIDENCE_QUALITY_ISSUES_ON_CLOSURE"]))

    # CD — the AI's draft adopted unchanged. Present ONLY then.
    adopt = conds.get("AI_DRAFT_ADOPTED_VERBATIM")
    if adopt is not None:
        rows.append(_row("CD", CP_PASS, T.CD_PASS, ["AI_DRAFT_ADOPTED_VERBATIM"]) if adopt["satisfied"] else _row("CD", CP_NEEDS, T.CD_NEEDS, ["AI_DRAFT_ADOPTED_VERBATIM"]))

    # CR — an earlier decision on this alert. Present ONLY when the alert already has one, so a first decision keeps exactly the seven rows.
    rep = conds.get("REPEAT_DECISION_NEEDS_REASON")
    if rep is not None:
        if rep["satisfied"]:
            rows.append(_row("CR", CP_PASS, T.CR_PASS, ["REPEAT_DECISION_NEEDS_REASON"]))
        else:
            rows.append(_row("CR", CP_NEEDS, T.CR_NEEDS.format(n=rep["detail"].get("prior_count", 1), latest=rep["detail"].get("latest_disposition") or "—",
                                                               chars=MIN_OVERRIDE_REASON_CHARS), ["REPEAT_DECISION_NEEDS_REASON"]))

    # C7 — ledger record ready. It summarises the rows above: it BLOCKS only for a missing PO ID, an ID that is not the signed-in identity, or
    # when something above blocks; if the decision is only waiting on the PO (an acknowledgement, a reason) it says NEEDS YOU — it never
    # contradicts the summary line.
    c7_own = False
    if "PO_ID_MISSING" in codes:
        rows.append(_row("C7", CP_BLOCK, T.C7_BLOCK_PO, ["PO_ID_MISSING"]))
        c7_own = True
    elif "PO_ID_DIFFERS_FROM_SESSION_IDENTITY" in codes:
        rows.append(_row("C7", CP_BLOCK, T.C7_BLOCK_IDENTITY, ["PO_ID_DIFFERS_FROM_SESSION_IDENTITY"]))
        c7_own = True
    elif gate.get("can_record"):
        rows.append(_row("C7", CP_PASS, T.C7_PASS.format(version=version)))
    elif gate.get("blocking_codes"):
        rows.append(_row("C7", CP_BLOCK, T.C7_BLOCK_OTHER))
    else:
        rows.append(_row("C7", CP_NEEDS, T.C7_BLOCK_OTHER))

    body = rows[:-1]                       # C1–C6 (+ CQ when present); C7 is a roll-up, counted only when IT is the reason (PO ID / identity)
    own = body + ([rows[-1]] if c7_own else [])
    blocks = sum(1 for r in own if r["status"] == CP_BLOCK)
    needs = sum(1 for r in body if r["status"] == CP_NEEDS)
    notes = sum(1 for r in rows if r["status"] == CP_NOTE)
    ready = bool(gate.get("can_record"))
    if ready:
        summary = T.SUMMARY_READY_NOTES.format(notes=notes) if notes else T.SUMMARY_READY
    else:
        summary = T.SUMMARY_NOT_READY.format(blocks=blocks, needs=needs)

    resp = [T.RESP_REASONING, T.RESP_UNCHECKABLE]
    if (basis or {}).get("assumed_rule_ids") and disposition != "DEFERRED":
        resp.append(T.RESP_ASSUMED)
    if sla_days_remaining is not None:
        resp.append(T.RESP_SLA.format(sla=(T.SLA_LEFT.format(n=sla_days_remaining) if sla_days_remaining >= 0 else T.SLA_OVERDUE.format(n=-sla_days_remaining))))
    return {"disposition": disposition, "label": _DECISION_LABEL.get(disposition, disposition), "rows": rows, "ready": ready,
            "blocks": blocks, "needs": needs, "notes": notes, "summary": summary, "responsibility": resp}
