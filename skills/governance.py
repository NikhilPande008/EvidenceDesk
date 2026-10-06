"""
Regulatory-corpus governance: what may be shown as PROVEN, what must carry a warning,
what is superseded, and what has never been independently verified.

Pure functions (no Snowflake) so every rule is unit-testable offline. The database supplies
rows (REGULATORY_CORPUS + governance columns); this module decides how they are presented.

Vocabulary
  evidence_level   PROVEN | ASSUMED | NEEDS-VERIFICATION           (existing claim-audit tag)
  source_authority STATUTE | RBI_DIRECTION | FIU_IND_GUIDANCE | FIU_IND_PUBLICATION |
                   INTERNATIONAL_STANDARD | INDUSTRY_PRACTICE | PRODUCT_COMPILED
  review_status    DRAFT | AUTHOR_ASSERTED | VERIFIED | STALE
                   VERIFIED requires last_verified + verified_by; nothing else may claim it.
  superseded_by / replaces   deterministic supersession relation between rules / instruments.

HONEST STATE (2026-09-30): no rule is VERIFIED. `PROVEN` means "a primary source is cited by the
corpus author", not "re-verified against the live source" (url_verified=false, last_verified=null
for all 49 rules). The UI says so.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Iterable

AUTHORITY_TYPES = (
    "STATUTE", "RBI_DIRECTION", "FIU_IND_GUIDANCE", "FIU_IND_PUBLICATION",
    "INTERNATIONAL_STANDARD", "INDUSTRY_PRACTICE", "PRODUCT_COMPILED",
)
REVIEW_STATUSES = ("DRAFT", "AUTHOR_ASSERTED", "VERIFIED", "STALE")
EVIDENCE_LEVELS = ("PROVEN", "ASSUMED", "NEEDS-VERIFICATION")
MAX_REVIEW_AGE_DAYS = 180

ASSUMED_WARNING = (
    "⚠ This answer includes ASSUMED content — strongly implied by a primary source but not stated "
    "verbatim. Do not present it as a verified legal conclusion; confirm against the primary source."
)
UNVERIFIED_NOTE = (
    "No rule in this corpus has been independently re-verified against its live primary source "
    "(review_status = AUTHOR_ASSERTED). PROVEN means a primary source is cited, not that it was re-checked."
)


def classify_authority(document: str | None) -> str:
    """Authority type of a rule's PRIMARY (first-listed) source document string."""
    first = (document or "").split(";")[0]
    t = first.lower()
    if re.search(r"prevention of money.?laundering|\bpmla\b|\bpml rules\b", t):
        return "STATUTE"
    if "rbi master direction" in t:
        return "RBI_DIRECTION"
    if "fatf" in t:
        return "INTERNATIONAL_STANDARD"
    if re.search(r"typology|annual report|inspection|quality feedback", t) and "fiu-ind" in t:
        return "FIU_IND_PUBLICATION"
    if re.search(r"fiu-ind|finnet|fingate", t):
        return "FIU_IND_GUIDANCE"
    if re.search(r"industry|i4c|mulehunter|dpip", t):
        return "INDUSTRY_PRACTICE"
    return "UNCLASSIFIED"


def default_review_status(evidence_level: str) -> str:
    return "DRAFT" if evidence_level == "NEEDS-VERIFICATION" else "AUTHOR_ASSERTED"


def _d(v: Any) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def _same_person(a: Any, b: Any) -> bool:
    x, y = " ".join(str(a or "").split()).casefold(), " ".join(str(b or "").split()).casefold()
    return bool(x) and x == y


