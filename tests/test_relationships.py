"""
Relationship / network investigation (skills/relationships.py): sourced versus inferred links, rule-named patterns, what cannot be tested,
and the guarantees that make the view safe — placeholders are never entities, no data is invented, hostile text stays bounded text.

Offline. Usage:  python3 tests/test_relationships.py     (or pytest)
"""

from __future__ import annotations

import re
import sys

from _helpers import ROOT, Runner

sys.path.insert(0, str(ROOT / "scripts"))
import setup_alerts as seed  # noqa: E402

from skills import relationships as R  # noqa: E402


def seeded(aid):
    a = next(x for x in seed.ALERTS if x["ALERT_ID"] == aid)
    tx = [{"txn_id": t["TXN_ID"], "date": t["TXN_DATE"], "type": t["TXN_TYPE"], "amount_inr": t["AMOUNT_INR"], "channel": t["CHANNEL"],
           "counterparty": t["COUNTERPARTY"], "is_flagged": t["IS_FLAGGED"]} for t in seed.TRANSACTIONS if t["ALERT_ID"] == aid]
    return a, tx


def others_of(aid):
    return [{"alert": a, "transactions": seeded(a["ALERT_ID"])[1]} for a in seed.ALERTS if a["ALERT_ID"] != aid]


def net(aid, **kw):
    a, tx = seeded(aid)
    return R.build_network(a, tx, other_cases=others_of(aid), **kw)


def t(tid, typ, amt, cp, d="2026-08-10", flagged=False):
    return {"txn_id": tid, "date": d, "type": typ, "amount_inr": amt, "channel": "UPI", "counterparty": cp, "is_flagged": flagged}


def al(aid="A-1", cust="CUST-A", **kw):
    return {"ALERT_ID": aid, "CUSTOMER_REF": cust, "ACCOUNT_TYPE": "SAVINGS", "ALERT_TYPE": "MULE_PASSTHROUGH", "SIGNAL_SOURCE": "I4C", "ALERT_AMOUNT_INR": 100000,
            "ALERT_DATE": "2026-08-12", **kw}


def rules(n):
    return [p["rule"] for p in n["patterns"]]


# ── sourced versus inferred ──────────────────────────────────────────────────

def test_every_link_is_sourced_or_inferred_and_every_inferred_link_names_its_rule():
    for a in seed.ALERTS:
        n = net(a["ALERT_ID"])
        for e in n["edges"]:
            assert e["provenance"] in (R.SOURCED, R.INFERRED) and e["explanation"], (a["ALERT_ID"], e)
            if e["provenance"] == R.INFERRED:
                assert e["rule"] in R.RULES, (a["ALERT_ID"], e)
            else:
                assert e["rule"] is None, "a sourced link is stated by the record; it has no inference rule"
        for p in n["patterns"]:
            assert p["provenance"] == R.INFERRED and p["strength"] == R.RULE_MATCH and p["rule"] in R.RULES and p["does_not_show"]
        assert n["summary"]["sourced_edges"] + n["summary"]["inferred_edges"] == n["summary"]["edges"]
        assert set(n["legend"]) == {R.SOURCED, R.INFERRED}
    print("  [PASS] 16 seeded cases: every edge SOURCED or INFERRED; every INFERRED edge and every pattern names a rule and states what it does NOT show; the strength is 'rule match', never a probability")


def test_the_demo_pair_shows_the_same_shape_and_the_difference_is_in_the_destination():
    n1, n16 = net("ALERT-01"), net("ALERT-16")
    assert {"R-RAPID-PASS", "R-FAN-IN", "R-CONCENTRATION", "R-REPEAT-CP", "R-SAME-SIGNAL"} == set(rules(n1))
    assert {"R-RAPID-PASS", "R-FAN-IN", "R-SAME-SIGNAL"} == set(rules(n16)), "the legitimate twin has the same timing and fan-in shape"
    flagged1 = [x for x in n1["nodes"] if x["kind"] == "COUNTERPARTY" and x["flagged"]]
    flagged16 = [x for x in n16["nodes"] if x["kind"] == "COUNTERPARTY" and x["flagged"]]
    assert len(flagged1) == 1 and not flagged16
    fan16 = next(p for p in n16["patterns"] if p["rule"] == "R-FAN-IN")
    assert "3 of the 3 senders are labelled as documented" in fan16["explanation"] and "not independently checked" in fan16["explanation"]
    assert not any(e["kind"] == "ALSO_IN" for e in n1["edges"] + n16["edges"]), "the pair shares a signal, not an entity"
    rel = n1["related_cases"][0]
    assert rel["alert_id"] == "ALERT-16" and rel["kinds"] == ["SAME_SIGNAL"] and "no customer, account or counterparty is shared" in next(p for p in n1["patterns"] if p["rule"] == "R-SAME-SIGNAL")["explanation"].lower()
    print("  [PASS] ALERT-01 and ALERT-16 both show rapid pass-through and fan-in; only ALERT-01's destination carries a flag; they are linked as 'same signal' and explicitly share no entity")


