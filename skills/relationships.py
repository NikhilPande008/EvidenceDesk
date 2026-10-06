"""
Relationship and network investigation — a deterministic map of who is connected to the case, and HOW WE KNOW.

Every link carries a provenance and the two are never blurred:

    SOURCED   stated by a field of the record the application was given (a customer reference on an alert, the counterparty and
              amount on a transaction row, a flag on a row, an attribute row such as a device or address identifier).
    INFERRED  computed by this application from sourced rows by a NAMED RULE (R-…): a repeated counterparty, a rapid pass-through, a
              counterparty that also appears in another case. An inferred link is a rule match, not a finding: it carries the rule's
              name, the rows it was computed from and a sentence saying what it does and does not show. No probabilities, no model.

What this module will not do
  * It does not resolve entities. Two labels are "the same counterparty" only if they are the same string after the stated
    normalisation (skills/evidence.py counterparty_key); a placeholder ("Multiple counterparties …") or an unidentified label
    ("Unknown UPI handle A") is NEVER matched against another row or another case.
  * It does not invent data. Shared device / address / document links are tested ONLY when attribute rows are supplied. The seeded
    dataset has none, so `coverage` says so for those three link types instead of showing an empty graph as a clean bill of health.
  * It does not conclude that a pattern is suspicious. The ALERT-01 / ALERT-16 pair show the same rapid pass-through and fan-in
    shape; what separates them is the destination and the documentation, and the explanations say so.

Output is plain data (nodes, edges, patterns, coverage). Free text from the record (counterparty names, channels, customer references)
is clipped and flattened here; the UI escapes it again at the point of display. Pure functions: no database, no model, no clock.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime
from typing import Any

from skills import evidence as ev

SOURCED, INFERRED = "SOURCED", "INFERRED"
RULE_MATCH = "RULE_MATCH"            # the only strength there is: the rule's condition was met. Not a probability.

RAPID_DAYS = 2                       # debits within this many days of the last credit count as "rapid"
RAPID_SHARE_PCT = 80
CONCENTRATION_SHARE_PCT = 70
FAN_IN_MIN_SOURCES = 3
FAN_IN_MAX_DESTINATIONS = 2
MAX_COUNTERPARTIES = 12
MAX_RELATED = 8
_CLIP = 80

ATTRIBUTE_KINDS = ("DEVICE", "ADDRESS", "DOCUMENT")
ATTRIBUTE_LABEL = {"DEVICE": "device", "ADDRESS": "address", "DOCUMENT": "identity document"}

# rule id → (title, what it shows, what it does NOT show)
RULES: dict[str, tuple[str, str]] = {
    "R-REPEAT-CP": ("Repeated counterparty", "The same counterparty appears on more than one row in the same direction. It does not show why."),
    "R-RAPID-PASS": ("Rapid pass-through", "Most of the credits left within a short time of arriving. It describes timing only; it does not show why the money moved."),
    "R-FAN-IN": ("Fan-in to few recipients", "Several distinct senders paid in and the money went to very few recipients. The shape is common to mule accounts and to ordinary pooled payments."),
    "R-CONCENTRATION": ("Beneficiary concentration", "Most of the money sent out went to one counterparty. It does not show that the counterparty is connected to the senders."),
    "R-CIRCULAR": ("Possible circular flow", "A counterparty both sent money in and received money out. Same-string match only; it may be a refund or two different parties."),
    "R-SHARED-BENEFICIARY": ("Shared beneficiary across cases", "The same counterparty string is a recipient in more than one case. Entity resolution has not been performed."),
    "R-SHARED-SOURCE": ("Shared sender across cases", "The same counterparty string is a sender in more than one case. Entity resolution has not been performed."),
    "R-ROLE-SWAP": ("Counterparty with opposite roles in two cases", "The same counterparty string received money in one case and sent money in another, which can indicate onward circulation."),
    "R-SAME-SIGNAL": ("Same detector signal in another case", "Another case was raised by the same detector rule, source and amount. No customer, account or counterparty is shared."),
    "R-SHARED-DEVICE": ("Common device", "Two customers are recorded against the same device identifier."),
    "R-SHARED-ADDRESS": ("Common address", "Two customers are recorded against the same address identifier."),
    "R-SHARED-DOCUMENT": ("Common identity document", "Two customers are recorded against the same identity-document identifier."),
}

COVERAGE_REASON = {
    "SHARED_DEVICE": "No device identifiers are supplied in this record, so a common device cannot be tested.",
    "SHARED_ADDRESS": "No address identifiers are supplied in this record, so a common address cannot be tested.",
    "SHARED_DOCUMENT": "No identity-document identifiers are supplied in this record, so a common document cannot be tested.",
    "SHARED_COUNTERPARTY": "Needs the other cases' transactions; they were not available.",
}


# ── small helpers ────────────────────────────────────────────────────────────
def _label(value: Any, n: int = _CLIP) -> str:
    s = re.sub(r"[\x00-\x1f\x7f]+", " ", "" if value is None else str(value))
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _d(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _inr(v: float) -> str:
    return f"₹{float(v):,.0f}"


def _amt(row: dict) -> float:
    try:
        v = float(row.get("amount_inr") or 0)
    except (TypeError, ValueError):
        return 0.0
    return v if v == v and v not in (float("inf"), float("-inf")) else 0.0


def _f(value) -> float:
    """A float or 0.0 — never raises (alert amounts come from a database column, but this module trusts nothing it is handed)."""
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return v if v == v and v not in (float("inf"), float("-inf")) else 0.0


def _alert_id(a: dict) -> str:
    return _label(a.get("ALERT_ID"), 40)


class _Graph:
    def __init__(self):
        self.nodes: dict[str, dict] = {}
        self.edges: list[dict] = []
        self.patterns: list[dict] = []

    def node(self, nid: str, kind: str, label: str, **extra) -> str:
        if nid not in self.nodes:
            self.nodes[nid] = {"id": nid, "kind": kind, "label": _label(label), "provenance": SOURCED, **extra}
        return nid

    def edge(self, src: str, dst: str, kind: str, provenance: str, text: str, *, rule: str | None = None, amount: float | None = None,
             count: int | None = None, refs=(), explanation: str = "") -> dict:
        e = {"id": f"e{len(self.edges) + 1}", "src": src, "dst": dst, "kind": kind, "provenance": provenance, "label": _label(text, 120),
             "rule": rule, "amount": amount, "count": count, "refs": [_label(r, 40) for r in list(refs)[:12]],
             "explanation": _label(explanation, 400)}
        self.edges.append(e)
        return e

    def pattern(self, rule: str, text: str, *, refs=(), involves=()) -> None:
        title, limit = RULES[rule]
        self.patterns.append({"rule": rule, "title": title, "provenance": INFERRED, "strength": RULE_MATCH, "explanation": _label(text, 500),
                              "does_not_show": limit, "refs": [_label(r, 40) for r in list(refs)[:12]], "involves": list(involves)})


# ── the network ──────────────────────────────────────────────────────────────
def build_network(alert: dict | None, transactions: list[dict] | None, *, other_cases: list[dict] | None = None,
                  attributes: list[dict] | None = None) -> dict:
    """The case's network.

    alert         the ALERTS_CURRENT row.            transactions  the case's rows (CoPilotSkills.load_transactions shape).
    other_cases   [{"alert": row, "transactions": [...]}] for cross-case links; None = not available (reported in `coverage`).
    attributes    [{"customer_ref", "kind": DEVICE|ADDRESS|DOCUMENT, "value"}] sourced attribute rows; None = not supplied.
    Returns {nodes, edges, patterns, related_cases, coverage, unresolved, truncated, summary}."""
    alert = alert or {}
    txns = [t for t in (transactions or []) if isinstance(t, dict)]
    g = _Graph()
    aid = _alert_id(alert)
    cust_ref = _label(alert.get("CUSTOMER_REF"), 40) or "customer not stated"

    cust = g.node("cust", "CUSTOMER", cust_ref, detail="Customer reference on the alert")
    acct_type = _label(alert.get("ACCOUNT_TYPE"), 30)
    acct = g.node("acct", "ACCOUNT", f"{acct_type.title() if acct_type else 'Account'} account", detail="Account type only; no account identifier is supplied")
    alrt = g.node("alert", "ALERT", aid or "alert", detail=f"{_label(alert.get('ALERT_TYPE'), 40).replace('_', ' ').title()} · {_label(alert.get('SIGNAL_SOURCE'), 30)}")
    g.edge(cust, acct, "HOLDS", SOURCED, "holds", explanation="The alert row names the customer and the account type.")
    g.edge(cust, alrt, "SUBJECT_OF", SOURCED, "is the subject of", explanation="The alert row carries this customer reference.")

    # ── counterparties: one node per distinct key, edges aggregate the rows ──
    explicit = [t for t in txns if not ev.is_aggregate_row(t)]
    aggregates = [t for t in txns if ev.is_aggregate_row(t)]
    by_key: dict[str, list[dict]] = defaultdict(list)
    for t in explicit:
        if t.get("type") in ("CREDIT", "DEBIT"):
            by_key[ev.counterparty_key(t.get("counterparty")) or f"~row:{t.get('txn_id')}"].append(t)
    ranked = sorted(by_key.items(), key=lambda kv: (-sum(_amt(r) for r in kv[1]), kv[0]))
    shown, hidden = ranked[:MAX_COUNTERPARTIES], ranked[MAX_COUNTERPARTIES:]
    cp_node: dict[str, str] = {}
    for i, (key, rows) in enumerate(shown, 1):
        label = _label(rows[0].get("counterparty") or "counterparty not stated")
        flagged = any(r.get("is_flagged") for r in rows)
        nid = g.node(f"cp{i}", "COUNTERPARTY", label, flagged=flagged, key=key, linkable=ev.is_linkable_counterparty(rows[0].get("counterparty")),
                     unidentified=ev.is_unidentified_counterparty(rows[0].get("counterparty")),
                     detail="A flag is recorded on at least one row" if flagged else "No flag recorded on its rows")
        cp_node[key] = nid
        for direction in ("CREDIT", "DEBIT"):
            part = [r for r in rows if r.get("type") == direction]
            if not part:
                continue
            total, ids = sum(_amt(r) for r in part), [r.get("txn_id") for r in part]
            if direction == "CREDIT":
                g.edge(nid, acct, "CREDIT_FROM", SOURCED, f"paid in {_inr(total)}" + (f" ({len(part)} rows)" if len(part) > 1 else ""),
                       amount=total, count=len(part), refs=ids, explanation="Stored credit row(s) name this counterparty.")
            else:
                g.edge(acct, nid, "DEBIT_TO", SOURCED, f"paid out {_inr(total)}" + (f" ({len(part)} rows)" if len(part) > 1 else ""),
                       amount=total, count=len(part), refs=ids, explanation="Stored debit row(s) name this counterparty.")
        if flagged:
            g.edge(nid, nid, "FLAGGED_ON_RECORD", SOURCED, "flag recorded", refs=[r.get("txn_id") for r in rows if r.get("is_flagged")],
                   explanation="The feed marked at least one row with this counterparty as flagged. The flag's source and date are not supplied.")
    if aggregates:
        n = g.node("agg", "AGGREGATE", "Aggregated counterparties", detail="Summary rows stand for many transfers", linkable=False, unidentified=False, flagged=any(t.get("is_flagged") for t in aggregates))
        for t in aggregates:
            kind = "CREDIT_FROM" if t.get("type") == "CREDIT" else "DEBIT_TO"
            src, dst = (n, acct) if kind == "CREDIT_FROM" else (acct, n)
            g.edge(src, dst, kind, SOURCED, f"{'paid in' if kind == 'CREDIT_FROM' else 'paid out'} {_inr(_amt(t))} (summary)", amount=_amt(t), count=1, refs=[t.get("txn_id")],
                   explanation="A reconciling summary row: individual counterparties are not resolvable.")

    # ── within-case patterns (INFERRED) ──────────────────────────────────────
    credits = [t for t in explicit if t.get("type") == "CREDIT"]
    debits = [t for t in explicit if t.get("type") == "DEBIT"]
    total_credit, total_debit = sum(_amt(t) for t in credits), sum(_amt(t) for t in debits)
    for key, rows in shown:
        for direction, word in (("CREDIT", "paid in"), ("DEBIT", "received")):
            part = [r for r in rows if r.get("type") == direction]
            if len(part) >= 2 and ev.is_linkable_counterparty(part[0].get("counterparty")):
                g.pattern("R-REPEAT-CP", f"“{_label(part[0].get('counterparty'), 50)}” {word} {len(part)} times in this case, {_inr(sum(_amt(r) for r in part))} in total.",
                          refs=[r.get("txn_id") for r in part], involves=[cp_node[key]])
    dated_credits = sorted(((d, t) for t in credits if (d := _d(t.get("date")))), key=lambda dt: (dt[0], str(dt[1].get("txn_id"))))
    if dated_credits and total_credit:
        window_end = dated_credits[-1][0].toordinal() + RAPID_DAYS
        quick = [t for t in debits if (d := _d(t.get("date"))) and dated_credits[0][0].toordinal() <= d.toordinal() <= window_end]
        share = sum(_amt(t) for t in quick) / total_credit * 100
        if share >= RAPID_SHARE_PCT:
            g.pattern("R-RAPID-PASS", f"{share:.1f}% of credits ({_inr(sum(_amt(t) for t in quick))} of {_inr(total_credit)}) left within {RAPID_DAYS} day(s) of the last credit.",
                      refs=[t.get("txn_id") for t in quick])
    sources = {ev.counterparty_key(t.get("counterparty")) for t in credits}
    dests = {ev.counterparty_key(t.get("counterparty")) for t in debits}
    if len(sources) >= FAN_IN_MIN_SOURCES and debits and len(dests) <= FAN_IN_MAX_DESTINATIONS:
        documented = sum(1 for k in sources if any(ev.documented_counterparty(t.get("counterparty")) for t in credits if ev.counterparty_key(t.get("counterparty")) == k))
        note = f" {documented} of the {len(sources)} senders are labelled as documented in the record (not independently checked)." if documented else ""
        g.pattern("R-FAN-IN", f"{len(sources)} distinct senders paid in; the money went to {len(dests)} recipient{'' if len(dests) == 1 else 's'}.{note}", refs=[t.get("txn_id") for t in credits + debits])
    if len([t for t in debits if ev.is_linkable_counterparty(t.get("counterparty"))]) >= 2 and total_debit:
        top_key, top_rows = max(((k, [t for t in debits if ev.counterparty_key(t.get("counterparty")) == k]) for k in dests if k), key=lambda kv: sum(_amt(r) for r in kv[1]), default=(None, []))
        if top_rows and ev.is_linkable_counterparty(top_rows[0].get("counterparty")):
            top_share = sum(_amt(r) for r in top_rows) / total_debit * 100
            if top_share >= CONCENTRATION_SHARE_PCT:
                g.pattern("R-CONCENTRATION", f"{top_share:.1f}% of the money sent out ({_inr(sum(_amt(r) for r in top_rows))}) went to “{_label(top_rows[0].get('counterparty'), 50)}”.",
                          refs=[r.get("txn_id") for r in top_rows], involves=[cp_node.get(top_key)] if top_key in cp_node else [])
    for key, rows in shown:
        kinds = {r.get("type") for r in rows}
        if kinds == {"CREDIT", "DEBIT"} and ev.is_linkable_counterparty(rows[0].get("counterparty")):
            g.pattern("R-CIRCULAR", f"“{_label(rows[0].get('counterparty'), 50)}” both paid in and received money in this case.", refs=[r.get("txn_id") for r in rows], involves=[cp_node[key]])

    # ── cross-case links (INFERRED) ──────────────────────────────────────────
    related: list[dict] = []
    coverage = {"SHARED_COUNTERPARTY": {"evaluable": other_cases is not None, "reason": None if other_cases is not None else COVERAGE_REASON["SHARED_COUNTERPARTY"]}}
    if other_cases is not None:
        mine = {k: rows for k, rows in by_key.items() if rows and ev.is_linkable_counterparty(rows[0].get("counterparty"))}
        for oc in other_cases:
            oa, otx = oc.get("alert") or {}, [t for t in (oc.get("transactions") or []) if isinstance(t, dict) and not ev.is_aggregate_row(t)]
            oid = _alert_id(oa)
            if not oid or oid == aid:
                continue
            reasons, kinds = [], set()
            if oa.get("CUSTOMER_REF") and str(oa.get("CUSTOMER_REF")) == str(alert.get("CUSTOMER_REF")):
                reasons.append("same customer reference")
                kinds.add("SAME_CUSTOMER")
            same_signal = (oa.get("ALERT_TYPE") and oa.get("ALERT_TYPE") == alert.get("ALERT_TYPE") and oa.get("SIGNAL_SOURCE") == alert.get("SIGNAL_SOURCE")
                           and oa.get("ALERT_AMOUNT_INR") is not None and _f(oa.get("ALERT_AMOUNT_INR")) == _f(alert.get("ALERT_AMOUNT_INR")))
            if same_signal:
                reasons.append("same detector rule, source and amount")
                kinds.add("SAME_SIGNAL")
            theirs: dict[str, list[dict]] = defaultdict(list)
            for t in otx:
                if t.get("type") in ("CREDIT", "DEBIT") and ev.is_linkable_counterparty(t.get("counterparty")):
                    theirs[ev.counterparty_key(t.get("counterparty"))].append(t)
            shared_cp = []
            for key, rows in mine.items():
                if key in theirs:
                    my_roles, their_roles = {r["type"] for r in rows}, {r["type"] for r in theirs[key]}
                    shared_cp.append((key, rows, theirs[key], my_roles, their_roles))
            if shared_cp:
                reasons.append(f"{len(shared_cp)} shared counterpart{'y' if len(shared_cp) == 1 else 'ies'}")
                kinds.add("SHARED_COUNTERPARTY")
            if not reasons:
                continue
            if len(related) >= MAX_RELATED:
                coverage["related_truncated"] = True
                continue
            rnode = g.node(f"rc{len(related) + 1}", "RELATED_CASE", oid, detail=_label("; ".join(reasons).capitalize(), 120), linkable=False, unidentified=False, flagged=False,
                           provenance=INFERRED if "SAME_CUSTOMER" not in kinds else SOURCED)
            related.append({"alert_id": oid, "node": rnode, "reasons": reasons, "kinds": sorted(kinds), "alert_type": _label(oa.get("ALERT_TYPE"), 40),
                            "amount": _f(oa.get("ALERT_AMOUNT_INR")), "status": _label(oa.get("ALERT_STATUS"), 20)})
            if "SAME_CUSTOMER" in kinds:
                g.edge(cust, rnode, "SUBJECT_OF", SOURCED, "is also the subject of", explanation="The other alert carries the same customer reference.")
            if "SAME_SIGNAL" in kinds:
                g.edge(alrt, rnode, "SIMILAR_SIGNAL", INFERRED, "same detector signal", rule="R-SAME-SIGNAL",
                       explanation=RULES["R-SAME-SIGNAL"][1])
                g.pattern("R-SAME-SIGNAL", f"{oid} was raised by the same detector rule ({_label(alert.get('ALERT_TYPE'), 40).replace('_', ' ').title()}), source and amount ({_inr(_f(alert.get('ALERT_AMOUNT_INR')))}). "
                          "No customer, account or counterparty is shared.", refs=[oid], involves=[rnode])
            for key, my_rows, their_rows, mr, tr in shared_cp:
                name = _label(my_rows[0].get("counterparty"), 50)
                target = cp_node.get(key)
                if target:
                    g.edge(target, rnode, "ALSO_IN", INFERRED, "also appears in", rule="R-SHARED-BENEFICIARY" if mr == tr == {"DEBIT"} else "R-SHARED-SOURCE" if mr == tr == {"CREDIT"} else "R-ROLE-SWAP",
                           refs=[r.get("txn_id") for r in their_rows], explanation=f"The string “{name}” appears in {oid}; no entity resolution was performed.")
                if mr == tr == {"DEBIT"}:
                    g.pattern("R-SHARED-BENEFICIARY", f"“{name}” also received money in {oid}.", refs=[r.get("txn_id") for r in their_rows], involves=[x for x in (target, rnode) if x])
                elif mr == tr == {"CREDIT"}:
                    g.pattern("R-SHARED-SOURCE", f"“{name}” also paid in to {oid}.", refs=[r.get("txn_id") for r in their_rows], involves=[x for x in (target, rnode) if x])
                elif "DEBIT" in (mr | tr) and "CREDIT" in (mr | tr):
                    g.pattern("R-ROLE-SWAP", f"“{name}” is a {'/'.join(sorted(r.lower() for r in mr))} counterparty here and a {'/'.join(sorted(r.lower() for r in tr))} counterparty in {oid}.",
                              refs=[r.get("txn_id") for r in their_rows], involves=[x for x in (target, rnode) if x])

    # ── shared attributes: only where attribute rows were supplied ───────────
    attrs = [a for a in (attributes or []) if isinstance(a, dict) and a.get("kind") in ATTRIBUTE_KINDS and a.get("value") and a.get("customer_ref")]
    for kind in ATTRIBUTE_KINDS:
        key = f"SHARED_{kind}"
        rows = [a for a in attrs if a["kind"] == kind]
        if attributes is None or not rows:
            coverage[key] = {"evaluable": False, "reason": COVERAGE_REASON[key]}
            continue
        coverage[key] = {"evaluable": True, "reason": None}
        by_value: dict[str, set[str]] = defaultdict(set)
        for a in rows:
            by_value[str(a["value"])].add(str(a["customer_ref"]))
        mine_values = {str(a["value"]) for a in rows if str(a["customer_ref"]) == str(alert.get("CUSTOMER_REF"))}
        for i, value in enumerate(sorted(mine_values), 1):
            holder = g.node(f"{kind.lower()}{i}", kind, f"{ATTRIBUTE_LABEL[kind].title()} {_label(value, 40)}", detail=f"Supplied {ATTRIBUTE_LABEL[kind]} identifier", value=_label(value, 40))
            g.edge(cust, holder, f"HAS_{kind}", SOURCED, f"is recorded against {ATTRIBUTE_LABEL[kind]}", explanation="An attribute row ties this customer to the identifier.")
            others = sorted(by_value[value] - {str(alert.get("CUSTOMER_REF"))})
            for j, other in enumerate(others, 1):
                onode = g.node(f"{kind.lower()}{i}_c{j}", "CUSTOMER", _label(other, 40), detail="Other customer reference", linkable=False, unidentified=False, flagged=False)
                g.edge(onode, holder, f"HAS_{kind}", SOURCED, f"is recorded against {ATTRIBUTE_LABEL[kind]}", explanation="An attribute row ties that customer to the same identifier.")
            if others:
                g.pattern(f"R-SHARED-{kind}", f"{len(others) + 1} customers are recorded against {ATTRIBUTE_LABEL[kind]} identifier {_label(value, 40)}: this one and {', '.join(_label(o, 30) for o in others[:4])}"
                          + (f" (+{len(others) - 4} more)" if len(others) > 4 else "") + ".", refs=[value], involves=[holder])

    unresolved = []
    if str(alert.get("ALERT_TYPE") or "").upper() == "DEVICE_IDENTITY_LINKAGE" and not coverage.get("SHARED_DEVICE", {}).get("evaluable"):
        unresolved.append("The detector reports a shared-device linkage across accounts, but no device identifier or linked account is in this record: the link is asserted, not shown.")
    if str(alert.get("ALERT_TYPE") or "").upper() == "BENEFICIARY_CONCENTRATION" and not related:
        unresolved.append("The detector reports several accounts paying one beneficiary; the other accounts are not in this record, so the concentration cannot be shown here.")
    if aggregates:
        unresolved.append("Aggregated rows hide the individual counterparties; no counterparty-level link can be drawn for them.")

    nodes = sorted(g.nodes.values(), key=lambda n: (["CUSTOMER", "ACCOUNT", "ALERT", "COUNTERPARTY", "AGGREGATE", "DEVICE", "ADDRESS", "DOCUMENT", "RELATED_CASE"].index(n["kind"]), n["id"]))
    edges = sorted(g.edges, key=lambda e: (e["provenance"] != SOURCED, -(e["amount"] or 0), e["id"]))
    return {
        "nodes": nodes, "edges": edges, "patterns": g.patterns, "related_cases": related, "coverage": coverage, "unresolved": unresolved,
        "truncated": {"counterparties": len(hidden), "counterparty_amount": round(sum(sum(_amt(r) for r in rows) for _, rows in hidden), 2)},
        "summary": {"nodes": len(nodes), "edges": len(edges), "sourced_edges": sum(1 for e in edges if e["provenance"] == SOURCED),
                    "inferred_edges": sum(1 for e in edges if e["provenance"] == INFERRED), "patterns": len(g.patterns), "related_cases": len(related)},
        "legend": {SOURCED: "Stated by a field of the record the application was given.",
                   INFERRED: "Computed here from sourced rows by the named rule. A rule match, not a finding and not entity resolution."},
    }


def edge_rows(network: dict) -> list[dict]:
    """The edge list as table rows (plain strings) for display: from → to, what the link is, provenance, rule and explanation."""
    names = {n["id"]: n["label"] for n in network["nodes"]}
    out = []
    for e in network["edges"]:
        if e["kind"] == "FLAGGED_ON_RECORD":
            out.append({"Link": "Flag on record", "From": names.get(e["src"], "?"), "To": "—", "Evidence": ", ".join(e["refs"]) or "—", "Provenance": e["provenance"],
                        "Rule": "—", "What it shows": e["explanation"]})
            continue
        out.append({"Link": e["label"], "From": names.get(e["src"], "?"), "To": names.get(e["dst"], "?"), "Evidence": ", ".join(e["refs"]) or "—",
                    "Provenance": e["provenance"], "Rule": e["rule"] or "—", "What it shows": e["explanation"]})
    return out


def flow_columns(network: dict) -> dict:
    """The money-flow map as three columns for display: who paid in → the customer's account → who was paid. Counterparties only."""
    nodes = {n["id"]: n for n in network["nodes"]}
    paid_in, paid_out = [], []
    for e in network["edges"]:
        if e["kind"] == "CREDIT_FROM" and e["src"] in nodes:
            paid_in.append({"label": nodes[e["src"]]["label"], "amount": e["amount"], "count": e["count"], "flagged": bool(nodes[e["src"]].get("flagged")),
                            "unidentified": bool(nodes[e["src"]].get("unidentified"))})
        elif e["kind"] == "DEBIT_TO" and e["dst"] in nodes:
            paid_out.append({"label": nodes[e["dst"]]["label"], "amount": e["amount"], "count": e["count"], "flagged": bool(nodes[e["dst"]].get("flagged")),
                             "unidentified": bool(nodes[e["dst"]].get("unidentified"))})
    centre = {"customer": nodes["cust"]["label"], "account": nodes["acct"]["label"], "alert": nodes["alert"]["label"]}
    return {"paid_in": paid_in, "centre": centre, "paid_out": paid_out}