def review_state(rule: dict, today: date | None = None) -> dict:
    """{status, verified, stale, reason} — `status` is what the UI may claim, never more."""
    today = today or date.today()
    declared = (rule.get("review_status") or "").upper()
    lv, by = _d(rule.get("last_verified")), rule.get("verified_by")
    if declared == "VERIFIED" and lv and by and _same_person(by, rule.get("owner")):
        # Independence needs a verifier who is not the rule's owner. (The data cannot prove organisational independence; it can show self-verification.)
        return {"status": "AUTHOR_ASSERTED", "verified": False, "stale": False,
                "reason": "verified_by is the rule's owner — self-verification is not independent, so treated as unverified"}
    if declared == "VERIFIED" and lv and by:
        age = (today - lv).days
        if age > MAX_REVIEW_AGE_DAYS:
            return {"status": "STALE", "verified": False, "stale": True,
                    "reason": f"last verified {lv.isoformat()} ({age} days ago; policy {MAX_REVIEW_AGE_DAYS})"}
        return {"status": "VERIFIED", "verified": True, "stale": False,
                "reason": f"verified {lv.isoformat()} by {by}"}
    if declared == "VERIFIED":            # claims verification without evidence of it → downgrade
        return {"status": "AUTHOR_ASSERTED", "verified": False, "stale": False,
                "reason": "marked VERIFIED but last_verified/verified_by missing — treated as unverified"}
    return {"status": declared or "AUTHOR_ASSERTED", "verified": False, "stale": False,
            "reason": "never independently verified" if not lv else f"last verified {lv.isoformat()}"}


# ── supersession ─────────────────────────────────────────────────────────────
def detect_superseded_terms(question: str, rules: Iterable[dict]) -> list[dict]:
    """Deterministic: does the question rely on an instrument some rule REPLACES?

    Uses the `replaces` field of corpus rules (e.g. STR-006 replaces 'FINnet direct-upload
    mechanism'). A significant-word match of the replaced name in the question yields a
    qualification naming the current successor rule.
    """
    q = re.sub(r"[^a-z0-9 ]+", " ", (question or "").lower())
    out = []
    for r in rules:
        replaced = (r.get("replaces") or "").strip()
        if not replaced:
            continue
        words = [w for w in re.sub(r"[^a-z0-9 ]+", " ", replaced.lower()).split()
                 if w not in ("the", "a", "an", "of", "mechanism", "direct", "upload", "legacy") and len(w) > 2]
        # 'finnet direct upload' → distinctive token 'finnet'; require it plus an upload/file cue
        if words and all(w in q.split() for w in words) and \
                re.search(r"\b(upload|uploading|file|filing|submit|submission|direct|portal|channel|report)\b", q):
            out.append({
                "replaced": replaced, "successor_rule": r.get("rule_id"),
                "message": (f"'{replaced}' is superseded — the current mechanism is described by "
                            f"{r.get('rule_id')} [{r.get('evidence_level')}]. Do not cite the superseded mechanism."),
            })
    return out


def resolve_superseded(rows: list[dict], fetch_by_id) -> tuple[list[dict], list[dict]]:
    """Split rows into (current, superseded).

    A row with `superseded_by` is NEVER returned as current: it moves to `superseded`
    (status=SUPERSEDED) and the rule that replaces it — fetched via `fetch_by_id` when it was
    not itself a search hit — is surfaced in its place. Chains are followed (max 5 hops); a
    dangling successor leaves the row superseded with no replacement (callers must abstain).
    """
    by_id = {r["rule_id"]: r for r in rows}
    current: list[dict] = []
    superseded: dict[str, dict] = {}
    for r in rows:
        if not (r.get("superseded_by") or "").strip():
            current.append(r)
            continue
        cur, hops = r, 0
        while cur and (cur.get("superseded_by") or "").strip() and hops < 5:
            superseded.setdefault(cur["rule_id"], {**cur, "status": "SUPERSEDED"})
            nid = cur["superseded_by"].strip()
            cur = by_id.get(nid) or fetch_by_id(nid)
            hops += 1
        if cur and not (cur.get("superseded_by") or "").strip():
            current.append({**cur, "surfaced_as_successor_of": r["rule_id"]})
    seen, uniq = set(), []
    for r in current:
        if r["rule_id"] not in seen:
            seen.add(r["rule_id"])
            uniq.append(r)
    return uniq, list(superseded.values())


# ── conclusions: prefer PROVEN, warn on ASSUMED ──────────────────────────────
def order_prefer_proven(rules: list[dict]) -> list[dict]:
    """Stable partition: PROVEN first, then ASSUMED, each keeping search-relevance order.
    NEEDS-VERIFICATION rows are dropped (defence in depth; SQL already excludes them)."""
    proven = [r for r in rules if r.get("evidence_level") == "PROVEN"]
    assumed = [r for r in rules if r.get("evidence_level") == "ASSUMED"]
    return proven + assumed


