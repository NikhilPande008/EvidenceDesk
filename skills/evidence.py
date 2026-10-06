"""
Deterministic SOURCE-FACT computations over the TRANSACTIONS ledger — no LLM.

Used by the Signal Brief and by the ALERT-01 vs ALERT-16 twin comparison, so the UI can show
"what the data says" separately from "what the AI infers".
"""

from __future__ import annotations

import re

from skills import po_copy as T

_DOCUMENTED = re.compile(r"kyc-linked|invoice on file|documented", re.I)


def movement_records(txns: list[dict]) -> dict:
    """Describe supplied rows, never infer links between individual credits and debits.

    The seed feed has no granularity column. Recognise its explicit summary labels
    (including 15-day cash totals), and disclose that other rows' granularity is
    not independently verified. This metadata is for display, not decision policy.
    """
    summary_ids = []
    groups = {"CREDIT": [], "DEBIT": [], "OTHER": []}
    for row in txns:
        cp = str(row.get("counterparty") or "")
        if (row.get("is_summary") is True or
                re.search(r"multiple counterparties|\(\d+\s*d\)|summary|aggregate", cp, re.I)):
            summary_ids.append(str(row.get("txn_id") or "Unidentified row"))
        kind = row.get("type")
        groups[kind if kind in ("CREDIT", "DEBIT") else "OTHER"].append(row)
    return {"groups": groups, "summary_ids": summary_ids,
            "has_summaries": bool(summary_ids), "row_count": len(txns)}


def signal_brief(txns: list[dict]) -> dict:
    """Aggregates the observed transactions. Every number is a plain SUM/COUNT of the rows."""
    credits = [t for t in txns if t.get("type") == "CREDIT"]
    debits = [t for t in txns if t.get("type") == "DEBIT"]
    amt = lambda rows: sum(float(t.get("amount_inr") or 0) for t in rows)  # noqa: E731
    flagged_rows = [t for t in txns if t.get("is_flagged")]
    flagged_debits = [t for t in debits if t.get("is_flagged")]
    cps = sorted({t["counterparty"] for t in txns if t.get("counterparty")})
    dates = sorted(str(t["date"]) for t in txns if t.get("date"))
    total_credit, total_debit = amt(credits), amt(debits)
    return {
        "txn_count": len(txns),
        "credit_count": len(credits), "debit_count": len(debits),
        "total_credit": total_credit, "total_debit": total_debit,
        "onward_ratio_pct": round(total_debit / total_credit * 100, 1) if total_credit else None,
        "flagged_txn_count": len(flagged_rows),
        "flagged_counterparties": sorted({t["counterparty"] for t in flagged_rows if t.get("counterparty")}),
        "flagged_debit_total": amt(flagged_debits),
        "flagged_debit_share_pct": round(amt(flagged_debits) / total_credit * 100, 1) if total_credit else None,
        "counterparties": cps,
        "documented_counterparties": [c for c in cps if _DOCUMENTED.search(c)],
        "channels": sorted({str(t["channel"]) for t in txns if t.get("channel")}),
        "window": (dates[0], dates[-1]) if dates else None,
        "txn_ids": [t.get("txn_id") for t in txns],
    }


def compare_signals(a_meta: dict, a: dict, b_meta: dict, b: dict) -> list[dict]:
    """Row-per-metric comparison of two alerts. `differs` marks the evidence that separates them."""
    def fm(v, kind):
        if v is None:
            return "—"
        return {"inr": f"₹{v:,.0f}", "pct": f"{v:.1f}%", "n": str(v)}[kind]
    rows = [
        ("Detection rule", a_meta.get("ALERT_TYPE"), b_meta.get("ALERT_TYPE")),
        ("Signal source", a_meta.get("SIGNAL_SOURCE"), b_meta.get("SIGNAL_SOURCE")),
        ("Alert amount", fm(float(a_meta.get("ALERT_AMOUNT_INR") or 0), "inr"), fm(float(b_meta.get("ALERT_AMOUNT_INR") or 0), "inr")),
        ("Credits received", fm(a["total_credit"], "inr"), fm(b["total_credit"], "inr")),
        ("Debits sent onward", fm(a["total_debit"], "inr"), fm(b["total_debit"], "inr")),
        ("Onward-transfer ratio", fm(a["onward_ratio_pct"], "pct"), fm(b["onward_ratio_pct"], "pct")),
        ("Flagged counterparties", fm(len(a["flagged_counterparties"]), "n"), fm(len(b["flagged_counterparties"]), "n")),
        ("Debits to flagged counterparties", fm(a["flagged_debit_total"], "inr"), fm(b["flagged_debit_total"], "inr")),
        ("Documented counterparties", fm(len(a["documented_counterparties"]), "n"),
         fm(len(b["documented_counterparties"]), "n")),
    ]
    return [{"metric": m, "a": x, "b": y, "differs": x != y} for m, x, y in rows]


def _inr(v) -> str:
    return f"₹{float(v or 0):,.0f}"


def _names(items: list[str], limit: int = 3) -> str:
    shown = [str(i) for i in items[:limit]]
    return ", ".join(shown) + (f" +{len(items) - limit} more" if len(items) > limit else "")


