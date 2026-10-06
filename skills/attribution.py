"""
Attribution check: does a narrative attach each verified fact to the RIGHT party, direction, date, side and flag?

skills/grounding.py confirms that a figure, a date or a party EXISTS in the case record. It cannot tell that "Rs.2.465L was received from UPI handle A" is false
when Rs.2.465L is a real debit and handle A is a real sender: every fact is in the record, and the sentence is still wrong. This module checks that binding.

Deliberately conservative. A finding is raised only when a sentence makes an UNAMBIGUOUS claim and the record contradicts it:

  party        one amount that is a single transaction + one named party: the party must be that transaction's counterparty
  direction    ... + a clear cue (received from / paid to / sent / went to ...): the transaction must be a credit / a debit accordingly
  date         one amount + one date: the transaction must be on that date
  side         "the debits totalled X" / "total credits ... X": X must be that side's total, not the other side's (or a partial sum)
  ratio        "N% of the credits/debits": N must be a ratio over THAT side
  quantifier   "all / every / each credit(s)/debit(s) ... from/to P": every transaction of that side must involve P
  flag         "P, which is I4C-flagged" / "the flagged handle P": the record must mark P as flagged

When a sentence is ambiguous (several parties and several amounts, a negation, a hypothetical, an amount that is not a single transaction) it is SKIPPED, not
guessed at. Findings are SOFT (labelled UNVERIFIED, acknowledged by the officer before filing): the extraction is heuristic, and a false hard block on a true
filing cannot be overridden. What it cannot see (causal claims, anything outside these patterns) stays in grounding.NOT_VERIFIED. Measured, with its false-flag
rate on correctly-bound statements, in tests/fabrication_benchmark.py and evidence/fabrication-benchmark/.

Pure: no model, no database, no clock.
"""

from __future__ import annotations

import itertools
import re
from collections import defaultdict

TYPE = "attribution_mismatch"
_PLACEHOLDER = "§p§"

_SKIP = re.compile(r"\b(?:not|never|no|without|neither|nor|if|whether|unless|would|could|might|may|should|n't|cannot|can't|isn't|wasn't|didn't)\b", re.I)
_ABBREV = {"rs", "inr", "pvt", "ltd", "inc", "co", "corp", "no", "dr", "mr", "mrs", "ms", "st", "approx", "vs", "etc"}

# ── parties ──────────────────────────────────────────────────────────────────
_HANDLE_LIST = re.compile(r"\b(?:UPI\s+)?(?:unknown\s+|unidentified\s+)?handles?\s+([A-Z])\b((?:\s*(?:,|and|&|or)\s*[A-Z]\b)*)")
_GENERIC_PARTY = re.compile(r"^(multiple counterparties|various|several)\b", re.I)          # a row that stands for many parties names none of them
_NAMELESS = {"individual", "sender", "party", "counterparty", "person", "payer", "payee", "entity"}   # "Unknown individual" identifies nobody
_ALIAS_STOP = {"family", "bank", "account", "accounts", "customer", "other", "same", "single", "current"}


def _core(counterparty: str) -> str:
    c = re.sub(r"\([^)]*\)", " ", counterparty or "")
    c = re.sub(r"^\s*(?:unknown|unidentified)\s+", "", c, flags=re.I)
    return " ".join(c.split()).strip(" -")


def _letters(text: str) -> list[str]:
    out = []
    for m in _HANDLE_LIST.finditer(text):
        out.append(m.group(1))
        out += re.findall(r"[A-Z]", m.group(2))
    return out