def conclusion_basis(rules: list[dict], today: date | None = None) -> dict:
    """Programmatic PROVEN-vs-ASSUMED verdict for a set of rules a conclusion will rely on."""
    rules = [r for r in rules if r.get("evidence_level") in ("PROVEN", "ASSUMED")]
    proven = [r["rule_id"] for r in rules if r["evidence_level"] == "PROVEN"]
    assumed = [r["rule_id"] for r in rules if r["evidence_level"] == "ASSUMED"]
    if not rules:
        grade, warning = "NO_SOURCES", "No PROVEN or ASSUMED source supports an answer. Abstain."
    elif assumed:
        grade, warning = "INCLUDES_ASSUMED", ASSUMED_WARNING
    else:
        grade, warning = "PROVEN_ONLY", ""
    states = [review_state(r, today) for r in rules]
    return {
        "grade": grade,
        "proven_ids": proven,
        "assumed_ids": assumed,
        "warning": warning,
        "can_state_as_proven": grade == "PROVEN_ONLY",
        "verified_count": sum(1 for s in states if s["verified"]),
        "unverified_count": sum(1 for s in states if not s["verified"]),
        "unverified_note": UNVERIFIED_NOTE if any(not s["verified"] for s in states) else "",
    }


def evidence_label(rule: dict) -> dict:
    """UI label for one rule: never blurs PROVEN and ASSUMED."""
    ev = rule.get("evidence_level")
    rs = review_state(rule)
    return {
        "evidence_level": ev,
        "text": {"PROVEN": "PROVEN — primary source cited",
                 "ASSUMED": "ASSUMED — implied, not verbatim",
                 "NEEDS-VERIFICATION": "NEEDS-VERIFICATION — not citable"}.get(ev, str(ev)),
        "review_status": rs["status"], "verified": rs["verified"], "review_reason": rs["reason"],
        "is_assumed": ev == "ASSUMED",
    }


def rules_by_evidence_level(rows: list[dict]) -> dict:
    """{'PROVEN': [...ids], 'ASSUMED': [...], 'NEEDS-VERIFICATION': [...], 'UNKNOWN': [...]} for ledger provenance."""
    out: dict[str, list[str]] = {"PROVEN": [], "ASSUMED": [], "NEEDS-VERIFICATION": [], "UNKNOWN": []}
    for r in rows:
        out.setdefault(r.get("evidence_level") or "UNKNOWN", []).append(r["rule_id"])
    return {k: sorted(v) for k, v in out.items() if v}


# ── decision-level regulatory basis ──────────────────────────────────────────
# The record of WHICH corpus rules a decision rests on and how much weight each can bear. It is persisted in the
# ledger (METADATA_JSON.regulatory_basis) so an inspector can see — years later — exactly what authority the PO relied
# on, at what corpus version, and whether any of it was assumed, unverified or superseded.
BASIS_SCHEMA = "regulatory_basis/1"
GRADE_PROVEN_ONLY = "PROVEN_ONLY"
GRADE_INCLUDES_ASSUMED = "INCLUDES_ASSUMED"
GRADE_NO_SUPPORTED_BASIS = "NO_SUPPORTED_BASIS"
GRADE_UNAVAILABLE = "UNAVAILABLE"            # the corpus could not be read: nothing may be concluded from it

# why a cited rule cannot bear a legal conclusion
UNUSABLE_NEEDS_VERIFICATION = "NEEDS_VERIFICATION"   # tag only; its text is excluded everywhere
UNUSABLE_SUPERSEDED = "SUPERSEDED"
UNUSABLE_NOT_IN_CORPUS = "NOT_IN_CORPUS"
UNUSABLE_UNKNOWN_LEVEL = "UNKNOWN_EVIDENCE_LEVEL"


