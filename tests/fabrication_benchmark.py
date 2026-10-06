"""
Fabrication-catch benchmark for the deterministic evidence validator (skills/grounding.py).

Question it answers: when a Ground-of-Suspicion narrative states a fact that is not in the case record, how often does the
validator say so, and how often does it wrongly object to a narrative that is true to the record?

Method (all deterministic, offline, no model, no Snowflake):
  record       ALERT-01 exactly as seeded (scripts/setup_alerts.py): five UPI transactions, a Rs.28K/month profile, the alert narrative.
  faithful     hand-written narratives true to the record (BASES), plus FAITHFUL_COUNT narratives assembled from true facts in varied
               notations (₹/Rs/INR, lakh/L, four date formats, derived sums, correct percentages and multiples).
  fabricated   every FABRICATIONS entry inserts or substitutes ONE wrong fact of one claim class into a faithful base. Each fact is
               tried in two bases. Nothing is random: the same code produces the same narratives.
  limits       MIS_ATTRIBUTIONS: every fact in the sentence IS in the record, but the claim is false (wrong direction, wrong party,
               wrong date for that amount). The validator checks that a fact exists, not that it is attached to the right event, so
               these are expected to pass; they are measured so the limit is a published number, not a surprise.
  precision    which wrong figures can pass because a stated amount is accepted within half a displayed unit of any figure derivable
               from the record (transactions, totals, subset sums, declared income).

Caveat that belongs next to every number from here: the author wrote both the validator and these narratives. This is a regression
and calibration record with honest error bars (Wilson 95% intervals), not an independent benchmark.
"""

from __future__ import annotations

import itertools
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import setup_alerts as seed  # noqa: E402
from skills.grounding import extract_amounts, parse_profile, validate_narrative  # noqa: E402

ALERT_ID = "ALERT-01"
FAITHFUL_COUNT = 64
SEED = 20261005


# ── the record ───────────────────────────────────────────────────────────────

def build_record(alert_id: str = ALERT_ID) -> dict:
    alert = next(a for a in seed.ALERTS if a["ALERT_ID"] == alert_id)
    txns = [{"txn_id": t["TXN_ID"], "date": t["TXN_DATE"], "type": t["TXN_TYPE"], "amount_inr": t["AMOUNT_INR"], "channel": t["CHANNEL"],
             "counterparty": t["COUNTERPARTY"], "is_flagged": t["IS_FLAGGED"]} for t in seed.TRANSACTIONS if t["ALERT_ID"] == alert_id]
    return {"transactions": txns, "profile_text": alert["CUSTOMER_PROFILE"], "alert_narrative": alert["ALERT_NARRATIVE"],
            "context_dates": [str(alert["ALERT_DATE"])[:10]]}


RECORD = build_record()
EXPLICIT_ALERTS = sorted(seed.EXPLICIT_TXNS)                      # the alerts with real transaction rows: 01, 02, 04, 16


def validate(narrative: str, record: dict | None = None) -> dict:
    record = record or RECORD
    return validate_narrative(narrative, record["transactions"], profile_text=record["profile_text"],
                              alert_narrative=record["alert_narrative"], context_dates=record["context_dates"])


# ── faithful narratives for the OTHER alerts (guards against a validator that only works on ALERT-01) ──────────────

def _inr(v: float) -> str:
    s = str(int(v))
    head, tail = s[:-3], s[-3:]
    groups = []
    while head:
        groups.append(head[-2:])
        head = head[:-2]
    return ",".join([*reversed(groups), tail]) if groups else tail


def _amount_forms(v: float) -> list[str]:
    forms = [f"Rs.{_inr(v)}", f"INR {int(v)}", f"{int(v)} rupees", f"₹{_inr(v)}"]
    if v >= 1e5 and v % 1000 == 0:
        forms += [f"Rs.{v / 1e5:g}L", f"₹{v / 1e5:g} lakh"]
    return forms


def _date_forms(iso: str) -> list[str]:
    y, m, d = iso.split("-")
    mon = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][int(m) - 1]
    return [iso, f"{int(d)} {mon} {y}", f"{d}.{m}.{y}", f"{d}/{m}/{y}", f"{y}/{m}/{d}"]


CROSS_RECORD_HAND_WRITTEN: dict[str, list[str]] = {
    "ALERT-04": [
        "The customer, a State PWD engineer and PEP with Rs.95K per month declared, received six NEFT credits totalling Rs.48,00,000 from four contractors.",
        "ABC Infrastructure Ltd credited Rs.8,50,000 on 2026-06-15 and Rs.11,00,000 on 15th July. DEF Engineering Pvt Ltd paid Rs.6,20,000 on June 20 and Rs.9,30,000 on 2026-08-15.",
        "GHI Constructions paid Rs.4.8 lakh on 2026-07-20 and JKL Roadways Pvt Ltd paid Rs.8.2 lakh on 20th August.",
        "All credits arrived by NEFT. The customer is a politically exposed person on a government salary of Rs.95,000 per month.",
        "Credits of Rs.8,50,000 and Rs.6,20,000 in June were followed by Rs.11,00,000 and Rs.4,80,000 in July.",
    ],
    "ALERT-02": [
        "Three linked savings accounts received cash deposits of Rs.1,42,500, Rs.1,42,500 and Rs.1,35,000 on 2026-08-19, totalling Rs.4,20,000.",
        "On 20th August Rs.4,20,000 was moved by NEFT to a single current account at another bank.",
        "The customer is a daily labourer with a declared income of Rs.10K per month, yet cash deposits totalled Rs.4.2 lakh.",
        "All three credits were cash and the single debit was by NEFT on 2026-08-20.",
    ],
}


def cross_record_faithful() -> list[tuple[str, str, str]]:
    """(alert id, narrative id, text) for every alert with real rows. Auto-generated narratives restate rows verbatim in varied notation, so they
    are true by construction; the hand-written ones read like real prose."""
    rng = random.Random(SEED + 1)
    out = []
    for aid in EXPLICIT_ALERTS:
        rec = build_record(aid)
        txns = rec["transactions"]
        for i in range(4):
            sentences = []
            for t in rng.sample(txns, k=min(3, len(txns))):
                verb = "credited" if t["type"] == "CREDIT" else "debited"
                cp = f"{t['counterparty']}"
                sentences.append(f"{rng.choice(_date_forms(str(t['date'])[:10]))}: {rng.choice(_amount_forms(float(t['amount_inr'])))} {verb} via {t['channel']} ({cp}).")
            out.append((aid, f"{aid}-auto{i + 1}", " ".join(sentences)))
        for j, text in enumerate(CROSS_RECORD_HAND_WRITTEN.get(aid, []), start=1):
            out.append((aid, f"{aid}-hand{j}", text))
    return out