class Parties:
    """The counterparties of a case record, and how a narrative may refer to them."""

    def __init__(self, transactions: list[dict]):
        self.keys: dict[str, str] = {}              # key -> display name from the record
        self.letter: dict[str, str] = {}            # "A" -> key (UPI handle A)
        self.aliases: list[tuple[re.Pattern, str]] = []
        self.flagged: dict[str, bool] = defaultdict(bool)
        # A counterparty that is the customer's OWN account, or a deposit row, has no reliable direction: "ACCT-02-B received a cash deposit" is the natural way
        # to say that the record's credit from "ACCT-02-B cash deposits" happened. The direction check is skipped for these; party, date and side still apply.
        self.own: set[str] = set()
        for t in transactions:
            raw = str(t.get("counterparty") or "")
            if not raw or _GENERIC_PARTY.match(raw.strip()):
                continue
            core = _core(raw)
            key = core.lower()
            if not key or key in _NAMELESS:
                continue
            self.keys.setdefault(key, core)
            if re.search(r"\bacct\b|\bacct-|\bdeposits?\b|\bown account\b|\bself\b", core, re.I):
                self.own.add(key)
            self.flagged[key] = self.flagged[key] or bool(t.get("is_flagged")) or "flag" in raw.lower()
            m = re.search(r"\bhandle\s+([A-Z])\b", core)
            if m:
                self.letter.setdefault(m.group(1), key)
            else:
                for alias in {core, re.split(r"\s+(?:cash|deposits?)\b", core, flags=re.I)[0].strip()}:
                    if len(alias) >= 5 and alias.lower() not in _ALIAS_STOP:
                        self.aliases.append((re.compile(r"(?<![A-Za-z0-9])" + re.escape(alias) + r"(?![A-Za-z0-9])", re.I), key))

    def mentions(self, sentence: str) -> tuple[set[str], str]:
        """({party keys named in the sentence}, the sentence with each mention replaced by a placeholder)."""
        found: set[str] = set()
        spans: list[tuple[int, int]] = []
        for m in _HANDLE_LIST.finditer(sentence):
            letters = [m.group(1)] + re.findall(r"[A-Z]", m.group(2))
            keys = [self.letter[x] for x in letters if x in self.letter]
            if keys:
                found.update(keys)
                spans.append(m.span())
        for pat, key in self.aliases:
            for m in pat.finditer(sentence):
                found.add(key)
                spans.append(m.span())
        marked = sentence
        for a, b in sorted(spans, reverse=True):
            marked = marked[:a] + f" {_PLACEHOLDER} " + marked[b:]
        return found, marked

    def name(self, key: str) -> str:
        return self.keys.get(key, key)


# ── sentences ────────────────────────────────────────────────────────────────
def sentences(text: str) -> list[str]:
    parts: list[str] = []
    buf = ""
    tokens = re.split(r"(?<=[.;!?])\s+", text or "")
    for tok in tokens:
        buf = (buf + " " + tok).strip() if buf else tok
        last = re.findall(r"([A-Za-z]+)\.$", buf)
        if buf.endswith(".") and last and last[-1].lower() in _ABBREV:
            continue                                   # "Rs." / "Pvt." / "Ltd." end an abbreviation, not a sentence
        parts.append(buf)
        buf = ""
    if buf:
        parts.append(buf)
    return [p.strip(" ;") for p in parts if p.strip(" ;")]


# ── direction ────────────────────────────────────────────────────────────────
_OUT_OF = re.compile(r"\bout of (?:the |this )?account\b|\bfrom the account\b|\bleft the account\b", re.I)
_SUBJ_SENT = re.compile(_PLACEHOLDER + r"[^.;]{0,60}?\b(?:sent|paid|transferred|remitted|wired|credited|deposited|routed)\b", re.I)
_SUBJ_RECEIVED = re.compile(_PLACEHOLDER + r"[^.;]{0,60}?\breceived\b", re.I)
_FROM_P = re.compile(r"\b(?:received|came|come|comes|arrived|arriving|credited|deposited|sent|transferred|originated|originating|inflows?|inbound)\b[^.;]{0,80}?\bfrom\s+" + _PLACEHOLDER, re.I)
_TO_P = re.compile(r"\b(?:paid|sent|transferred|remitted|wired|went|go|goes|debited|moved|left|withdrawn|withdrew|routed|credited|passed|flowed|outbound)\b[^.;]{0,80}?\b(?:to|towards)\s+" + _PLACEHOLDER, re.I)