def _canonical_sha256(obj: Any) -> str:
    import hashlib
    import json
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def build_regulatory_basis(requested_ids: Iterable[str], rows: Iterable[dict], *, corpus_version: str | None,
                           snapshot_date: str | None, today: date | None = None, error: str | None = None) -> dict:
    """The decision-level regulatory-basis object. Pure: `rows` are the corpus rows found for `requested_ids`
    (lower-case keys: rule_id, evidence_level, review_status, source_authority, corpus_version, snapshot_date,
    last_verified, verified_by, superseded_by); a requested id with no row is NOT_IN_CORPUS.

    A rule may bear a legal conclusion only if it is PROVEN or ASSUMED, in the corpus, and not superseded.
    NEEDS-VERIFICATION rules stay as internal tags. `error` (corpus unreadable) → grade UNAVAILABLE: nothing may be
    concluded. The object carries its own sha256 so any later edit of the stored copy is detectable."""
    by_id = {r.get("rule_id"): r for r in rows if r.get("rule_id")}
    entries: list[dict] = []
    for rid in sorted({i for i in requested_ids if i}):
        r = by_id.get(rid)
        if r is None:
            entries.append({"rule_id": rid, "evidence_level": "UNKNOWN", "review_status": None, "source_authority": None,
                            "corpus_version": None, "snapshot_date": None, "supersession_status": "UNKNOWN",
                            "superseded_by": None, "usable_as_basis": False, "unusable_reason": UNUSABLE_NOT_IN_CORPUS})
            continue
        level = r.get("evidence_level") or "UNKNOWN"
        sup = (r.get("superseded_by") or "").strip() or None
        if level not in EVIDENCE_LEVELS:
            reason = UNUSABLE_UNKNOWN_LEVEL
        elif level == "NEEDS-VERIFICATION":
            reason = UNUSABLE_NEEDS_VERIFICATION
        elif sup:
            reason = UNUSABLE_SUPERSEDED
        else:
            reason = None
        rs = review_state(r, today)
        entries.append({
            "rule_id": rid, "evidence_level": level, "review_status": rs["status"], "review_verified": rs["verified"],
            "source_authority": r.get("source_authority") or "UNCLASSIFIED",
            "corpus_version": r.get("corpus_version"), "snapshot_date": str(r.get("snapshot_date") or "")[:10] or None,
            "supersession_status": "SUPERSEDED" if sup else "CURRENT", "superseded_by": sup,
            "usable_as_basis": reason is None, "unusable_reason": reason,
        })
    usable = [e for e in entries if e["usable_as_basis"]]
    proven = [e["rule_id"] for e in usable if e["evidence_level"] == "PROVEN"]
    assumed = [e["rule_id"] for e in usable if e["evidence_level"] == "ASSUMED"]
    if error:
        grade = GRADE_UNAVAILABLE
    elif not usable:
        grade = GRADE_NO_SUPPORTED_BASIS
    else:
        grade = GRADE_INCLUDES_ASSUMED if assumed else GRADE_PROVEN_ONLY
    basis = {
        "schema": BASIS_SCHEMA,
        "corpus_version": corpus_version or "UNKNOWN",
        "snapshot_date": str(snapshot_date or "")[:10] or None,
        "grade": grade,
        "legal_conclusion_permitted": grade in (GRADE_PROVEN_ONLY, GRADE_INCLUDES_ASSUMED),
        "requires_assumed_acknowledgement": bool(assumed) and grade != GRADE_UNAVAILABLE,
        "proven_rule_ids": proven,
        "assumed_rule_ids": assumed,
        "excluded": [{"rule_id": e["rule_id"], "reason": e["unusable_reason"], "superseded_by": e["superseded_by"]}
                     for e in entries if not e["usable_as_basis"]],
        "independently_verified_count": sum(1 for e in usable if e.get("review_verified")),
        "stale_review_rule_ids": [e["rule_id"] for e in usable if e["review_status"] == "STALE"],
        "rules": entries,
        # same shape the v2 ledger rows used, so readers/tests of the old shape keep working
        "by_evidence_level": rules_by_evidence_level(
            [{"rule_id": e["rule_id"], "evidence_level": e["evidence_level"]} for e in entries]),
        "error": error,
    }
    basis["basis_sha256"] = _canonical_sha256(basis)
    return basis


def basis_intact(basis: Any) -> bool:
    """True iff a stored basis object still hashes to its own `basis_sha256` (detects a hand-edited copy)."""
    if not isinstance(basis, dict) or not basis.get("basis_sha256"):
        return False
    body = {k: v for k, v in basis.items() if k != "basis_sha256"}
    return _canonical_sha256(body) == basis["basis_sha256"]


def basis_by_level(basis: Any) -> dict:
    """{'PROVEN': [...], ...} from either the current object or a v2 ledger row's plain dict."""
    if not isinstance(basis, dict):
        return {}
    if basis.get("schema") == BASIS_SCHEMA:
        return dict(basis.get("by_evidence_level") or {})
    return {k: v for k, v in basis.items() if isinstance(v, list)}