# ── cross-case links: what is and is not matched ─────────────────────────────

def test_placeholders_and_unidentified_labels_are_never_matched_across_cases():
    agg = [t("T1", "CREDIT", 100000, "Multiple counterparties (see alert narrative)")]
    unk = [t("T2", "CREDIT", 50000, "Unknown UPI handle A"), t("T3", "DEBIT", 40000, "Unknown UPI handle B")]
    for mine in (agg, unk):
        n = R.build_network(al("A-1"), mine, other_cases=[{"alert": al("A-2", "CUST-B"), "transactions": mine}])
        assert not [p for p in n["patterns"] if p["rule"] in ("R-SHARED-BENEFICIARY", "R-SHARED-SOURCE", "R-ROLE-SWAP")], n["patterns"]
        assert not [e for e in n["edges"] if e["kind"] == "ALSO_IN"]
    n = net("ALERT-05")
    assert not n["related_cases"] or all("SHARED_COUNTERPARTY" not in r["kinds"] for r in n["related_cases"]), "12 seeded alerts share the same summary label; it is not an entity"
    print("  [PASS] 'Multiple counterparties …' and 'Unknown UPI handle A' are never linked across cases (12 seeded alerts share the same summary label and no link is drawn)")


def test_shared_beneficiary_shared_source_and_role_swap_across_cases():
    mine = [t("T1", "CREDIT", 100000, "Sender One", "2026-08-01"), t("T2", "DEBIT", 95000, "Delta Exports (I4C-flagged)", "2026-08-02", True)]
    other_debit = [t("U1", "CREDIT", 20000, "Someone Else", "2026-08-03"), t("U2", "DEBIT", 15000, "delta exports", "2026-08-04")]
    n = R.build_network(al("A-1"), mine, other_cases=[{"alert": al("A-2", "CUST-B", ALERT_TYPE="OTHER"), "transactions": other_debit}])
    assert "R-SHARED-BENEFICIARY" in rules(n) and n["related_cases"][0]["kinds"] == ["SHARED_COUNTERPARTY"]
    edge = next(e for e in n["edges"] if e["kind"] == "ALSO_IN")
    assert edge["provenance"] == R.INFERRED and edge["rule"] == "R-SHARED-BENEFICIARY" and "no entity resolution was performed" in edge["explanation"]
    src = R.build_network(al("A-1"), [t("T1", "CREDIT", 100000, "Sender One")], other_cases=[{"alert": al("A-2", "CUST-B", ALERT_TYPE="OTHER"), "transactions": [t("U1", "CREDIT", 1, "sender one")]}])
    assert "R-SHARED-SOURCE" in rules(src)
    swap = R.build_network(al("A-1"), [t("T1", "DEBIT", 100000, "Sender One")], other_cases=[{"alert": al("A-2", "CUST-B", ALERT_TYPE="OTHER"), "transactions": [t("U1", "CREDIT", 1, "Sender One")]}])
    assert "R-ROLE-SWAP" in rules(swap)
    same_cust = R.build_network(al("A-1"), mine, other_cases=[{"alert": al("A-3", "CUST-A", ALERT_TYPE="OTHER"), "transactions": []}])
    e = next(e for e in same_cust["edges"] if e["dst"].startswith("rc"))
    assert e["provenance"] == R.SOURCED and "SAME_CUSTOMER" in same_cust["related_cases"][0]["kinds"], "a shared customer reference is a stated field"
    print("  [PASS] same normalised string across cases → shared beneficiary / shared source / role swap (all INFERRED, 'no entity resolution was performed'); same customer reference → SOURCED")