def _direction(marked: str) -> str | None:
    """'IN' (money into the account, the party is the source), 'OUT' (money out, the party is the destination), or None when the cue is absent or conflicting."""
    verdicts = set()
    if _FROM_P.search(marked):
        verdicts.add("IN")
    if _TO_P.search(marked):
        verdicts.add("OUT")
    if _SUBJ_RECEIVED.search(marked):
        verdicts.add("OUT")
    if _SUBJ_SENT.search(marked):
        verdicts.add("OUT" if _OUT_OF.search(marked) else "IN")
    return verdicts.pop() if len(verdicts) == 1 else None


_TYPE_OF = {"IN": "CREDIT", "OUT": "DEBIT"}
_WORD = {"CREDIT": "a credit", "DEBIT": "a debit"}


def _describe(t: dict, parties: Parties) -> str:
    cp = _core(str(t.get("counterparty") or "")) or "an unnamed counterparty"
    kind = "from" if t.get("type") == "CREDIT" else "to"
    return f"{_WORD.get(t.get('type'), 'a transaction')} {kind} {cp} on {str(t.get('date'))[:10]}"


def _amount_text(a: dict) -> str:
    return a["raw"].strip()


def _rupees(v: float) -> str:
    """Rs.3,40,700 (Indian digit grouping)."""
    s = str(int(round(v)))
    head, tail = s[:-3], s[-3:]
    groups = []
    while head:
        groups.append(head[-2:])
        head = head[:-2]
    return "Rs." + ",".join([*reversed(groups), tail]) if groups else "Rs." + tail


def _aggregates(txns: list[dict]) -> list[float]:
    """Totals and sums of two or more transactions on one side. An amount that is both one transaction and one of these is ambiguous (Rs.2.5L is the debit of
    Rs.2.465L rounded AND the sum of Rs.1.1L and Rs.1.4L), so no claim about it is checked."""
    out: list[float] = []
    for side in ("CREDIT", "DEBIT"):
        vals = [float(t.get("amount_inr") or 0) for t in txns if t.get("type") == side]
        if len(vals) > 12:
            vals = vals[:12]
        for r in range(2, len(vals) + 1):
            out += [sum(c) for c in itertools.combinations(vals, r)]
    return out


# ── claim checks ─────────────────────────────────────────────────────────────
def _binding(sentence, marked, amounts, dates, party_keys, txns, parties) -> list[str]:
    """party / direction / date of a single-transaction amount."""
    why: list[str] = []
    singles = []
    aggregates = _aggregates(txns)
    for a in amounts:
        cands = [t for t in txns if abs(float(t.get("amount_inr") or 0) - a["value"]) <= max(a["tol"], 0.5)]
        if cands and not any(abs(v - a["value"]) <= max(a["tol"], 0.5) for v in aggregates):
            singles.append((a, cands))
    if not singles:
        return why
    direction = _direction(marked) if len(party_keys) == 1 and not (parties.own & party_keys) else None
    for a, cands in singles:
        if len(party_keys) == 1:
            key = next(iter(party_keys))
            by_party = [t for t in cands if _core(str(t.get("counterparty") or "")).lower() == key]
            if not by_party:
                shown = "; ".join(sorted({_describe(t, parties) for t in cands}))
                why.append(f"{_amount_text(a)} appears in the record as {shown}, not with {parties.name(key)}.")
                continue
            if direction:
                by_dir = [t for t in by_party if t.get("type") == _TYPE_OF[direction]]
                if not by_dir:
                    shown = "; ".join(sorted({_describe(t, parties) for t in by_party}))
                    word = "received from" if direction == "IN" else "paid to"
                    why.append(f"The sentence says {_amount_text(a)} was {word} {parties.name(key)}; the record shows {shown}.")
                    continue
                by_party = by_dir
        else:
            by_party = cands
        if len(dates) == 1 and len(amounts) == 1:
            if not any(str(t.get("date"))[:10] == dates[0].isoformat() for t in by_party):
                shown = "; ".join(sorted({_describe(t, parties) for t in by_party}))
                why.append(f"The sentence dates {_amount_text(a)} to {dates[0].isoformat()}; the record shows {shown}.")
    return why