# ── faithful narratives ──────────────────────────────────────────────────────

BASES = [
    ("B1", "I formed suspicion after credits of Rs.1.1L, Rs.1.4L and Rs.0.95L (total Rs.3.45L) from unidentified UPI handles A, B and D. "
           "Within days, debits of Rs.2.465L and Rs.0.942L went to UPI handle C, which is I4C-flagged: 98.8% of the credits left the account. "
           "The customer is a data entry operator with a declared income of Rs.28K per month, so the credits are about 12 times that income, "
           "and none of the counterparties is documented."),
    ("B2", "Between 13 and 17 August 2026 the account received three UPI credits of Rs.1,10,000, Rs.1,40,000 and Rs.95,000, totalling Rs.3,45,000, "
           "from unidentified UPI handles A, B and D. Debits of Rs.2,46,500 and Rs.94,200 were then made to UPI handle C, which is I4C-flagged."),
    ("B3", "On 2026-08-13, 2026-08-14 and 2026-08-16 the account received UPI credits from unidentified UPI handles. On 2026-08-15 and 2026-08-17 "
           "funds left to UPI handle C (I4C-flagged). The customer's declared income is Rs.28K per month."),
    ("B4", "The customer is a data entry operator whose account is 14 months old. Credits of ₹3.45 lakh arrived over four days through UPI "
           "and ₹3.407 lakh was debited to a flagged handle."),
    ("B5", "Transactions T01-1, T01-2 and T01-4 are credits; T01-3 and T01-5 are debits to the flagged handle. The credits total Rs.3.45L "
           "and 98.8% of that left the account within days."),
    ("B6", "The I4C Suspect Registry linkage fired on UPI handle C. The credits of Rs.3.45L are about 12 times the declared income of "
           "Rs.28K per month, and none of the counterparties is documented."),
]

_TRUE = {
    "c1": ["Rs.1,10,000", "₹1.1 lakh", "Rs.1.1L", "INR 110000"], "c2": ["Rs.1,40,000", "₹1.4 lakh", "Rs.1.4L", "INR 140000"],
    "c4": ["Rs.95,000", "₹0.95 lakh", "Rs.0.95L", "INR 95000"], "ctot": ["Rs.3,45,000", "₹3.45 lakh", "Rs.3.45L", "INR 345000"],
    "d3": ["Rs.2,46,500", "₹2.465 lakh", "Rs.2.465L"], "d5": ["Rs.94,200", "₹0.942 lakh", "Rs.0.942L"], "dtot": ["Rs.3,40,700", "₹3.407 lakh"],
    "date1": ["2026-08-13", "13 Aug 2026", "Aug 13, 2026", "13/08/2026"], "date5": ["2026-08-17", "17 August 2026", "Aug 17, 2026", "17/08/2026"],
    "inc": ["Rs.28K per month", "₹28,000 per month", "Rs.28,000/month"], "pct": ["98.8", "98.75", "98.7"],
    # the notations the validator was extended to read, stated truthfully
    "ctot2": ["345000 rupees", "3,45,000 INR", "three lakh forty-five thousand rupees", "Rs 3.45 lakh"],
    "d3b": ["246500 rupees", "2,46,500 INR", "two lakh forty-six thousand five hundred rupees"],
    "date1b": ["13.08.2026", "2026/08/13", "13th August", "August 13", "the thirteenth of August", "20260813", "13th of August"],
    "date5b": ["17.08.2026", "2026/08/17", "17th August", "August 17", "the seventeenth of August", "20260817"],
    "earn": ["earns Rs.28,000 per month", "has a salary of ₹28,000", "earns about Rs.28K a month"],
    "open": ["2025", "June 2025", "May 2025"],
    "tenure": ["14 months", "fourteen months"],
}
_TEMPLATES = [
    "Credits of {c1}, {c2} and {c4} (total {ctot}) were received from unidentified UPI handles A, B and D.",
    "Debits of {d3} and {d5} went to UPI handle C, which is I4C-flagged.",
    "The first credit arrived on {date1} and the last debit on {date5}.",
    "The customer is a data entry operator with a declared income of {inc}.",
    "{pct}% of the credits left the account.",
    "The credits were about 12 times the declared income.",
    "The account is 14 months old.",
    "Reference transactions T01-1, T01-2 and T01-4 (credits) and T01-3 and T01-5 (debits).",
    "Total credits were {ctot} and total debits were {dtot}.",
    "All of the activity was by UPI.",
    "Total credits came to {ctot2}.",
    "A debit of {d3b} went to the flagged handle.",
    "The first credit was on {date1b} and the last debit was on {date5b}.",
    "The customer {earn}.",
    "The account was opened in {open}.",
    "The customer has been banking with us for {tenure}.",
]


def faithful_narratives(n: int = FAITHFUL_COUNT) -> list[tuple[str, str]]:
    rng = random.Random(SEED)
    out = list(BASES)
    i = 0
    while len(out) < len(BASES) + n:
        picks = rng.sample(_TEMPLATES, k=rng.choice((2, 3, 4)))
        text = " ".join(t.format(**{k: rng.choice(v) for k, v in _TRUE.items()}) for t in picks)
        i += 1
        out.append((f"F{i:02d}", text))
    return out


# ── fabrications ─────────────────────────────────────────────────────────────
# (id, claim class, sentence appended to a base, or (target, replacement) substituted in it)

