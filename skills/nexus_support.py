"""
Record-backed support for the two nexus factors the model is most willing to trigger on a hedge.

PRODUCT POLICY (DG-19, an extension of the nexus rule in skills/core.py): a FILE recommendation needs at least one grounded factor about what the
money IS or WHERE it goes (source of income, beneficiary, complexity, geography). "Grounded" only proves that the transaction ids a factor cites
exist. The live replay of 16 alerts (evidence/live-replay/2026-10-05/) showed what that lets through: for ALERT-16, the legitimate twin of ALERT-01,
the model triggered Beneficiary ("raises questions about the purpose") and Complexity ("possible pass-through") on a record in which every
sender is a KYC-linked family member and the only recipient is a named hospital, and the recommendation was FILE.

This module asks the transaction record one more question about those two factors, and only where the record CAN answer it:

  POE-007 Beneficiary   supported when a flagged counterparty received money, or a recipient is unidentified.
  POE-010 Complexity    supported by a cross-border hop (SWIFT, or a foreign place on a row), repeated cash deposits (three or more rows, the shape of
                        structuring), a flagged counterparty, or three or more unidentified senders.

Three properties keep this honest:

  * It only DISCOUNTS. A factor the record cannot test (no debit rows for the beneficiary test; fewer than two rows for the complexity test; only an
    aggregate summary row) keeps the support it had. Absence of rows is not evidence against suspicion.
  * It reads facts, not labels the officer can type: the flag, the channel, the counterparty name and the row count. It does not parse "documented".
  * It never raises a recommendation. A discounted factor stops counting toward FILE; it is still shown as triggered, with the reason.

Pure and deterministic: no model, no database, no clock.
"""

from __future__ import annotations

import re

from skills.grounding import GEOGRAPHIES

BENEFICIARY, COMPLEXITY = "POE-007", "POE-010"
CHECKED = (BENEFICIARY, COMPLEXITY)

_UNIDENTIFIED = re.compile(r"\b(unknown|unidentified|unnamed|anonymous|unrelated)\b", re.I)
_SUMMARY = re.compile(r"multiple counterparties|\(\d+\s*d\)|summary|aggregate", re.I)
_FOREIGN_PLACE = re.compile(r"(?<![A-Za-z])(" + "|".join(re.escape(g) for g in sorted(GEOGRAPHIES, key=len, reverse=True)) + r")(?![A-Za-z])", re.I)
CASH_ROWS_FOR_STRUCTURING = 3
UNIDENTIFIED_SENDERS_FOR_COMPLEXITY = 3


def _is_summary(row: dict) -> bool:
    return row.get("is_summary") is True or bool(_SUMMARY.search(str(row.get("counterparty") or "")))


def _unidentified(row: dict) -> bool:
    return bool(_UNIDENTIFIED.search(str(row.get("counterparty") or "")))


def assess(factor_id: str, transactions: list[dict] | None) -> dict:
    """{testable, supported, reason} for one nexus factor against the case rows. `supported` is None when the record cannot test the factor."""
    rows = [t for t in (transactions or []) if isinstance(t, dict)]
    real = [t for t in rows if not _is_summary(t)]
    if factor_id == BENEFICIARY:
        debits = [t for t in real if t.get("type") == "DEBIT"]
        if not debits:
            return {"testable": False, "supported": None, "reason": "no individual outgoing row to test the beneficiary against"}
        flagged = [t for t in debits if t.get("is_flagged")]
        unknown = [t for t in debits if _unidentified(t)]
        if flagged or unknown:
            why = "a flagged counterparty received money" if flagged else "a recipient is unidentified"
            return {"testable": True, "supported": True, "reason": why}
        return {"testable": True, "supported": False,
                "reason": f"every one of the {len(debits)} outgoing row(s) goes to a named counterparty that carries no flag"}
    if factor_id == COMPLEXITY:
        if len(rows) < 2:
            return {"testable": False, "supported": None, "reason": "fewer than two rows: no structure to test"}
        if any(str(t.get("channel") or "").upper() == "SWIFT" or _FOREIGN_PLACE.search(str(t.get("counterparty") or "")) for t in rows):
            return {"testable": True, "supported": True, "reason": "the record shows a cross-border hop"}
        if sum(1 for t in rows if str(t.get("channel") or "").upper() == "CASH") >= CASH_ROWS_FOR_STRUCTURING:
            return {"testable": True, "supported": True, "reason": "repeated cash rows (the shape of structuring)"}
        if any(t.get("is_flagged") for t in rows):
            return {"testable": True, "supported": True, "reason": "a flagged counterparty is involved"}
        senders = {str(t.get("counterparty") or "") for t in rows if t.get("type") == "CREDIT" and _unidentified(t)}
        if len(senders) >= UNIDENTIFIED_SENDERS_FOR_COMPLEXITY:
            return {"testable": True, "supported": True, "reason": f"{len(senders)} unidentified senders"}
        return {"testable": True, "supported": False,
                "reason": "no cross-border hop, no repeated cash, no flagged counterparty and no run of unidentified senders: the record shows a pass-through shape only"}
    return {"testable": False, "supported": None, "reason": "this factor has no record test"}


def discounted(factor_id: str, transactions: list[dict] | None) -> str | None:
    """The reason a triggered nexus factor must not count toward FILE, or None (it counts, or the record cannot say)."""
    if factor_id not in CHECKED:
        return None
    r = assess(factor_id, transactions)
    return r["reason"] if r["testable"] and r["supported"] is False else None