_SIDE_TOTAL = re.compile(
    r"\b(?:total(?:l?ed|ling)?|aggregat\w+|sum(?:med)?\s+(?:to|of)|amount(?:ed|ing)?\s+to|came\s+to|comes\s+to)\b", re.I)
_SIDE_WORD = re.compile(r"\b(credits?|debits?)\b", re.I)


def _side_totals(sentence, amounts, txns) -> list[str]:
    why = []
    if not _SIDE_TOTAL.search(sentence) or len(amounts) != 1:
        return why
    m = _SIDE_TOTAL.search(sentence)
    before = [w for w in _SIDE_WORD.finditer(sentence) if w.start() < m.start()] or [w for w in _SIDE_WORD.finditer(sentence)]
    sides = {("CREDIT" if w.group(1).lower().startswith("credit") else "DEBIT") for w in before[-1:]}
    if len(sides) != 1 or len({w.group(1).lower()[:5] for w in _SIDE_WORD.finditer(sentence)}) > 1:
        return why                                               # both sides named: ambiguous
    side = sides.pop()
    totals = {s: sum(float(t.get("amount_inr") or 0) for t in txns if t.get("type") == s) for s in ("CREDIT", "DEBIT")}
    a = amounts[0]
    ok = lambda v: abs(a["value"] - v) <= max(a["tol"], 0.5)      # noqa: E731
    other = "DEBIT" if side == "CREDIT" else "CREDIT"
    if not totals[side] or ok(totals[side]):
        return why
    if totals[other] and ok(totals[other]):
        word = "credits" if side == "CREDIT" else "debits"
        why.append(f"The sentence gives {_amount_text(a)} as the total of the {word}; the record shows {_amount_text(a)} is the total of the {'debits' if side == 'CREDIT' else 'credits'}, "
                   f"and the {word} total {_rupees(totals[side])}.")
    return why


_PCT_OF = re.compile(r"(\d+(?:\.\d+)?)\s*%\s+of\s+(?:the\s+|all\s+the\s+|all\s+)?(credits?|debits?)\b", re.I)


def _ratio_sides(sentence, txns) -> list[str]:
    why = []
    credits = [float(t.get("amount_inr") or 0) for t in txns if t.get("type") == "CREDIT"]
    debits = [float(t.get("amount_inr") or 0) for t in txns if t.get("type") == "DEBIT"]
    flagged_d = sum(float(t.get("amount_inr") or 0) for t in txns if t.get("type") == "DEBIT" and t.get("is_flagged"))
    tc, td = sum(credits), sum(debits)
    over = {"credit": {round(td / tc * 100, 2)} | {round(flagged_d / tc * 100, 2)} | {round(x / tc * 100, 2) for x in credits + debits} if tc else set(),
            "debit": {round(tc / td * 100, 2)} | {round(flagged_d / td * 100, 2)} | {round(x / td * 100, 2) for x in credits + debits} if td else set()}
    for m in _PCT_OF.finditer(sentence):
        pct, side = float(m.group(1)), "credit" if m.group(2).lower().startswith("credit") else "debit"
        near = lambda s: any(abs(pct - r) <= 0.6 for r in over[s])   # noqa: E731
        other = "debit" if side == "credit" else "credit"
        if over[side] and not near(side) and near(other):
            why.append(f"The sentence puts {m.group(1)}% over the {side}s; in the record that ratio is taken over the {other}s.")
    return why


_QUANT = re.compile(r"\b(?:all|every|each)\s+(?:of\s+)?(?:the\s+)?(?:(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+)?(credits?|debits?)\b", re.I)