FABRICATIONS: list[tuple[str, str, object]] = [
    # amount (appended)
    ("A01", "amount", "The customer also received Rs.7,85,000 from an unrelated party."),
    ("A02", "amount", "A further credit of ₹4.2 lakh was noted."),
    ("A03", "amount", "The account also saw a transfer of INR 12,34,567."),
    ("A04", "amount", "A single deposit of ₹9.8 lakh preceded these credits."),
    ("A05", "amount", "The customer separately moved Rs.1.75 crore."),
    ("A06", "amount", "A payment of Rs. 62,500 was made to a third party."),
    ("A07", "amount", "A credit of ₹3,46,000 was also received."),
    ("A08", "amount", "The customer received 25 lakh in total."),
    ("A09", "amount", "A debit of Rs.5.5L followed."),
    ("A10", "amount", "The customer paid Rs.45,000 in fees."),
    ("A11", "amount", "Total outflows were Rs.4,10,000."),
    ("A12", "amount", "The credits total Rs.3,95,000."),
    # amount (a true figure replaced by a wrong one)
    ("S01", "amount", ("Rs.1.1L", "Rs.1.7L")), ("S02", "amount", ("Rs.1.4L", "Rs.1.9L")), ("S03", "amount", ("Rs.0.95L", "Rs.0.85L")),
    ("S04", "amount", ("Rs.3.45L", "Rs.3.95L")), ("S05", "amount", ("Rs.2.465L", "Rs.2.9L")), ("S06", "amount", ("Rs.0.942L", "Rs.1.2L")),
    # date
    ("D01", "date", "On 2026-08-27 the customer made a further transfer."),
    ("D02", "date", "The account activity continued until 5 September 2026."),
    ("D03", "date", "A transfer on 27/08/2026 was also noted."),
    ("D04", "date", "On Aug 3, 2026 the customer opened the account."),
    ("D05", "date", "On 2026-09-35 a final credit arrived."),
    ("D06", "date", "The pattern began on 2026-01-15."),
    ("D07", "date", "A related transfer occurred on 14 February 2026."),
    ("D08", "date", "On 2026-12-01 the funds were moved again."),
    ("D09", "date", "On 31/12/2025 the customer was onboarded."),
    ("D10", "date", "On 2026-08-20 the funds were moved."),
    # channel
    ("C01", "channel", "The customer also sent funds by SWIFT."), ("C02", "channel", "A NEFT transfer followed."),
    ("C03", "channel", "Funds were moved via RTGS."), ("C04", "channel", "An IMPS credit was also received."),
    ("C05", "channel", "The customer made cash deposits at a branch."), ("C06", "channel", "ATM withdrawals followed."),
    ("C07", "channel", "A cheque was deposited."),
    # geography
    ("G01", "geography", "The funds were routed to Dubai."), ("G02", "geography", "A counterparty in Singapore was involved."),
    ("G03", "geography", "Money was sent to Hong Kong."), ("G04", "geography", "The beneficiary is based in Cyprus."),
    ("G05", "geography", "Transfers went to Pakistan."), ("G06", "geography", "A London-based entity was involved."),
    ("G07", "geography", "The funds passed through Mauritius."), ("G08", "geography", "A Cayman account was used."),
    ("G09", "geography", "A Panama company received funds."), ("G10", "geography", "The money reached Nepal."),
    # transaction id
    ("T01", "txn_id", "See transaction TXN-9001."), ("T02", "txn_id", "Reference T01-9 shows a further debit."),
    ("T03", "txn_id", "The pattern includes ALERT-01-T9."), ("T04", "txn_id", "T02-3 is also relevant."),
    ("T05", "txn_id", "TXN-0042 was reviewed."), ("T06", "txn_id", "See T01A-77."),
    # identifier
    ("I01", "identifier", "A further handle ravi.k@okaxis was used."), ("I02", "identifier", "Funds were credited to account 123456789012."),
    ("I03", "identifier", "The IFSC HDFC0001234 was used."), ("I04", "identifier", "PAN ABCDE1234F is linked."),
    ("I05", "identifier", "The phone number 9876543210 was provided."), ("I06", "identifier", "The email a.b@example.com was registered."),
    ("I07", "identifier", "Another handle priya99@ybl received funds."),
    # named entity
    ("E01", "entity", "Funds went to Sunrise Traders Pvt Ltd."), ("E02", "entity", "A payment to Global Exports Ltd was made."),
    ("E03", "entity", "Hindustan Charitable Trust received funds."), ("E04", "entity", "Apex Bank was involved."),
    ("E05", "entity", "Metro Infrastructure LLP is linked."), ("E06", "entity", "Delta Engineering Limited was the payer."),
    ("E07", "entity", "Shree Constructions Pvt Ltd received a transfer."), ("E08", "entity", "National Relief Foundation was a payee."),
    # declared income
    ("N01", "profile_income", "The customer's declared income is Rs.45K per month."),
    ("N02", "profile_income", "The stated monthly income of ₹1.2 lakh does not explain the credits."),
    ("N03", "profile_income", "The reported annual income of Rs. 12 lakh is inconsistent with the activity."),
    ("N04", "profile_income", "The declared income of INR 85,000 is far lower than the credits."),
    ("N05", "profile_income", "The monthly income of Rs.60K was verified."),
    ("N06", "profile_income", "The stated income: Rs.2 lakh was noted."),
    # profile facts
    ("P01", "profile_fact", "The account had been dormant for 6 months."), ("P02", "profile_fact", "The customer is a politically exposed person."),
    ("P03", "profile_fact", "The account is 5 years old."), ("P04", "profile_fact", "The customer's passport was used to open the account."),
    ("P05", "profile_fact", "The nominee is the customer's brother."), ("P06", "profile_fact", "The account is held with a joint holder."),
    ("P07", "profile_fact", "A guarantor was named."), ("P08", "profile_fact", "The aadhaar was re-verified."),
]

# SOFT claims (need acknowledgement, never a hard block): third-party characterisations and unreproducible ratios.
SOFT_FABRICATIONS: list[tuple[str, str, str]] = [
    ("H01", "third_party_characterisation", "The counterparty has known links to hawala networks."),
    ("H02", "third_party_characterisation", "The handles are linked to terror financing."),
    ("H03", "third_party_characterisation", "The recipient is FATF-listed."),
    ("H04", "third_party_characterisation", "The receiver is a shell company."),
    ("H05", "third_party_characterisation", "The counterparty is sanctioned."),
    ("H06", "third_party_characterisation", "He has known ties to organised crime."),
    ("H07", "third_party_characterisation", "The handle is blacklisted."),
    ("H08", "third_party_characterisation", "The counterparty is notorious in the area."),
    ("H09", "percentage", "99.9% of the credits were withdrawn."),
    ("H10", "multiple", "The credits were 30 times the declared income."),
    ("H11", "percentage", "40% of the funds were sent abroad."),
]

# Every fact is in the record; the claim is false. Expected to pass the validator (a stated limit).
MIS_ATTRIBUTIONS: list[tuple[str, str, str]] = [
    ("M01", "wrong direction", "The customer sent Rs.1.1L to UPI handle A."),
    ("M02", "wrong party for an amount", "Rs.2.465L was received from UPI handle A."),
    ("M03", "wrong date for a transaction", "On 2026-08-13 debits of Rs.2.465L went to UPI handle C."),
    ("M04", "wrong party carries the flag", "UPI handle D, which is I4C-flagged, received the money."),
    ("M05", "wrong source for all credits", "All three credits came from UPI handle C."),
    ("M06", "total mislabelled", "The debits totalled Rs.3.45L."),
    ("M07", "wrong date for an amount", "The credit of Rs.0.95L was received on 2026-08-13."),
    ("M08", "wrong party carries the flag", "UPI handle B, an I4C-flagged account, sent Rs.1.4L."),
    ("M09", "ratio attached to the wrong side", "98.8% of the debits were later returned."),
]