def test_a_circular_flow_inside_one_case_is_a_same_string_rule_match():
    n = R.build_network(al(), [t("T1", "CREDIT", 50000, "Echo Traders"), t("T2", "DEBIT", 48000, "Echo Traders", "2026-08-11")])
    p = next(p for p in n["patterns"] if p["rule"] == "R-CIRCULAR")
    assert "both paid in and received money" in p["explanation"] and "refund" in p["does_not_show"]
    print("  [PASS] circular flow: a counterparty on both sides of one case is reported with a caveat that it may be a refund or two different parties")


# ── what cannot be tested ────────────────────────────────────────────────────

def test_shared_device_address_document_are_tested_only_where_attribute_rows_exist():
    n = net("ALERT-09")
    for kind in ("SHARED_DEVICE", "SHARED_ADDRESS", "SHARED_DOCUMENT"):
        assert n["coverage"][kind]["evaluable"] is False and "supplied" in n["coverage"][kind]["reason"]
    assert any("shared-device linkage" in u and "asserted, not shown" in u for u in n["unresolved"]), "ALERT-09's detector asserts a device link the record cannot show"
    assert not [p for p in n["patterns"] if "DEVICE" in p["rule"]]
    attrs = [{"customer_ref": "CUST-A", "kind": "DEVICE", "value": "DEV-0001"}, {"customer_ref": "CUST-B", "kind": "DEVICE", "value": "DEV-0001"},
             {"customer_ref": "CUST-C", "kind": "DEVICE", "value": "DEV-0001"}, {"customer_ref": "CUST-A", "kind": "ADDRESS", "value": "ADDR-7"},
             {"customer_ref": "CUST-D", "kind": "ADDRESS", "value": "ADDR-8"}]
    n = R.build_network(al(), [t("T1", "CREDIT", 1, "X Y")], other_cases=[], attributes=attrs)
    assert n["coverage"]["SHARED_DEVICE"]["evaluable"] and n["coverage"]["SHARED_ADDRESS"]["evaluable"] and not n["coverage"]["SHARED_DOCUMENT"]["evaluable"]
    dev = next(p for p in n["patterns"] if p["rule"] == "R-SHARED-DEVICE")
    assert "3 customers" in dev["explanation"] and "CUST-B" in dev["explanation"] and not [p for p in n["patterns"] if p["rule"] == "R-SHARED-ADDRESS"]
    assert all(e["provenance"] == R.SOURCED for e in n["edges"] if e["kind"].startswith("HAS_")), "an attribute row is a sourced link; the sharing is the inferred pattern"
    print("  [PASS] without attribute rows, device / address / document links are reported as 'not testable' (and ALERT-09's asserted link as unresolved); with them, a common device is found and the attribute edges stay SOURCED")


def test_aggregated_rows_are_one_placeholder_node_and_hide_counterparty_links():
    n = net("ALERT-06")
    kinds = [x["kind"] for x in n["nodes"]]
    assert kinds.count("AGGREGATE") == 1 and kinds.count("COUNTERPARTY") == 0 and any("Aggregated rows hide" in u for u in n["unresolved"])
    print("  [PASS] a summary-only case shows one 'aggregated counterparties' node and says no counterparty-level link can be drawn")


# ── safety and determinism ───────────────────────────────────────────────────

def test_hostile_names_are_clipped_flattened_and_bounded():
    hostile = "![x](https://attacker.example/p.png)\n\n[c](https://attacker.example/x)\t<img src=x onerror=alert(1)> " + "Z" * 5000
    rows = [t(f"T{i}", "CREDIT" if i % 2 else "DEBIT", 1000 + i, f"{hostile} {i}", flagged=bool(i % 3)) for i in range(60)]
    a = al(CUSTOMER_REF=hostile, ACCOUNT_TYPE=hostile, ALERT_TYPE=hostile, SIGNAL_SOURCE=hostile)
    n = R.build_network(a, rows, other_cases=[{"alert": al("A-9", ALERT_TYPE=hostile, SIGNAL_SOURCE=hostile), "transactions": rows}])
    assert len([x for x in n["nodes"] if x["kind"] == "COUNTERPARTY"]) <= R.MAX_COUNTERPARTIES and n["truncated"]["counterparties"] > 0
    for x in n["nodes"]:
        assert len(x["label"]) <= 80 and "\n" not in x["label"] and "\t" not in x["label"]
    for e in n["edges"]:
        assert len(e["label"]) <= 120 and len(e["explanation"]) <= 400 and "\n" not in e["label"]
    for p in n["patterns"]:
        assert len(p["explanation"]) <= 500 and "\n" not in p["explanation"]
    assert len(n["related_cases"]) <= R.MAX_RELATED
    for row in R.edge_rows(n):
        assert all(isinstance(v, str) for v in row.values())
    print(f"  [PASS] 60 hostile 5 000-character counterparty names: nodes ≤ {R.MAX_COUNTERPARTIES} counterparties (+{n['truncated']['counterparties']} counted, not drawn), every label, edge text and pattern text clipped and flattened")


