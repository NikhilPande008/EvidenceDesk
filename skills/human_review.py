"""
The independent-review protocol — PURE deterministic logic (no Snowflake, no model, no clock).

Implements the backend of design/HUMAN_REVIEW_SPEC.md:

  * the provisional "first impression" read the PO records BEFORE AI advice is revealed;
  * evidence-reference resolution for the THREE allowed reference kinds
    (transaction id · current-case cited rule id · a deterministic fact key → stored snapshot);
  * the risk-adaptive `independent_review_required` trigger calculation, split into
    ALWAYS-AVAILABLE / AI-DERIVED / AI-COMPARISON classes — the no-AI path evaluates ONLY the
    always-available class and NEVER reads "no AI assessment" as "no evidence gap";
  * near-verbatim AI-draft overlap (computed only against a draft supplied at call time);
  * the `human_review` provenance object builder + a structural validator.

Everything here is a pure function over values the caller supplies. The recorder
(skills/core.py) re-runs the trigger calculation and the completeness checks server-side; the UI
is never trusted. Placing the review object INSIDE METADATA_JSON means the existing ROW_HASH
covers it with no change to the hash expression (see skills/ledger.py).

Honest limit (enforcement_scope = "normal_ui_path"): the saved timestamps are client-supplied, so
nothing here proves the officer had not already seen AI advice. The UI gates the normal path; this
module validates completeness and internal consistency only.
"""

from __future__ import annotations

import hashlib
import os
import re
from typing import Any, Iterable

from skills.ledger import is_override

# ── versions / constants ─────────────────────────────────────────────────────
HUMAN_REVIEW_SCHEMA_VERSION = 1
HUMAN_REVIEW_KEY = "human_review"
ENFORCEMENT_SCOPE = "normal_ui_path"

VIEW_SUSPICION = "SUSPICION_SUPPORTED"
VIEW_INNOCENT = "INNOCENT_EXPLANATION_SUPPORTED"
VIEW_INSUFFICIENT = "INSUFFICIENT_EVIDENCE"
PROVISIONAL_VIEWS = (VIEW_SUSPICION, VIEW_INNOCENT, VIEW_INSUFFICIENT)

FINAL_DECISIONS = ("FILE", "NOT_FILE", "DEFERRED", "ESCALATE")
_CLOSING = ("NOT_FILE", "ESCALATE")              # a decision that dismisses suspicion
_AI_WEAK = ("REVIEW", "INSUFFICIENT_EVIDENCE", "NEEDS_MANUAL_REVIEW")
_NO_AI = ("", "NOT_RUN", "NEEDS_MANUAL_REVIEW", "NONE", None)

# The ONLY fact keys that may be used as a "source-fact reference". Each resolves to a value in the
# stored evidence snapshot (fact_key_snapshot below). No arbitrary UI string is ever a reference.
FACT_KEYS = (
    "alert_amount",
    "customer_profile",
    "signal_source",
    "transaction_window",
    "flagged_counterparty_count",
    "documented_counterparty_count",
    "onward_ratio_pct",
    "credit_total",
    "debit_total",
    "transaction_count",
)

_CLIP = 500
_MAX_REFS = 20


# ── feature flag ─────────────────────────────────────────────────────────────
def enabled() -> bool:
    """Off by default. Turned on with FIU_HUMAN_REVIEW in {1,true,yes,on}. When off AND no review
    object is supplied, the recorder behaves exactly as before (backward compatible)."""
    return os.environ.get("FIU_HUMAN_REVIEW", "").strip().lower() in ("1", "true", "yes", "on")