# HELD-OUT mis-attributions: written BEFORE any attribution logic existed, in surface forms different from M01-M09 (which the logic was developed against).
# Every fact is in the record; the claim attaches it to the wrong party, the wrong direction, the wrong date, the wrong side, or the wrong flag.
MIS_ATTRIBUTIONS_HELD_OUT: list[tuple[str, str, str]] = [
    ("N01", "wrong direction", "UPI handle B transferred Rs.1.4L out of the account."),
    ("N02", "wrong direction", "Rs.95,000 was paid to UPI handle D on 2026-08-16."),
    ("N03", "wrong direction", "Funds of Rs.2,46,500 were received from UPI handle C."),
    ("N04", "wrong party", "The first credit, Rs.1.1L, arrived from UPI handle B."),
    ("N05", "wrong date", "On 17 August 2026, UPI handle A sent Rs.1.1L."),
    ("N06", "wrong party", "A debit of Rs.94,200 went to UPI handle A."),
    ("N07", "wrong flag", "The I4C-flagged handle B received Rs.2.465L."),
    ("N08", "wrong date", "Rs.1.4L credited on 2026-08-16 came from UPI handle B."),
    ("N09", "total on the wrong side", "Total credits amounted to Rs.3.407L."),
    ("N10", "total on the wrong side", "Total debits came to ₹3.45 lakh."),
    ("N11", "wrong party for all debits", "All the debits went to UPI handle A."),
    ("N12", "wrong party for all credits", "Every credit was received from UPI handle C."),
    ("N13", "wrong flag", "UPI handle D, flagged by I4C, sent Rs.95,000."),
    ("N14", "ratio on the wrong side", "98.75% of the debits were received back."),
    ("N15", "wrong direction and party", "Rs.1.1L left the account to UPI handle C on 2026-08-13."),
]

# The same facts bound CORRECTLY, in the same surface forms. A check that flags these is wrong, not careful.
CORRECT_ATTRIBUTIONS: list[tuple[str, str]] = [
    ("P01", "UPI handle B sent Rs.1.4L into the account."),
    ("P02", "Rs.95,000 was received from UPI handle D on 2026-08-16."),
    ("P03", "Funds of Rs.2,46,500 were paid to UPI handle C."),
    ("P04", "The first credit, Rs.1.1L, arrived from UPI handle A."),
    ("P05", "On 13 August 2026, UPI handle A sent Rs.1.1L."),
    ("P06", "A debit of Rs.94,200 went to UPI handle C on 2026-08-17."),
    ("P07", "The I4C-flagged handle C received Rs.2.465L."),
    ("P08", "Rs.1.4L credited on 2026-08-14 came from UPI handle B."),
    ("P09", "Total credits amounted to Rs.3.45L."),
    ("P10", "Total debits came to ₹3.407 lakh."),
    ("P11", "All the debits went to UPI handle C."),
    ("P12", "Every credit was received from an unidentified UPI handle."),
    ("P13", "UPI handle C, flagged by I4C, received Rs.94,200."),
    ("P14", "98.75% of the credits left the account."),
    ("P15", "Rs.1.1L, from UPI handle A, was credited on 2026-08-13 and Rs.1.4L, from UPI handle B, on 2026-08-14."),
    ("P16", "Credits came from handles A, B and D; the debits went to handle C."),
    ("P17", "Rs.2.465L went to UPI handle C on 2026-08-15, and a further Rs.94,200 went to the same handle on 2026-08-17."),
    ("P18", "The credits (Rs.1.1L, Rs.1.4L and Rs.0.95L) were received from three different UPI handles."),
]

# Correct statements that FALSE-FLAGGED when first measured (found by set Q), kept as permanent regression cases. (alert, id, sentence)
REGRESSION_CORRECT: list[tuple[str, str, str]] = [
    ("ALERT-02", "G1", "ACCT-02-B received a cash deposit of Rs.1,42,500 on 2026-08-19."),
    ("ALERT-02", "G2", "ACCT-02-A received Rs.1,42,500 in cash on 2026-08-19."),
    ("ALERT-02", "G3", "All the credits were cash deposits into ACCT-02-A, ACCT-02-B and ACCT-02-C."),
]