def _quantifiers(sentence, marked, party_keys, txns, parties) -> list[str]:
    why = []
    m = _QUANT.search(sentence)
    if not m or len(party_keys) != 1:
        return why
    side = "CREDIT" if m.group(1).lower().startswith("credit") else "DEBIT"
    key = next(iter(party_keys))
    direction = None if key in parties.own else _direction(marked)
    side_txns = [t for t in txns if t.get("type") == side]
    if not side_txns:
        return why
    if direction and _TYPE_OF[direction] != side:
        word = "received from" if direction == "IN" else "paid to"
        why.append(f"The sentence says all the {side.lower()}s were {word} {parties.name(key)}, which reverses the direction of {side.lower()}s in the record.")
        return why
    cps = {_core(str(t.get("counterparty") or "")).lower() for t in side_txns}
    if cps != {key}:
        shown = ", ".join(sorted(parties.name(c) for c in cps if c)) or "other counterparties"
        why.append(f"The sentence says all the {side.lower()}s involve {parties.name(key)}; the record shows {shown}.")
    return why


_FLAG_PATTERNS = (
    re.compile(_PLACEHOLDER + r"\s*,?\s*(?:which|that|who)\s+(?:is|was|are|were)\s+(?:an?\s+|the\s+)?(?:(?:i4c|mule\s*hunter)[- ]?)?flagged", re.I),
    re.compile(_PLACEHOLDER + r"\s*,?\s*(?:an?\s+|the\s+)?(?:(?:i4c|mule\s*hunter)[- ]?flagged|flagged(?:\s+(?:by|in)\s+(?:the\s+)?i4c)?)\b", re.I),
    re.compile(r"\b(?:(?:i4c|mule\s*hunter)[- ]?flagged|flagged\s+(?:by|in)\s+(?:the\s+)?i4c|flagged)\s+" + _PLACEHOLDER, re.I),
)


def _flags(marked, party_keys, parties) -> list[str]:
    if len(party_keys) != 1 or not any(p.search(marked) for p in _FLAG_PATTERNS):
        return []
    key = next(iter(party_keys))
    if parties.flagged.get(key):
        return []
    flagged = sorted(parties.name(k) for k, v in parties.flagged.items() if v)
    return [f"The sentence calls {parties.name(key)} flagged; the record does not mark it" + (f" (it marks {', '.join(flagged)})." if flagged else ".")]


def _mask_numbers(sentence: str, amounts: list[dict]) -> str:
    """The sentence with every amount replaced by a token and every decimal point removed, so the clause templates (which stop at a full stop) read
    'sent Rs.1.1L to handle A' as one clause."""
    out = sentence
    for a in sorted(amounts, key=lambda x: x["span"][0], reverse=True):
        lo, hi = a["span"]
        out = out[:lo] + " §a§ " + out[hi:]
    return re.sub(r"(?<=\d)\.(?=\d)", "", out)


def check(narrative: str, transactions: list[dict], extract_amounts, extract_dates) -> list[dict]:
    """[{type, text, why}] for every sentence whose claim the record contradicts. `extract_*` are grounding's extractors (passed in: no import cycle)."""
    txns = [t for t in (transactions or []) if isinstance(t, dict)]
    if not txns or not (narrative or "").strip():
        return []
    parties = Parties(txns)
    findings: list[dict] = []
    seen: set[str] = set()
    for sent in sentences(narrative):
        if _SKIP.search(sent):
            continue
        amounts = [a for a in extract_amounts(sent) if not a.get("foreign")]
        dates = [d["date"] for d in extract_dates(sent) if d.get("date")]
        party_keys, marked = parties.mentions(_mask_numbers(sent, extract_amounts(sent)))
        why = (_flags(marked, party_keys, parties) + _side_totals(sent, amounts, txns) + _ratio_sides(sent, txns)
               + _quantifiers(sent, marked, party_keys, txns, parties)
               + ([] if _SIDE_TOTAL.search(sent) else _binding(sent, marked, amounts, dates, party_keys, txns, parties)))
        if why and sent not in seen:
            seen.add(sent)
            findings.append({"type": TYPE, "text": " ".join(sent.split())[:100], "why": " ".join(dict.fromkeys(why))[:400]})
    return findings
