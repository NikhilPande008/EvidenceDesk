"""
Regulatory-corpus lifecycle — who stands behind each rule, when it was last looked at, and whether it is still safe to lean on.

Per rule the lifecycle model holds (a rule row from REGULATORY_CORPUS or a corpus YAML entry):

    source URL · authority · effective date · LAST REVIEWED · LAST INDEPENDENTLY VERIFIED · owner · REVIEW SLA (days) ·
    supersession / replacement relationship · APPROVAL status

and `governance_report` turns a set of rules into the dashboard an inspector or a corpus owner needs: rules requiring review, superseded
rules, unverified sources, stale content, approval status — each as a list of rule IDs with the reason, never as an adjective.

Four statements the model refuses to make unless the DATA proves them:
  1. "independently verified"  needs review_status VERIFIED **and** a verification date **and** a named verifier **and** a verifier who is
     not the rule's owner **and** a verification no older than the review SLA. Anything less is reported UNVERIFIED (or STALE).
     (Independence here means "a different person recorded it"; no dataset can prove organisational independence.)
  2. "reviewed" needs a recorded `last_reviewed` date. A rule never reviewed is NEVER_REVIEWED — not "current".
  3. "approved" needs `approval_status = APPROVED` **and** `approved_by` **and** `approved_on`. Otherwise it is UNAPPROVED.
  4. A rule is usable for a legal or regulatory conclusion only if it is PROVEN or ASSUMED **and** not superseded. NEEDS-VERIFICATION and
     superseded rules are EXCLUDED from conclusions — this module reports that exclusion (it cannot lift it) and a test pins that
     no lifecycle state, however good, makes an excluded rule usable. Being reviewed, approved or verified never lifts an exclusion.

Fields that the live table does not yet have (LAST_REVIEWED, REVIEW_SLA_DAYS, APPROVAL_STATUS, APPROVED_BY, APPROVED_ON arrive with the
migration in domain/corpus/export/ddl/regulatory_corpus.sql) are reported as NOT PROVISIONED in `field_coverage` — never defaulted to a
reassuring value. The review SLA falls back to the corpus policy (180 days, the same constant governance.review_state uses).

Pure functions; no database, no clock of their own.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date, timedelta
from typing import Iterable

from skills.governance import EVIDENCE_LEVELS, MAX_REVIEW_AGE_DAYS, _d, review_state

DEFAULT_REVIEW_SLA_DAYS = MAX_REVIEW_AGE_DAYS
DUE_SOON_DAYS = 30
APPROVAL_STATUSES = ("UNAPPROVED", "APPROVED")

# Columns the lifecycle needs beyond the original governance columns. The app reads them with a fallback, so a table that predates the
# migration still works (every new column is reported NOT PROVISIONED).
NEW_COLUMNS = ("LAST_REVIEWED", "REVIEW_SLA_DAYS", "APPROVAL_STATUS", "APPROVED_BY", "APPROVED_ON")
_BASE_COLUMNS = ("RULE_ID", "CATEGORY", "EVIDENCE_LEVEL", "SOURCE_AUTHORITY", "SOURCE_DOCUMENT", "SOURCE_URL", "SOURCE_URL_VERIFIED", "EFFECTIVE_DATE",
                 "SNAPSHOT_DATE", "LAST_VERIFIED", "VERIFIED_BY", "REVIEW_STATUS", "OWNER", "SUPERSEDED_BY", "REPLACES", "CORPUS_VERSION")
# Metadata only: rule TEXT is never selected, so NEEDS-VERIFICATION wording cannot reach this page.
LIFECYCLE_SQL_BASE = "SELECT " + ", ".join(_BASE_COLUMNS) + " FROM FIU_COPILOT.AML.REGULATORY_CORPUS ORDER BY RULE_ID"
LIFECYCLE_SQL_FULL = "SELECT " + ", ".join(_BASE_COLUMNS + NEW_COLUMNS) + " FROM FIU_COPILOT.AML.REGULATORY_CORPUS ORDER BY RULE_ID"

_SAFE_URL = re.compile(r"https?://[^\s<>()\[\]`\"'\\]+")


def normalise_row(row: dict) -> dict:
    """A REGULATORY_CORPUS row (upper-case keys) → the lower-case rule dict the lifecycle works on. Unknown keys are dropped."""
    g = lambda k: row.get(k) if k in row else row.get(k.lower())          # noqa: E731
    return {
        "rule_id": g("RULE_ID"), "category": g("CATEGORY"), "evidence_level": g("EVIDENCE_LEVEL"), "source_authority": g("SOURCE_AUTHORITY"),
        "source_document": g("SOURCE_DOCUMENT"), "source_url": g("SOURCE_URL"), "source_url_verified": bool(g("SOURCE_URL_VERIFIED")),
        "effective_date": g("EFFECTIVE_DATE"), "snapshot_date": g("SNAPSHOT_DATE"), "last_verified": g("LAST_VERIFIED"), "verified_by": g("VERIFIED_BY"),
        "review_status": g("REVIEW_STATUS"), "owner": g("OWNER"), "superseded_by": g("SUPERSEDED_BY"), "replaces": g("REPLACES"),
        "corpus_version": g("CORPUS_VERSION"),
        "last_reviewed": g("LAST_REVIEWED"), "review_sla_days": g("REVIEW_SLA_DAYS"), "approval_status": g("APPROVAL_STATUS"),
        "approved_by": g("APPROVED_BY"), "approved_on": g("APPROVED_ON"),
        # which new columns this row actually carried (a column absent from the table is "not provisioned", not "empty")
        "_provisioned": {k: (k in row or k.lower() in row) for k in NEW_COLUMNS},
    }


def rule_from_yaml(entry: dict) -> dict:
    """A corpus YAML entry (domain/corpus/rules/*.yaml) → the same lower-case rule dict. All five new fields are optional there."""
    ps = entry.get("primary_source") or {}
    return {
        "rule_id": entry.get("id"), "category": entry.get("category"), "evidence_level": entry.get("evidence_level"), "source_authority": entry.get("source_authority"),
        "source_document": ps.get("document"), "source_url": ps.get("url"), "source_url_verified": bool(ps.get("url_verified")),
        "effective_date": entry.get("effective_date"), "snapshot_date": entry.get("snapshot_date"), "last_verified": entry.get("last_verified"),
        "verified_by": entry.get("verified_by"), "review_status": entry.get("review_status"), "owner": entry.get("owner"),
        "superseded_by": entry.get("superseded_by"), "replaces": entry.get("replaces") or (entry.get("supersession") or {}).get("supersedes"),
        "corpus_version": entry.get("corpus_version"),
        "last_reviewed": entry.get("last_reviewed"), "review_sla_days": entry.get("review_sla_days"), "approval_status": entry.get("approval_status"),
        "approved_by": entry.get("approved_by"), "approved_on": entry.get("approved_on"),
        "_provisioned": {k: True for k in NEW_COLUMNS},          # a YAML file can carry the fields; absent simply means nobody recorded a value
    }


def _sla(rule: dict) -> tuple[int, bool]:
    try:
        n = int(rule.get("review_sla_days"))
        if n > 0:
            return n, True
    except (TypeError, ValueError):
        pass
    return DEFAULT_REVIEW_SLA_DAYS, False


def lifecycle_state(rule: dict, today: date | None = None) -> dict:
    """The lifecycle of ONE rule, with every claim justified by a field. See the module docstring for the four things it will not assert."""
    today = _d(today) or date.today()
    level = rule.get("evidence_level") or "UNKNOWN"
    sla, sla_explicit = _sla(rule)
    reviewed, snapshot = _d(rule.get("last_reviewed")), _d(rule.get("snapshot_date"))
    anchor = reviewed or snapshot                    # the review clock runs from the last review, else from the content's as-of date
    due = (anchor + timedelta(days=sla)) if anchor else None
    if reviewed is None:
        review = "NEVER_REVIEWED"
    elif due and today > due:
        review = "OVERDUE"
    elif due and (due - today).days <= DUE_SOON_DAYS:
        review = "DUE_SOON"
    else:
        review = "CURRENT"
    if review == "NEVER_REVIEWED" and due and today > due:
        review = "NEVER_REVIEWED_OVERDUE"            # never reviewed AND the as-of date is already older than the SLA

    rs = review_state({**rule, "owner": rule.get("owner")}, today)
    independent = bool(rs["verified"])
    verification = "VERIFIED" if independent else ("STALE" if rs["stale"] else "UNVERIFIED")

    sup, replaces = (rule.get("superseded_by") or "").strip() or None, (rule.get("replaces") or "").strip() or None
    approved = ((rule.get("approval_status") or "").upper() == "APPROVED" and bool(rule.get("approved_by")) and _d(rule.get("approved_on")) is not None)
    approval = "APPROVED" if approved else "UNAPPROVED"
    approval_reason = ("approved by %s on %s" % (rule.get("approved_by"), _d(rule.get("approved_on")).isoformat()) if approved else
                       "marked APPROVED without approved_by / approved_on — treated as unapproved" if (rule.get("approval_status") or "").upper() == "APPROVED" else
                       "no approval recorded")

    reasons = []
    if level == "NEEDS-VERIFICATION":
        reasons.append("NEEDS_VERIFICATION")
    elif level not in EVIDENCE_LEVELS:
        reasons.append("UNKNOWN_EVIDENCE_LEVEL")
    if sup:
        reasons.append("SUPERSEDED")
    url = str(rule.get("source_url") or "").strip()
    return {
        "rule_id": rule.get("rule_id"), "evidence_level": level, "owner": rule.get("owner") or None, "source_authority": rule.get("source_authority") or "UNCLASSIFIED",
        "source_url": url or None, "source_url_shape_ok": bool(_SAFE_URL.fullmatch(url)) if url else False, "source_url_verified": bool(rule.get("source_url_verified")),
        "effective_date": _d(rule.get("effective_date")).isoformat() if _d(rule.get("effective_date")) else None,
        "snapshot_date": snapshot.isoformat() if snapshot else None,
        "last_reviewed": reviewed.isoformat() if reviewed else None, "last_verified": _d(rule.get("last_verified")).isoformat() if _d(rule.get("last_verified")) else None,
        "verified_by": rule.get("verified_by") or None, "review_sla_days": sla, "review_sla_explicit": sla_explicit,
        "review_due_on": due.isoformat() if due else None, "review_state": review,
        "verification": verification, "independently_verified": independent, "verification_reason": rs["reason"],
        "superseded_by": sup, "replaces": replaces, "supersession": "SUPERSEDED" if sup else "CURRENT",
        "approval_status": approval, "approval_reason": approval_reason,
        "excluded_from_conclusions": bool(reasons), "exclusion_reasons": reasons,
        "usable_for_conclusion": not reasons,
        "needs_review": review != "CURRENT",
    }


def governance_report(rules: Iterable[dict], today: date | None = None) -> dict:
    """The corpus-governance dashboard over a set of rule dicts (normalise_row / rule_from_yaml)."""
    today = _d(today) or date.today()
    rules = list(rules)
    states = [lifecycle_state(r, today) for r in rules]
    prov = {k: any((r.get("_provisioned") or {}).get(k) for r in rules) for k in NEW_COLUMNS}
    populated = {"LAST_REVIEWED": sum(1 for s in states if s["last_reviewed"]), "REVIEW_SLA_DAYS": sum(1 for s in states if s["review_sla_explicit"]),
                 "APPROVAL_STATUS": sum(1 for s in states if s["approval_status"] == "APPROVED"),
                 "APPROVED_BY": sum(1 for r in rules if r.get("approved_by")), "APPROVED_ON": sum(1 for r in rules if _d(r.get("approved_on")))}
    rank = {"NEEDS-VERIFICATION": 0, "ASSUMED": 1, "PROVEN": 2}
    order = lambda s: ({"NEVER_REVIEWED_OVERDUE": 0, "OVERDUE": 0, "DUE_SOON": 1, "NEVER_REVIEWED": 2}.get(s["review_state"], 3), rank.get(s["evidence_level"], 3), str(s["rule_id"]))  # noqa: E731
    item = lambda s, why: {"rule_id": s["rule_id"], "evidence_level": s["evidence_level"], "owner": s["owner"], "reason": why, "due_on": s["review_due_on"]}  # noqa: E731
    requiring = [item(s, s["review_state"]) for s in sorted(states, key=order) if s["needs_review"]]
    superseded = [{"rule_id": s["rule_id"], "superseded_by": s["superseded_by"], "evidence_level": s["evidence_level"]} for s in states if s["superseded_by"]]
    replacing = [{"rule_id": s["rule_id"], "replaces": s["replaces"]} for s in states if s["replaces"]]
    unverified_sources = [item(s, "SOURCE_URL_NOT_VERIFIED" if not s["source_url_verified"] else "RULE_NOT_INDEPENDENTLY_VERIFIED") for s in states
                          if not s["source_url_verified"] or not s["independently_verified"]]
    stale = [item(s, "VERIFICATION_STALE" if s["verification"] == "STALE" else "REVIEW_OVERDUE") for s in states
             if s["verification"] == "STALE" or s["review_state"] in ("OVERDUE", "NEVER_REVIEWED_OVERDUE")]
    n = len(states)
    verified_n = sum(1 for s in states if s["independently_verified"])
    by_level = Counter(s["evidence_level"] for s in states)
    return {
        "as_of": today.isoformat(), "total": n,
        "counts": {
            "proven": by_level.get("PROVEN", 0), "assumed": by_level.get("ASSUMED", 0), "needs_verification": by_level.get("NEEDS-VERIFICATION", 0),
            "independently_verified": verified_n, "never_reviewed": sum(1 for s in states if s["review_state"].startswith("NEVER_REVIEWED")),
            "review_overdue": sum(1 for s in states if s["review_state"] in ("OVERDUE", "NEVER_REVIEWED_OVERDUE")),
            "review_due_soon": sum(1 for s in states if s["review_state"] == "DUE_SOON"), "requiring_review": len(requiring),
            "superseded": len(superseded), "source_url_not_verified": sum(1 for s in states if not s["source_url_verified"]),
            "stale_verification": sum(1 for s in states if s["verification"] == "STALE"), "unapproved": sum(1 for s in states if s["approval_status"] == "UNAPPROVED"),
            "approved": sum(1 for s in states if s["approval_status"] == "APPROVED"), "excluded_from_conclusions": sum(1 for s in states if s["excluded_from_conclusions"]),
            "missing_owner": sum(1 for s in states if not s["owner"]), "source_url_shape_invalid": sum(1 for s in states if s["source_url"] and not s["source_url_shape_ok"]),
        },
        "requiring_review": requiring, "superseded": superseded, "replacing": replacing, "unverified_sources": unverified_sources, "stale": stale,
        "excluded": [{"rule_id": s["rule_id"], "reasons": s["exclusion_reasons"]} for s in states if s["excluded_from_conclusions"]],
        "by_authority": dict(Counter(s["source_authority"] for s in states)),
        "field_coverage": {k: {"provisioned": prov[k], "populated": populated[k]} for k in NEW_COLUMNS},
        "statement": (f"{verified_n} of {n} rules are independently verified against their primary source."
                      + (" No rule has been independently verified." if n and verified_n == 0 else "")),
        "exclusion_statement": ("NEEDS-VERIFICATION and superseded rules are excluded from legal and regulatory conclusions. Being reviewed, approved or verified never lifts "
                                "that exclusion."),
        "rules": states,
    }


def usable_for_conclusion(rule: dict, today: date | None = None) -> bool:
    return lifecycle_state(rule, today)["usable_for_conclusion"]


def to_markdown(report: dict) -> str:
    """The report as a plain Markdown document (for the CLI and for filing with a corpus review)."""
    c = report["counts"]
    lines = [f"# Corpus governance report — as of {report['as_of']}", "", f"**{report['statement']}**", "", report["exclusion_statement"], "",
             "| Measure | Rules |", "|---|---|"]
    for label, key in (("Total", None), ("PROVEN (primary source cited)", "proven"), ("ASSUMED", "assumed"), ("NEEDS-VERIFICATION (excluded)", "needs_verification"),
                       ("Independently verified", "independently_verified"), ("Never reviewed", "never_reviewed"), ("Review overdue", "review_overdue"),
                       ("Requiring review (never / overdue / due soon)", "requiring_review"), ("Superseded (excluded)", "superseded"),
                       ("Source URL not verified", "source_url_not_verified"), ("Stale verification", "stale_verification"), ("Unapproved", "unapproved"),
                       ("Approved", "approved")):
        lines.append(f"| {label} | {report['total'] if key is None else c[key]} |")
    lines += ["", "## Lifecycle fields", "", "| Field | Available | Rules with a value |", "|---|---|---|"]
    for k, v in report["field_coverage"].items():
        lines.append(f"| {k} | {'yes' if v['provisioned'] else 'NO — column not present'} | {v['populated']} |")
    for title, key in (("Rules requiring review", "requiring_review"), ("Superseded rules", "superseded"), ("Stale content", "stale")):
        items = report[key]
        lines += ["", f"## {title} ({len(items)})", ""]
        lines += [f"- `{i['rule_id']}` — " + ", ".join(f"{k}: {v}" for k, v in i.items() if k != "rule_id" and v) for i in items[:60]] or ["- none"]
    return "\n".join(lines) + "\n"