# SET Q: written AFTER the attribution check existed and never tuned on. Natural phrasings across FOUR alerts (the check was developed on ALERT-01's "UPI handle A/B/C"
# parties; company names, family members and own accounts go through a path the development sets never exercised). It includes cases the check is NOT expected to
# catch (partial sums called totals, "recipient of", two parties in one sentence) and one correct statement suspected to false-flag (an own account "receiving" a
# deposit). Whatever it gets wrong stays wrong: this is the figure to quote.
# (alert, id, kind, sentence)
Q_MISATTRIBUTIONS: list[tuple[str, str, str, str]] = [
    ("ALERT-04", "Q01", "wrong direction", "Rs.11,00,000 was paid to ABC Infrastructure Ltd on 2026-07-15."),
    ("ALERT-04", "Q02", "wrong party", "DEF Engineering Pvt Ltd credited Rs.8,50,000 on 2026-06-15."),
    ("ALERT-04", "Q03", "wrong party", "GHI Constructions sent Rs.9,30,000 on 2026-08-15."),
    ("ALERT-04", "Q04", "wrong party for all credits", "All the credits came from ABC Infrastructure Ltd."),
    ("ALERT-04", "Q05", "wrong date", "JKL Roadways Pvt Ltd paid Rs.8,20,000 on 2026-08-15."),
    ("ALERT-04", "Q06", "partial sum called the total", "The credits totalled Rs.4,80,000 over two months."),
    ("ALERT-04", "Q07", "wrong direction", "Rs.6,20,000 left the account for DEF Engineering Pvt Ltd on 2026-06-20."),
    ("ALERT-04", "Q08", "wrong party", "Rs.4,80,000 was received from JKL Roadways Pvt Ltd."),
    ("ALERT-16", "Q09", "wrong direction", "Rs.3,00,000 was received from City General Hospital."),
    ("ALERT-16", "Q10", "wrong party", "Rs.1,50,000 came from his father."),
    ("ALERT-16", "Q11", "wrong direction", "Rs.75,000 was paid to Sister on 2026-09-11."),
    ("ALERT-16", "Q12", "wrong party", "Rs.1,20,000 arrived from the brother on 2026-09-10."),
    ("ALERT-02", "Q13", "wrong date", "Rs.4,20,000 was transferred by NEFT on 2026-08-19."),
    ("ALERT-02", "Q14", "wrong direction", "ACCT-02-B paid out Rs.1,42,500 by NEFT."),
    ("ALERT-01", "Q15", "ratio on the wrong side", "Of the credits received, 100% were forwarded to flagged handle C."),
    ("ALERT-01", "Q16", "wrong party", "UPI handle A deposited Rs.2,46,500 into the account."),
    ("ALERT-01", "Q17", "wrong date", "The final debit, Rs.94,200, went to UPI handle C on 2026-08-15."),
    ("ALERT-01", "Q18", "total on the wrong side", "Debits totalled Rs.3.45L over five days."),
    ("ALERT-01", "Q19", "wrong direction (cue not read)", "UPI handle B was the recipient of Rs.1.4L."),
    ("ALERT-01", "Q20", "two parties in one sentence", "Rs.1.4L went from UPI handle A to UPI handle C."),
]
R_CORRECT: list[tuple[str, str, str]] = [
    ("ALERT-04", "R01", "ABC Infrastructure Ltd paid Rs.11,00,000 on 2026-07-15."),
    ("ALERT-04", "R02", "Rs.6,20,000 was received from DEF Engineering Pvt Ltd on 2026-06-20."),
    ("ALERT-04", "R03", "The credits totalled Rs.48,00,000 across six NEFT transfers."),
    ("ALERT-04", "R04", "Rs.4,80,000 came from GHI Constructions on 20 July 2026."),
    ("ALERT-04", "R05", "DEF Engineering Pvt Ltd made two payments, Rs.6,20,000 on 2026-06-20 and Rs.9,30,000 on 2026-08-15."),
    ("ALERT-04", "R06", "ABC Infrastructure Ltd and DEF Engineering Pvt Ltd were the two largest sources."),
    ("ALERT-04", "R07", "All the credits arrived from four contractors."),
    ("ALERT-16", "R08", "Rs.3,00,000 was paid to City General Hospital on 2026-09-12."),
    ("ALERT-16", "R09", "Rs.1,50,000 came from his brother on 2026-09-09."),
    ("ALERT-16", "R10", "Rs.75,000 arrived from Sister on 2026-09-11."),
    ("ALERT-16", "R11", "The credits totalled Rs.3.45 lakh from three family members."),
    ("ALERT-02", "R12", "Rs.4,20,000 was transferred by NEFT on 2026-08-20."),
    ("ALERT-02", "R13", "ACCT-02-B received a cash deposit of Rs.1,42,500 on 2026-08-19."),
    ("ALERT-01", "R14", "UPI handle D was the source of Rs.95,000 on 2026-08-16."),
    ("ALERT-01", "R15", "UPI handle A paid Rs.1.1L into the account on 13 August 2026."),
    ("ALERT-01", "R16", "On 2026-08-15 the account paid Rs.2.465L to the I4C-flagged UPI handle C."),
    ("ALERT-01", "R17", "Debits totalled Rs.3.407L over five days."),
    ("ALERT-01", "R18", "98.75% of the credits were forwarded to flagged handle C."),
    ("ALERT-01", "R19", "The credits came to ₹3.45 lakh."),
    ("ALERT-01", "R20", "Rs.1.4L was sent by UPI handle B on 2026-08-14."),
]


def fabricated_narratives() -> list[dict]:
    """Every fabrication placed in two bases. Returns dicts: id, cls, expect ('hard'|'soft'), text, base."""
    out = []
    for i, (fid, cls, spec) in enumerate(FABRICATIONS):
        bases = [BASES[i % len(BASES)], BASES[(i + 3) % len(BASES)]]
        for bid, base in bases:
            if isinstance(spec, tuple):
                target, repl = spec
                if target not in base:                     # a substitution needs a base that contains the figure
                    base = BASES[0][1]
                    bid = BASES[0][0]
                text = base.replace(target, repl, 1)
            else:
                text = base + " " + spec
            out.append({"id": fid, "cls": cls, "expect": "hard", "text": text, "base": bid})
    for i, (fid, cls, sentence) in enumerate(SOFT_FABRICATIONS):
        for bid, base in (BASES[i % len(BASES)], BASES[(i + 2) % len(BASES)]):
            out.append({"id": fid, "cls": cls, "expect": "soft", "text": base + " " + sentence, "base": bid})
    seen, unique = set(), []
    for r in out:                                           # two bases can coincide for substitutions; keep distinct texts only
        if r["text"] not in seen:
            seen.add(r["text"])
            unique.append(r)
    return unique