def test_the_module_builds_no_markup_and_is_deterministic():
    src = open(ROOT / "skills/relationships.py").read()
    assert "unsafe_allow_html" not in src and "streamlit" not in src and not re.search(r"<(?:div|span|a|img|svg)\b", src), "the module returns data; the UI escapes it"
    for banned in ("snowflake", "cortex", "datetime.now", "random"):
        assert banned not in src.lower().replace("date.today", ""), banned
    a, tx = seeded("ALERT-01")
    assert R.build_network(a, tx, other_cases=others_of("ALERT-01")) == R.build_network(a, list(tx), other_cases=others_of("ALERT-01"))
    shuffled = list(reversed(tx))
    assert [p["rule"] for p in R.build_network(a, shuffled, other_cases=others_of("ALERT-01"))["patterns"]] == [p["rule"] for p in R.build_network(a, tx, other_cases=others_of("ALERT-01"))["patterns"]]
    print("  [PASS] no HTML / Streamlit / database / model / clock in the module; same input → same network, and row order does not change which patterns fire")


def test_edge_rows_and_flow_columns_are_what_the_ui_needs():
    n = net("ALERT-01")
    rows = R.edge_rows(n)
    assert rows and set(rows[0]) == {"Link", "From", "To", "Evidence", "Provenance", "Rule", "What it shows"} and {r["Provenance"] for r in rows} <= {"SOURCED", "INFERRED"}
    cols = R.flow_columns(n)
    assert [c["label"] for c in cols["paid_out"]] == ["UPI handle C (I4C-flagged)"] and cols["paid_out"][0]["flagged"] and cols["paid_out"][0]["amount"] == 340700
    assert sorted(c["label"] for c in cols["paid_in"]) == ["Unknown UPI handle A", "Unknown UPI handle B", "Unknown UPI handle D"] and all(c["unidentified"] for c in cols["paid_in"])
    assert cols["centre"]["customer"] == "CUST-01"
    print("  [PASS] the edge table (Link · From · To · Evidence · Provenance · Rule · What it shows) and the paid-in → account → paid-out columns carry exactly the sourced facts")


TESTS = [
    test_every_link_is_sourced_or_inferred_and_every_inferred_link_names_its_rule, test_the_demo_pair_shows_the_same_shape_and_the_difference_is_in_the_destination,
    test_placeholders_and_unidentified_labels_are_never_matched_across_cases, test_shared_beneficiary_shared_source_and_role_swap_across_cases,
    test_a_circular_flow_inside_one_case_is_a_same_string_rule_match, test_shared_device_address_document_are_tested_only_where_attribute_rows_exist,
    test_aggregated_rows_are_one_placeholder_node_and_hide_counterparty_links, test_hostile_names_are_clipped_flattened_and_bounded,
    test_the_module_builds_no_markup_and_is_deterministic, test_edge_rows_and_flow_columns_are_what_the_ui_needs,
]



def test_a_non_numeric_alert_amount_cannot_crash_the_network():
    odd = {"alert": al("A-2", "CUST-B", ALERT_AMOUNT_INR="not a number"), "transactions": [t("U1", "CREDIT", 1, "Sender One")]}
    n = R.build_network(al(ALERT_AMOUNT_INR=float("nan")), [t("T1", "CREDIT", 100000, "Sender One")], other_cases=[odd, {"alert": al("A-3", ALERT_AMOUNT_INR=None), "transactions": []}])
    assert n["summary"]["nodes"] >= 3 and any("shared counterpart" in " ".join(r["reasons"]) for r in n["related_cases"])
    print("  [PASS] a non-numeric, NaN or missing alert amount is treated as 0 and never raises")


TESTS.append(test_a_non_numeric_alert_amount_cannot_crash_the_network)


if __name__ == "__main__":
    raise SystemExit(Runner("Relationships and network (offline)").run(TESTS))