# ── small helpers ────────────────────────────────────────────────────────────
def _clip(value: Any, n: int = _CLIP) -> str:
    s = " ".join(str(value or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _nonempty(value: Any, *, minimum: int = 1) -> bool:
    return len(str(value or "").strip()) >= minimum


# ── fact-key snapshot (the resolvable source-fact vocabulary for a case) ──────
def fact_key_snapshot(*, signal_brief: dict | None, alert_meta: dict | None) -> dict:
    """Build the fact-key → value map for a case from the deterministic signal brief
    (skills.evidence.signal_brief) and the alert metadata. Only keys with a non-None value are
    included — a key not present is simply not a resolvable reference for this case."""
    sb = signal_brief or {}
    am = alert_meta or {}
    flagged = sb.get("flagged_counterparties") or []
    documented = sb.get("documented_counterparties") or []
    window = sb.get("window")
    candidates = {
        "alert_amount": am.get("ALERT_AMOUNT_INR"),
        "customer_profile": am.get("CUSTOMER_PROFILE") or am.get("customer_profile"),
        "signal_source": am.get("SIGNAL_SOURCE"),
        "transaction_window": ("%s..%s" % (window[0], window[1])) if window else None,
        "flagged_counterparty_count": len(flagged) if sb else None,
        "documented_counterparty_count": len(documented) if sb else None,
        "onward_ratio_pct": sb.get("onward_ratio_pct"),
        "credit_total": sb.get("total_credit"),
        "debit_total": sb.get("total_debit"),
        "transaction_count": sb.get("txn_count"),
    }
    return {k: v for k, v in candidates.items() if v is not None}


class ReferenceContext:
    """What a reference is allowed to resolve against for one case. `rule_ids` MUST already exclude
    NEEDS-VERIFICATION rules (they are internal tags, never citations — their text is never exposed
    through this feature)."""

    def __init__(self, *, txn_ids: Iterable[str] | None = None, rule_ids: Iterable[str] | None = None,
                 fact_snapshot: dict | None = None):
        self.txn_ids = {str(t) for t in (txn_ids or []) if t is not None}
        self.rule_ids = {str(r) for r in (rule_ids or []) if r is not None}
        self.fact_snapshot = dict(fact_snapshot or {})

    def resolve(self, ref: Any) -> dict:
        """{ref, kind: txn|rule|fact_key|invalid, resolved: bool, value}. An unknown string is
        `invalid` and NEVER becomes a 'verified reference'. A reference proves a record EXISTS; it
        does not prove the PO's statement about it is correct."""
        r = str(ref or "").strip()
        if r and r in self.txn_ids:
            return {"ref": r, "kind": "txn", "resolved": True, "value": r}
        if r and r in self.rule_ids:
            return {"ref": r, "kind": "rule", "resolved": True, "value": r}
        if r and r in FACT_KEYS and r in self.fact_snapshot:
            return {"ref": r, "kind": "fact_key", "resolved": True, "value": self.fact_snapshot[r]}
        return {"ref": _clip(r, 60), "kind": "invalid", "resolved": False, "value": None}

    def resolve_all(self, refs: Iterable[Any]) -> list[dict]:
        return [self.resolve(x) for x in list(refs or [])[:_MAX_REFS]]

    def any_valid(self, refs: Iterable[Any]) -> bool:
        return any(r["resolved"] for r in self.resolve_all(refs))


# ── provisional read completeness ────────────────────────────────────────────
def provisional_missing(provisional: Any, ctx: ReferenceContext) -> list[str]:
    """What the provisional 'first impression' is missing (empty = complete). Required: a valid
    view; at least one resolvable evidence reference; one unanswered question."""
    missing: list[str] = []
    if not isinstance(provisional, dict):
        return ["view", "evidence_refs", "unanswered_question"]
    if provisional.get("view") not in PROVISIONAL_VIEWS:
        missing.append("view")
    if not ctx.any_valid(provisional.get("evidence_refs") or []):
        missing.append("evidence_refs")
    if not _nonempty(provisional.get("unanswered_question")):
        missing.append("unanswered_question")
    return missing


# ── reconciliation completeness (only demanded when enhanced review is required) ──
def reconciliation_missing(final_reconciliation: Any, *, disposition: str, ctx: ReferenceContext) -> list[str]:
    """What an enhanced-review reconciliation is missing (empty = complete).

    Always: a response to the most material counter-evidence (material_counter_evidence) — OR the
    explicit `none_material` marker WITH a reason in the same field; and, unless none_material, at
    least one resolvable counter_evidence_ref.
    Per final decision: FILE → why file despite the strongest reason not to; closure accepting an
    innocent explanation → the explanation + a resolvable supporting ref + remaining uncertainty;
    DEFERRED → the concrete next evidence item."""
    missing: list[str] = []
    fr = final_reconciliation if isinstance(final_reconciliation, dict) else {}
    none_material = bool(fr.get("none_material"))

    if not _nonempty(fr.get("material_counter_evidence")):
        missing.append("material_counter_evidence")
    if not none_material and not ctx.any_valid(fr.get("counter_evidence_refs") or []):
        missing.append("counter_evidence_refs")

    d = (disposition or "").upper()
    if d == "FILE":
        if not _nonempty(fr.get("change_reason")):
            missing.append("why_file_despite_counter")       # reuse change_reason as the justification
    elif d in _CLOSING:
        if _nonempty(fr.get("accepted_innocent_explanation")):
            if not ctx.any_valid(fr.get("accepted_explanation_refs") or []):
                missing.append("accepted_explanation_refs")
            if not _nonempty(fr.get("remaining_uncertainty")):
                missing.append("remaining_uncertainty")
        else:
            missing.append("accepted_innocent_explanation")
    elif d == "DEFERRED":
        if not _nonempty(fr.get("next_evidence_needed")):
            missing.append("next_evidence_needed")
    return missing


# ── independent-review trigger calculation (the three classes) ────────────────
# code → (class, one-line rationale). class ∈ {always, ai_derived, ai_comparison}.
TRIGGERS: dict[str, tuple[str, str]] = {
    "CLOSE_WITH_FLAGGED_TXN":      ("always", "closing/dismissing an alert that has a flagged counterparty in the record"),
    "TXN_RECORD_UNREADABLE":       ("always", "the transaction record is missing or could not be read"),
    "NO_SUPPORTED_REGULATORY_BASIS": ("always", "no PROVEN/ASSUMED current corpus rule supports the decision"),
    "SOURCE_OF_FUNDS_UNDOCUMENTED": ("always", "source-of-funds documentation absent where the case depends on it"),
    "UNRESOLVED_REQUIRED_RFI":     ("always", "a required red-flag indicator is unresolved"),
    "AI_EVIDENCE_GAPS":            ("ai_derived", "the AI assessment left dispositive factors on insufficient_data"),
    "AI_CHALLENGE_STRONG":         ("ai_derived", "the AI-derived counter-evidence challenge is strong"),
    "DECISION_CONTRADICTS_AI":     ("ai_comparison", "the decision contradicts a definite AI recommendation"),
    "AI_WEAK_BUT_FILES":           ("ai_comparison", "the officer files though AI returned REVIEW/insufficient"),
}


def independent_review_required(
    *,
    disposition: str,
    transactions: list[dict] | None,
    transactions_readable: bool = True,
    has_supported_basis: bool = True,
    source_of_funds_required: bool = False,
    source_of_funds_documented: bool | None = None,
    unresolved_required_rfi: bool = False,
    ai_ran: bool,
    ai_recommendation: str | None = None,
    sufficiency: dict | None = None,
    challenge: dict | None = None,
) -> dict:
    """Deterministic. Returns {required, triggers:[{code,class,detail}], classes_present}.

    HARD RULE: when `ai_ran` is False, ONLY the always-available class is evaluated. The absence of
    an AI assessment is NEVER interpreted as "no evidence gap" — AI-derived triggers are simply not
    evaluated, and `required` can still be True from the always-available class alone."""
    d = (disposition or "").upper()
    txns = transactions or []
    closing = d in _CLOSING or d == "CLOSE"
    fired: list[dict] = []

    def fire(code: str, detail: str):
        cls = TRIGGERS[code][0]
        fired.append({"code": code, "class": cls, "detail": detail})

    # ── ALWAYS-AVAILABLE (computed with no AI assessment) ──
    if not transactions_readable or transactions is None:
        fire("TXN_RECORD_UNREADABLE", "no readable transaction record for this case")
    if closing and any(t.get("is_flagged") for t in txns):
        flagged = [t.get("txn_id") for t in txns if t.get("is_flagged")]
        fire("CLOSE_WITH_FLAGGED_TXN", "flagged transactions on a closure: " + ", ".join(str(x) for x in flagged[:8]))
    if not has_supported_basis:
        fire("NO_SUPPORTED_REGULATORY_BASIS", "the corpus supplies no PROVEN/ASSUMED current rule for this decision")
    if source_of_funds_required and source_of_funds_documented is False:
        fire("SOURCE_OF_FUNDS_UNDOCUMENTED", "the case turns on source of funds and none is documented")
    if unresolved_required_rfi:
        fire("UNRESOLVED_REQUIRED_RFI", "a required red-flag indicator is unresolved")

    # ── AI-DERIVED + AI-COMPARISON (only when AI was actually run) ──
    if ai_ran:
        gaps = (sufficiency or {}).get("gaps") or []
        if gaps:
            fire("AI_EVIDENCE_GAPS", "insufficient_data factors: " + ", ".join(str(g.get("factor_id")) for g in gaps[:8]))
        if str((challenge or {}).get("strength") or (challenge or {}).get("challenge_strength") or "").lower() == "strong":
            fire("AI_CHALLENGE_STRONG", "the counter-evidence challenge to the leading call is strong")
        if is_override(ai_recommendation, d):
            fire("DECISION_CONTRADICTS_AI", f"decision {d} contradicts AI {ai_recommendation}")
        if d == "FILE" and (ai_recommendation or "").upper() in _AI_WEAK:
            fire("AI_WEAK_BUT_FILES", f"filing though AI returned {ai_recommendation}")

    return {
        "required": bool(fired),
        "triggers": fired,
        "classes_present": sorted({f["class"] for f in fired}),
        "ai_ran": bool(ai_ran),
    }


# ── near-verbatim AI-draft overlap (descriptive, never a gate) ────────────────
_WORD = re.compile(r"[a-z0-9₹]+")


def _tokens(text: str) -> list[str]:
    return _WORD.findall((text or "").lower())


def near_verbatim_overlap(ai_draft: str | None, final_text: str | None) -> float | None:
    """Fraction of the FINAL narrative's tokens that also appear in the AI draft, as a percent
    (0–100). None when either text is empty. Descriptive only: high overlap is frequently
    legitimate because the facts are shared — never a quality signal, never a gate."""
    final_tokens = _tokens(final_text or "")
    draft_tokens = set(_tokens(ai_draft or ""))
    if not final_tokens or not draft_tokens:
        return None
    shared = sum(1 for t in final_tokens if t in draft_tokens)
    return round(shared / len(final_tokens) * 100, 1)


def ai_draft_fingerprint(ai_draft: str | None, final_text: str | None) -> dict:
    """{ai_draft_hash, ai_draft_overlap_pct} computed AT RECORD TIME against the draft then in hand.
    The draft TEXT is deliberately not stored (avoid re-introducing a hostile-text / PII surface).
    When no draft is available both are None and the near-verbatim metric is DEFERRED for this row —
    it is never reconstructed from the final text."""
    if not _nonempty(ai_draft):
        return {"ai_draft_hash": None, "ai_draft_overlap_pct": None}
    return {
        "ai_draft_hash": hashlib.sha256(ai_draft.encode("utf-8")).hexdigest(),
        "ai_draft_overlap_pct": near_verbatim_overlap(ai_draft, final_text),
    }


# ── build + validate the provenance object ───────────────────────────────────
def build_human_review(
    *,
    provisional: dict | None,
    ai_reveal: dict | None,
    final_reconciliation: dict | None,
    interaction_observations: dict | None = None,
    ai_draft: str | None = None,
    final_text: str | None = None,
    review_requirement: dict | None = None,
) -> dict:
    """Assemble the versioned `human_review` object stored inside METADATA_JSON. All free text is
    clipped (hostile text is data). ai_draft/final_text are used only to compute the overlap
    fingerprint; the draft text itself is not stored."""
    prov = provisional or {}
    fr = dict(final_reconciliation or {})
    io = interaction_observations or {}
    fr_out = {
        "final_decision": str(fr.get("final_decision") or "").upper() or None,
        "changed_since_provisional": None if fr.get("changed_since_provisional") is None else bool(fr.get("changed_since_provisional")),
        "change_reason": _clip(fr.get("change_reason")) or None,
        "material_counter_evidence": _clip(fr.get("material_counter_evidence")) or None,
        "none_material": bool(fr.get("none_material")),
        "counter_evidence_refs": [_clip(r, 60) for r in (fr.get("counter_evidence_refs") or [])[:_MAX_REFS]],
        "accepted_innocent_explanation": _clip(fr.get("accepted_innocent_explanation")) or None,
        "accepted_explanation_refs": [_clip(r, 60) for r in (fr.get("accepted_explanation_refs") or [])[:_MAX_REFS]],
        "remaining_uncertainty": _clip(fr.get("remaining_uncertainty")) or None,
        "next_evidence_needed": _clip(fr.get("next_evidence_needed")) or None,
        "finalized_at": _clip(fr.get("finalized_at"), 40) or None,
        **ai_draft_fingerprint(ai_draft, final_text),
    }
    rr = review_requirement or {}
    return {
        "schema_version": HUMAN_REVIEW_SCHEMA_VERSION,
        "enforcement_scope": ENFORCEMENT_SCOPE,
        # the recorder's OWN requirement decision (server-side), stored so aggregate monitoring can use the right denominator
        "review_requirement": {"required": bool(rr.get("required")),
                               "triggers": [str(t.get("code")) for t in (rr.get("triggers") or [])][:12],
                               "classes_present": list(rr.get("classes_present") or [])},
        "provisional": {
            "view": prov.get("view") if prov.get("view") in PROVISIONAL_VIEWS else None,
            "evidence_refs": [_clip(r, 60) for r in (prov.get("evidence_refs") or [])[:_MAX_REFS]],
            "unanswered_question": _clip(prov.get("unanswered_question")) or None,
            "saved_at": _clip(prov.get("saved_at"), 40) or None,
        },
        "ai_reveal": {
            "assessment_used": bool((ai_reveal or {}).get("assessment_used")),
            "recommendation": _clip((ai_reveal or {}).get("recommendation"), 40) or None,
            "revealed_at": _clip((ai_reveal or {}).get("revealed_at"), 40) or None,
        },
        "final_reconciliation": fr_out,
        "interaction_observations": {
            "opened_transaction_detail": bool(io.get("opened_transaction_detail")),
            "opened_regulatory_basis": bool(io.get("opened_regulatory_basis")),
            "opened_counter_evidence": bool(io.get("opened_counter_evidence")),
        },
    }


def validate_human_review(obj: Any) -> list[str]:
    """Structural problems in a stored human_review object (empty = structurally valid). Tolerant of
    hostile strings (they are data); never raises; used by the recorder and by reconstruction."""
    problems: list[str] = []
    if not isinstance(obj, dict):
        return ["not an object"]
    if obj.get("schema_version") != HUMAN_REVIEW_SCHEMA_VERSION:
        problems.append("schema_version")
    if obj.get("enforcement_scope") != ENFORCEMENT_SCOPE:
        problems.append("enforcement_scope")
    prov = obj.get("provisional")
    if not isinstance(prov, dict):
        problems.append("provisional")
    else:
        if prov.get("view") is not None and prov.get("view") not in PROVISIONAL_VIEWS:
            problems.append("provisional.view")
        if not isinstance(prov.get("evidence_refs"), list):
            problems.append("provisional.evidence_refs")
    fr = obj.get("final_reconciliation")
    if not isinstance(fr, dict):
        problems.append("final_reconciliation")
    else:
        fd = fr.get("final_decision")
        if fd is not None and fd not in FINAL_DECISIONS:
            problems.append("final_reconciliation.final_decision")
        for lst in ("counter_evidence_refs", "accepted_explanation_refs"):
            if not isinstance(fr.get(lst), list):
                problems.append(f"final_reconciliation.{lst}")
        pct = fr.get("ai_draft_overlap_pct")
        if pct is not None and not isinstance(pct, (int, float)):
            problems.append("final_reconciliation.ai_draft_overlap_pct")
    if not isinstance(obj.get("ai_reveal"), dict):
        problems.append("ai_reveal")
    if not isinstance(obj.get("interaction_observations"), dict):
        problems.append("interaction_observations")
    return problems