# STRESS set: wrong facts phrased the way people and models write them in practice, chosen to probe notations the validator's patterns do
# not obviously cover (amounts in words, dates without a year, "wire transfer", cities, unlisted company suffixes). A competent validator
# should object to every one; the miss rate is the generalisation gap. Written before any validator change and recorded as the baseline.
# (id, claim class, sentence). SET 'S' is the baseline; SET 'S2' was written AFTER the fixes made for S and is the fairer generalisation number.
STRESS: list[tuple[str, str, str, str]] = [
    ("S", "X01", "amount", "The customer moved twenty-five lakh rupees."),
    ("S", "X02", "amount", "A credit of Rs 25,00,000/- was received."),
    ("S", "X03", "amount", "A transfer of 2.5 million rupees took place."),
    ("S", "X04", "amount", "She received five hundred thousand rupees."),
    ("S", "X05", "amount", "The sum of Rupees Seven Lakh Eighty Five Thousand was received."),
    ("S", "X06", "amount", "A deposit of ₹ 7,85,000.00 was made."),
    ("S", "X07", "amount", "The balance rose by Rs. 7.85 L."),
    ("S", "X08", "amount", "The customer got 785000 rupees."),
    ("S", "X09", "amount", "A payment of 7,85,000 INR followed."),
    ("S", "X10", "amount", "A credit of USD 9,500 was received."),
    ("S", "X11", "date", "On the twenty-seventh of August the customer made a transfer."),
    ("S", "X12", "date", "On 27th August a transfer was made."),
    ("S", "X13", "date", "The transfer was on 27.08.2026."),
    ("S", "X14", "date", "On 2026/08/27 the funds moved."),
    ("S", "X15", "date", "A transfer on August 27 happened."),
    ("S", "X16", "date", "The funds were withdrawn on 20260827."),
    ("S", "X17", "channel", "The customer used a wire transfer to send funds abroad."),
    ("S", "X18", "channel", "An international remittance followed."),
    ("S", "X19", "channel", "The customer paid by debit card."),
    ("S", "X20", "channel", "Funds were moved through internet banking."),
    ("S", "X21", "channel", "A demand draft was issued."),
    ("S", "X22", "channel", "Cash was handed over at the branch."),
    ("S", "X23", "geography", "Funds reached the Maldives."),
    ("S", "X24", "geography", "A company in the Bahamas received funds."),
    ("S", "X25", "geography", "The beneficiary lives in Jersey."),
    ("S", "X26", "geography", "The money was sent to Kathmandu."),
    ("S", "X27", "geography", "Funds went to Karachi."),
    ("S", "X28", "geography", "A recipient in Shenzhen was involved."),
    ("S", "X29", "entity", "Funds went to Acme Holdings."),
    ("S", "X30", "entity", "A payment to Rao & Sons was made."),
    ("S", "X31", "entity", "Sunrise Group received funds."),
    ("S", "X32", "entity", "ICICI received the funds."),
    ("S", "X33", "entity", "Kalyan Jewellers Inc was the payee."),
    ("S", "X34", "identifier", "Account number 1234 5678 9012 3456 was credited."),
    ("S", "X35", "identifier", "The customer's mobile +91 98765 43210 was provided."),
    ("S", "X36", "identifier", "A card ending 4321 was used."),
    ("S", "X37", "profile_income", "The customer earns about Rs.50,000 a month."),
    ("S", "X38", "profile_fact", "The customer has been banking with us for ten years."),
    ("S", "X39", "profile_fact", "The account was opened in 2019."),
    ("S", "X40", "profile_fact", "The customer is a retired teacher."),
    # ── S2: written AFTER the validator fixes made for S. New surface forms in the same classes. Not iterated on: whatever it misses stays missed. ──
    ("S2", "Y01", "amount", "She was paid eight lakh fifty thousand rupees."),
    ("S2", "Y02", "amount", "The customer transferred Rs 1.2 Cr."),
    ("S2", "Y03", "amount", "A sum of four crore rupees moved."),
    ("S2", "Y04", "amount", "Ten thousand rupees was debited."),
    ("S2", "Y05", "amount", "The payer sent ₹ 15,000/-"),
    ("S2", "Y06", "amount", "A payment of rupees 6,50,000 followed."),
    ("S2", "Y07", "amount", "Funds worth 12 lakh were moved."),
    ("S2", "Y08", "amount", "A one-time credit of Rs 8.4 lakhs arrived."),
    ("S2", "Y09", "amount", "He remitted USD 12,000."),
    ("S2", "Y10", "amount", "A cheque for fifty-five thousand rupees was presented."),
    ("S2", "Y11", "date", "On 3rd of September the account was used."),
    ("S2", "Y12", "date", "The transfer posted on Aug. 29."),
    ("S2", "Y13", "date", "On 12-09-2026 funds were sent."),
    ("S2", "Y14", "date", "On 2026-9-12 a credit arrived."),
    ("S2", "Y15", "date", "On 12 Sept 2026 the balance was cleared."),
    ("S2", "Y16", "date", "On the 1st of September a credit arrived."),
    ("S2", "Y17", "date", "On September 5th, 2026 a transfer occurred."),
    ("S2", "Y18", "date", "On the thirtieth of August the account was emptied."),
    ("S2", "Y19", "channel", "A SWIFT MT103 message was sent."),
    ("S2", "Y20", "channel", "The funds were sent through a mobile wallet."),
    ("S2", "Y21", "channel", "Payments were made by credit card."),
    ("S2", "Y22", "channel", "An NEFT/RTGS transfer followed."),
    ("S2", "Y23", "channel", "Funds were wired overseas."),
    ("S2", "Y24", "channel", "The customer withdrew cash from the branch counter."),
    ("S2", "Y25", "geography", "The recipient is in Tanzania."),
    ("S2", "Y26", "geography", "A counterparty in Lithuania was involved."),
    ("S2", "Y27", "geography", "Payments went to Vanuatu."),
    ("S2", "Y28", "geography", "Funds were sent to Oslo."),
    ("S2", "Y29", "geography", "A Dubai-based exchange house received funds."),
    ("S2", "Y30", "entity", "Payments went to Greenfield Realty LLP."),
    ("S2", "Y31", "entity", "The payee was Omkar Textiles."),
    ("S2", "Y32", "entity", "The beneficiary is Zenith Securities."),
    ("S2", "Y33", "entity", "Funds went to Patel Brothers."),
    ("S2", "Y34", "entity", "The recipient, M/s Joshi & Associates, was paid."),
    ("S2", "Y35", "identifier", "UPI ID ravi123@paytm was used."),
    ("S2", "Y36", "identifier", "Mobile 98765-43210 was linked."),
    ("S2", "Y37", "identifier", "Cheque number 004512 was presented."),
    ("S2", "Y38", "profile_fact", "The customer has been a client for five years."),
    ("S2", "Y39", "profile_fact", "The account was opened in March 2021."),
    ("S2", "Y40", "profile_fact", "The customer is a serving government official."),
    ("S2", "Y41", "profile_income", "Their monthly salary is ₹95,000."),
    ("S2", "Y42", "profile_fact", "The customer is 29 years old."),
    # ── S3: written BEFORE the second round of fixes (the four S2 pattern gaps), in categories spanning the whole validator, with ~4 of 38 in the
    #    patched shapes. Measured before and after the patch; the after-figure is the estimate to quote. Not iterated on. ──
    ("S3", "Z01", "amount", "The account received rupees 2,40,000 from an unknown sender."),
    ("S3", "Z02", "amount", "A credit of Rs. 9.25 L appeared."),
    ("S3", "Z03", "amount", "He deposited INR 3,00,000/- in one go."),
    ("S3", "Z04", "amount", "The total came to nearly six lakh rupees."),
    ("S3", "Z05", "amount", "Funds of one crore were moved."),
    ("S3", "Z06", "amount", "A transfer of ₹87,500 was flagged."),
    ("S3", "Z07", "amount", "The customer received EUR 4,000 from abroad."),
    ("S3", "Z08", "amount", "She paid fifteen thousand rupees in cash."),
    ("S3", "Z09", "date", "The credit was posted on 5/9/2026."),
    ("S3", "Z10", "date", "On 12 Sep. 2026, funds were moved."),
    ("S3", "Z11", "date", "On the 3rd day of September the account was used."),
    ("S3", "Z12", "date", "On 2026-10-1 the account was closed."),
    ("S3", "Z13", "date", "The payment went out on Sept 9."),
    ("S3", "Z14", "date", "On Monday 7 September the funds left."),
    ("S3", "Z15", "channel", "Money was wired to a foreign account."),
    ("S3", "Z16", "channel", "The customer used a mobile banking app to push funds."),
    ("S3", "Z17", "channel", "A credit card repayment was made."),
    ("S3", "Z18", "channel", "The funds arrived through a foreign remittance."),
    ("S3", "Z19", "channel", "Cash was withdrawn at the branch."),
    ("S3", "Z20", "channel", "A pay order for the amount was issued."),
    ("S3", "Z21", "geography", "Funds were transferred to Hungary."),
    ("S3", "Z22", "geography", "The beneficiary bank is located in Sweden."),
    ("S3", "Z23", "geography", "A payment reached Casablanca."),
    ("S3", "Z24", "geography", "The counterparty operates from Abu Dhabi."),
    ("S3", "Z25", "geography", "Transfers went to Panama City."),
    ("S3", "Z26", "geography", "The recipient lives in Chittagong."),
    ("S3", "Z27", "entity", "Money was sent to Royal Orchid Hotels Pvt Ltd."),
    ("S3", "Z28", "entity", "Bharat Mercantile Co received funds."),
    ("S3", "Z29", "entity", "Funds went to Nair & Nair."),
    ("S3", "Z30", "entity", "The beneficiary was Union Exchange Corporation."),
    ("S3", "Z31", "entity", "Payment was made to the State Bank."),
    ("S3", "Z32", "entity", "A wallet company, PhonePe, was involved."),
    ("S3", "Z33", "identifier", "The linked email is rohit.sharma@gmail.com."),
    ("S3", "Z34", "identifier", "The device IMEI 356938035643809 was recorded."),
    ("S3", "Z35", "profile_fact", "The customer has been with the bank for twelve years."),
    ("S3", "Z36", "profile_income", "Her declared income is Rs.1.5 lakh monthly."),
    ("S3", "Z37", "profile_fact", "The account was opened in the year 2018."),
    ("S3", "Z38", "profile_fact", "He is a government servant."),
]