def explain_pair(a_meta: dict, a: dict, b_meta: dict, b: dict) -> dict:
    """Why do two alerts that fired the SAME detector for the SAME amount deserve different dispositions? Built ONLY from the two
    alerts' computed source facts (signal_brief) — no AI, no alert IDs hard-coded. Every sentence is a template in skills/po_copy.py.

    Returns {title, thesis, same[], different[], conclusion|None, evidence_differs}. `different` has one line per alert per metric."""
    rule_a, rule_b = a_meta.get("ALERT_TYPE"), b_meta.get("ALERT_TYPE")
    src_a, src_b = a_meta.get("SIGNAL_SOURCE"), b_meta.get("SIGNAL_SOURCE")
    amt_a, amt_b = float(a_meta.get("ALERT_AMOUNT_INR") or 0), float(b_meta.get("ALERT_AMOUNT_INR") or 0)
    same: list[str] = []
    if rule_a == rule_b and src_a == src_b and amt_a == amt_b:
        same.append(T.PAIR_SAME.format(rule=str(rule_a).replace("_", " ").title(), source=src_a, amount=_inr(amt_a)))
    else:
        if rule_a == rule_b:
            same.append(f"Same detection rule ({str(rule_a).replace('_', ' ').title()}).")
        if src_a == src_b:
            same.append(f"Same signal source ({src_a}).")
        if amt_a == amt_b:
            same.append(f"Same alert amount ({_inr(amt_a)}).")

    different: list[str] = []
    for meta, brief in ((a_meta, a), (b_meta, b)):
        aid = meta.get("ALERT_ID")
        if brief.get("onward_ratio_pct") is not None:
            different.append(T.PAIR_ONWARD.format(alert=aid, debits=_inr(brief["total_debit"]), ratio=brief["onward_ratio_pct"], credits=_inr(brief["total_credit"])))
        flagged = brief.get("flagged_counterparties") or []
        if flagged:
            tpl = T.PAIR_FLAGGED_ONE if len(flagged) == 1 else T.PAIR_FLAGGED_MANY
            different.append(tpl.format(alert=aid, amount=_inr(brief["flagged_debit_total"]), share=brief.get("flagged_debit_share_pct"), n=len(flagged), names=_names(flagged)))
        else:
            different.append(T.PAIR_FLAGGED_NONE.format(alert=aid))
        documented, total = brief.get("documented_counterparties") or [], len(brief.get("counterparties") or [])
        if documented:
            different.append(T.PAIR_DOCUMENTED.format(alert=aid, documented=len(documented), total=total, names=_names(documented)))
        else:
            different.append(T.PAIR_UNDOCUMENTED.format(alert=aid, total=total))

    differs = (
        len(a.get("flagged_counterparties") or []) != len(b.get("flagged_counterparties") or [])
        or len(a.get("documented_counterparties") or []) != len(b.get("documented_counterparties") or [])
        or a.get("onward_ratio_pct") != b.get("onward_ratio_pct")
    )
    return {"title": T.PAIR_WHY_TITLE, "thesis": T.PAIR_THESIS, "same": same, "different": different,
            "conclusion": T.PAIR_CONCLUSION if differs else None, "evidence_differs": differs}


# ── counterparty identity helpers (shared by evidence_quality and relationships) ────────────────────────
# Deterministic string rules, NOT entity resolution: they decide only whether two labels are the same string after a stated
# normalisation, and whether a label is the kind of placeholder that must never be treated as one real entity.
_AGGREGATE_LABEL = re.compile(r"multiple counterparties|\(\d+\s*d\)|summary|aggregate", re.I)
_UNIDENTIFIED_LABEL = re.compile(r"\b(?:unknown|unidentified|unnamed|unresolved)\b", re.I)
_TRAILING_NOTE = re.compile(r"(?:\s*\([^()]*\))+\s*$")
_CORPORATE_WORDS = frozenset({"ltd", "limited", "pvt", "private", "co", "company", "inc", "llp", "the", "and", "of"})


def is_aggregate_row(row: dict) -> bool:
    """A stored row that stands for MANY transfers (a reconciling summary), so its counterparty is a placeholder."""
    return bool(row.get("is_summary") is True or _AGGREGATE_LABEL.search(str(row.get("counterparty") or "")))


def is_unidentified_counterparty(label: str | None) -> bool:
    """'Unknown UPI handle A' names no stable entity: the letter only distinguishes rows inside ONE case."""
    return bool(_UNIDENTIFIED_LABEL.search(str(label or "")))


def is_linkable_counterparty(label: str | None) -> bool:
    """May this label be matched against other rows or other cases? Not a placeholder, not unidentified, not empty."""
    s = str(label or "").strip()
    return bool(s) and not _AGGREGATE_LABEL.search(s) and not _UNIDENTIFIED_LABEL.search(s)


def counterparty_key(label: str | None) -> str:
    """Normalised comparison key: trailing '(…)' annotations such as '(I4C-flagged)' or '(KYC-linked family)' removed, case-folded,
    punctuation collapsed. 'UPI handle C (I4C-flagged)' and 'UPI handle C' share a key; 'Brother' and 'Sister' do not."""
    s = _TRAILING_NOTE.sub("", str(label or "")).casefold()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def counterparty_tokens(label: str | None) -> frozenset:
    return frozenset(t for t in counterparty_key(label).split() if t not in _CORPORATE_WORDS)


def documented_counterparty(label: str | None) -> bool:
    return bool(_DOCUMENTED.search(str(label or "")))