# ── independent view of what the record can support (for collision analysis) ─

def derivable_amounts() -> list[float]:
    credits = [t["amount_inr"] for t in RECORD["transactions"] if t["type"] == "CREDIT"]
    debits = [t["amount_inr"] for t in RECORD["transactions"] if t["type"] == "DEBIT"]
    vals = [t["amount_inr"] for t in RECORD["transactions"]] + [sum(credits), sum(debits)]
    for group in (credits, debits):
        for r in range(2, len(group) + 1):
            vals += [sum(c) for c in itertools.combinations(group, r)]
    vals += [a["value"] for a in extract_amounts(RECORD["alert_narrative"])]
    p = parse_profile(RECORD["profile_text"])
    vals += [v for v in (p["monthly_income"], p["annual_income"]) if v]
    return sorted({float(v) for v in vals if v > 0})


def is_collision(narrative_amount_text: str) -> bool:
    """True when a stated amount is within its own display tolerance of some figure the record supports (so passing is not a miss)."""
    allowed = derivable_amounts()
    return any(any(abs(a["value"] - v) <= max(a["tol"], 0.5) for v in allowed) for a in extract_amounts(narrative_amount_text))


# ── statistics ───────────────────────────────────────────────────────────────

def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4))


def _rate(k: int, n: int) -> dict:
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "rate_pct": round(100 * k / n, 1) if n else None, "wilson95_pct": [round(100 * lo, 1), round(100 * hi, 1)]}


# ── the run ──────────────────────────────────────────────────────────────────

def run() -> dict:
    faithful = faithful_narratives()
    fp_hard, fp_soft = [], []
    for fid, text in faithful:
        r = validate(text)
        if not r["passed"]:
            fp_hard.append({"id": fid, "flagged": r["unsupported_claims_by_type"], "text": text})
        if r["unverified_assertions"]:
            fp_soft.append({"id": fid, "flagged": [(u["type"], u["text"]) for u in r["unverified_assertions"]], "text": text})

    cross_fp, cross = [], cross_record_faithful()
    for aid, nid, text in cross:
        r = validate(text, build_record(aid))
        if not r["passed"]:
            cross_fp.append({"id": nid, "alert": aid, "flagged": r["unsupported_claims_by_type"], "text": text})

    fab = fabricated_narratives()
    hard = [f for f in fab if f["expect"] == "hard"]
    soft = [f for f in fab if f["expect"] == "soft"]
    by_class: dict[str, dict] = {}
    missed: list[dict] = []
    for f in hard:
        r = validate(f["text"])
        flagged = set(r["unsupported_claims_by_type"])
        caught_any = not r["passed"]
        caught_class = f["cls"] in flagged
        c = by_class.setdefault(f["cls"], {"n": 0, "any": 0, "cls": 0})
        c["n"] += 1
        c["any"] += caught_any
        c["cls"] += caught_class
        if not caught_any:
            missed.append({"id": f["id"], "cls": f["cls"], "text": f["text"][-140:]})
    soft_by_class: dict[str, dict] = {}
    soft_missed = []
    for f in soft:
        r = validate(f["text"])
        types = {u["type"] for u in r["unverified_assertions"]}
        c = soft_by_class.setdefault(f["cls"], {"n": 0, "flagged": 0})
        c["n"] += 1
        c["flagged"] += f["cls"] in types
        if f["cls"] not in types:
            soft_missed.append({"id": f["id"], "cls": f["cls"], "text": f["text"][-120:]})

    stress_by_set: dict[str, dict] = {}
    stress_missed = []
    for sset, sid, cls, sentence in STRESS:
        text = BASES[1][1] + " " + sentence
        r = validate(text)
        caught = (not r["passed"]) or any(u["type"] in ("occupation", "third_party_characterisation") for u in r["unverified_assertions"])
        c = stress_by_set.setdefault(sset, {"n": 0, "caught": 0, "by_class": {}})
        c["n"] += 1
        c["caught"] += caught
        bc = c["by_class"].setdefault(cls, {"n": 0, "caught": 0})
        bc["n"] += 1
        bc["caught"] += caught
        if not caught:
            stress_missed.append({"set": sset, "id": sid, "cls": cls, "sentence": sentence})

    def _attribution(items):
        out_ = []
        for mid, kind, sentence in items:
            r = validate(BASES[1][1] + " " + sentence)
            out_.append({"id": mid, "kind": kind, "sentence": sentence, "detected": not r["passed"] or bool(r["unverified_assertions"]),
                         "flagged": [u["text"] for u in r["unverified_assertions"] if u["type"] == "attribution_mismatch"][:3]})
        return out_

    attributions = _attribution(MIS_ATTRIBUTIONS)
    held_out = _attribution(MIS_ATTRIBUTIONS_HELD_OUT)
    correct = []
    for pid, sentence in CORRECT_ATTRIBUTIONS:
        r = validate(BASES[1][1] + " " + sentence)
        correct.append({"id": pid, "sentence": sentence, "hard": r["unsupported_claims_by_type"], "soft": [(u["type"], u["text"]) for u in r["unverified_assertions"]]})
    correct_flagged = [c for c in correct if c["hard"] or c["soft"]]

    q_detail = []
    for aid, qid, kind, sentence in Q_MISATTRIBUTIONS:
        r = validate(sentence, build_record(aid))
        hit = [u["why"] for u in r["unverified_assertions"] if u["type"] == "attribution_mismatch"]
        q_detail.append({"id": qid, "alert": aid, "kind": kind, "sentence": sentence, "detected": bool(hit), "why": hit[:1], "other_flags": r["unsupported_claims_by_type"]})
    r_detail = []
    for aid, rid, sentence in R_CORRECT:
        r = validate(sentence, build_record(aid))
        r_detail.append({"id": rid, "alert": aid, "sentence": sentence, "attribution": [u["why"] for u in r["unverified_assertions"] if u["type"] == "attribution_mismatch"],
                         "other_soft": [(u["type"], u["text"]) for u in r["unverified_assertions"] if u["type"] != "attribution_mismatch"], "hard": r["unsupported_claims_by_type"]})
    r_flagged = [x for x in r_detail if x["attribution"] or x["hard"] or x["other_soft"]]

    return {
        "record": {"alert": ALERT_ID, "transactions": len(RECORD["transactions"]), "derivable_amounts": len(derivable_amounts())},
        "faithful": {"narratives": len(faithful), "hard_false_positives": _rate(len(fp_hard), len(faithful)), "soft_flags": _rate(len(fp_soft), len(faithful)),
                     "hard_fp_cases": fp_hard, "soft_flag_cases": fp_soft,
                     "other_alerts": {"alerts": EXPLICIT_ALERTS, "narratives": len(cross), "hard_false_positives": _rate(len(cross_fp), len(cross)), "hard_fp_cases": cross_fp}},
        "fabricated_hard": {"narratives": len(hard), "caught_any": _rate(sum(c["any"] for c in by_class.values()), len(hard)),
                            "caught_as_right_class": _rate(sum(c["cls"] for c in by_class.values()), len(hard)),
                            "by_class": {k: {"n": v["n"], "caught_any": _rate(v["any"], v["n"]), "caught_as_right_class": _rate(v["cls"], v["n"])} for k, v in sorted(by_class.items())},
                            "missed": missed},
        "fabricated_soft": {"narratives": len(soft), "flagged_for_acknowledgement": _rate(sum(c["flagged"] for c in soft_by_class.values()), len(soft)),
                            "by_class": {k: _rate(v["flagged"], v["n"]) for k, v in sorted(soft_by_class.items())}, "missed": soft_missed},
        "stress": {sset: {"narratives": c["n"], "caught": _rate(c["caught"], c["n"]),
                          "by_class": {k: _rate(v["caught"], v["n"]) for k, v in sorted(c["by_class"].items())}} for sset, c in sorted(stress_by_set.items())},
        "stress_missed": stress_missed,
        "mis_attribution": {"cases": len(attributions), "detected": sum(a["detected"] for a in attributions), "cases_detail": attributions},
        "mis_attribution_held_out": {"cases": len(held_out), "detected": sum(a["detected"] for a in held_out), "cases_detail": held_out,
                                     "rate": _rate(sum(a["detected"] for a in held_out), len(held_out))},
        "correct_attribution": {"statements": len(correct), "wrongly_flagged": _rate(len(correct_flagged), len(correct)), "flagged_cases": correct_flagged},
        "attribution_q": {"misattributions": len(q_detail), "detected": _rate(sum(x["detected"] for x in q_detail), len(q_detail)), "cases_detail": q_detail,
                          "correct_statements": len(r_detail), "wrongly_flagged": _rate(len(r_flagged), len(r_detail)), "flagged_cases": r_flagged},
        "acceptance_bands": precision_table(),
    }


# ── amount precision: which displayed figures does the validator accept? ─────

def precision_table() -> dict:
    """For each notation, every figure that could be displayed between Rs.10,000 and Rs.10,00,000, and how many the validator accepts.
    A figure is accepted when it lies within half a displayed unit of something the record supports; coarser notation, wider band."""
    rows = {}
    allowed = derivable_amounts()
    notations = {
        "whole lakh (Rs.4 lakh)": [(f"Rs.{n} lakh", n * 1e5) for n in range(1, 11)],
        "one decimal lakh (Rs.4.3 lakh)": [(f"Rs.{n / 10:.1f} lakh", n * 1e4) for n in range(1, 101)],
        "two decimals lakh (Rs.4.35 lakh)": [(f"Rs.{n / 100:.2f} lakh", n * 1e3) for n in range(10, 1001, 5)],
        "exact rupees (Rs.4,35,000)": [(f"Rs.{v:,.0f}", v) for v in range(10_000, 1_000_001, 2_500)],
    }
    for label, items in notations.items():
        accepted = []
        for text, value in items:
            r = validate(f"The customer received {text}.")
            if "amount" not in r["unsupported_claims_by_type"]:
                accepted.append(text)
        rows[label] = {"displayed_figures_tested": len(items), "accepted": len(accepted),
                       "accepted_share_pct": round(100 * len(accepted) / len(items), 1), "accepted_examples": accepted[:6]}
    pct_accepted = [n for n in range(1, 100) if not any(u["type"] == "percentage" for u in validate(f"{n}% of the credits left the account.")["unverified_assertions"])]
    return {"derivable_figures_in_the_record": len(allowed), "by_notation": rows,
            "percentages": {"whole percentages_tested": 99, "accepted_without_a_flag": len(pct_accepted), "accepted_share_pct": round(100 * len(pct_accepted) / 99, 1),
                            "accepted": pct_accepted,
                            "note": "a percentage passes when within 0.6 points of any ratio derivable from the transactions; the check is soft (UNVERIFIED), not a block"}}


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=1, ensure_ascii=False)[:6000])
