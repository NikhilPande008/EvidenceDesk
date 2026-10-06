"""
Deterministic evidence grounding for Ground-of-Suspicion narratives (no LLM, no Snowflake).

A narrative may only state facts that exist in the CASE RECORD:
    transactions  +  customer profile text  +  alert narrative  +  context dates
                     (alert date, PO-entered suspicion date)

Claim classes extracted and checked
  HARD  (any unsupported claim blocks READY *and* FILE — cannot be overridden):
      amount · date · txn_id · channel · geography · identifier (UPI/account/IFSC/PAN/phone)
      · entity (named company/bank/trust) · profile_income · profile_fact (dormant / PEP / account age)
  SOFT  (labelled UNVERIFIED in the UI; PO must acknowledge before FILE):
      third-party characterisations ("known links to hawala networks", "FATF-listed", …)
      · percentages / multiples that cannot be reproduced from the data · occupation inferences

What this module does NOT verify is returned explicitly in `verification_scope.not_verified`,
so the UI never implies complete verification.
"""

from __future__ import annotations

import itertools
import re
from datetime import date, datetime, timedelta
from typing import Any

# ── vocabulary ───────────────────────────────────────────────────────────────
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_UNIT_MULT = {"lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5, "l": 1e5,
              "crore": 1e7, "crores": 1e7, "cr": 1e7, "k": 1e3, "thousand": 1e3,
              "million": 1e6, "mn": 1e6}

CHANNELS = {  # narrative token -> canonical channel value used in TRANSACTIONS.CHANNEL
    "upi": "UPI", "neft": "NEFT", "rtgs": "RTGS", "imps": "IMPS", "swift": "SWIFT",
    "atm": "ATM", "nach": "NACH", "cheque": "CHEQUE", "check": "CHEQUE",
}
_CASH_CHANNEL = re.compile(
    r"\bcash\s+(?:deposit|deposits|withdrawal|withdrawals|credit|credits|debit|debits|transaction|transactions|payment|payments)\b"
    r"|\b(?:deposited|withdrawn|paid|received)\s+in\s+cash\b|\bin\s+cash\b"
    r"|\bcash\s+(?:was|were|had\s+been)\s+(?:handed|paid|given|received|withdrawn|deposited|collected)\b"
    r"|\bhanded\s+over\s+(?:the\s+)?cash\b|\bcash\s+hand-?over\b"
    r"|\b(?:withdrew|deposited|collected|received|paid)\s+(?:the\s+|some\s+)?cash\b", re.I)
# Channels named by phrase rather than by code. (pattern, label, record channels that make the phrase true)
_CHANNEL_PHRASES = (
    (re.compile(r"\b(?:wire\s+transfers?|international\s+wires?|(?:foreign|international|outward|inward|overseas)\s+remittances?|remittances?)\b"
                r"|\b(?:funds?|money|amounts?|sums?|proceeds|payments?|credits?|debits?|balance|it|them)\s+(?:was|were|is|are|had\s+been|has\s+been|have\s+been|being|got)\s+wired\b"
                r"|\bwired\s+(?:the\s+|these\s+|those\s+)?(?:funds?|money|amounts?|sums?|abroad|overseas|out|to|(?:Rs\.?|₹|INR)\s*\d)", re.I),
     "WIRE", {"SWIFT", "RTGS", "NEFT", "WIRE"}),
    (re.compile(r"\b(?:debit|credit|prepaid)\s+cards?\b|\bcard\s+payments?\b|\bPOS\b"), "CARD", {"CARD", "POS", "ATM"}),
    (re.compile(r"\b(?:internet|net|online)\s+banking\b", re.I), "INTERNET_BANKING", {"NEFT", "RTGS", "IMPS", "NETBANKING"}),
    (re.compile(r"\b(?:demand\s+drafts?|pay\s+orders?|banker'?s\s+cheques?)\b", re.I), "DRAFT", {"DD", "DRAFT", "CHEQUE"}),
)

GEOGRAPHIES = (
    "UAE", "Dubai", "Abu Dhabi", "Sharjah", "United Arab Emirates", "Singapore", "Hong Kong",
    "China", "Pakistan", "Iran", "North Korea", "DPRK", "Myanmar", "Nepal", "Bangladesh",
    "Sri Lanka", "Thailand", "Malaysia", "Cyprus", "Cayman", "Panama", "BVI", "British Virgin Islands",
    "Mauritius", "Seychelles", "London", "United Kingdom", "UK", "United States", "USA", "Russia",
    "Turkey", "Lebanon", "Nigeria", "Cambodia", "Laos", "Vietnam", "Afghanistan", "Syria", "Yemen",
    "Switzerland", "Hong-Kong", "Qatar", "Oman", "Saudi Arabia", "Bahrain", "Kuwait", "Canada", "Australia",
    # offshore centres and common remittance corridors
    "Maldives", "Bahamas", "Jersey", "Guernsey", "Isle of Man", "Liechtenstein", "Monaco", "Malta", "Belize", "Barbados", "Bermuda",
    "Gibraltar", "Luxembourg", "Ireland", "Netherlands", "Germany", "France", "Italy", "Spain", "Portugal", "Belgium", "Austria",
    "Sweden", "Norway", "Denmark", "Finland", "Poland", "Ukraine", "Belarus", "Armenia", "Azerbaijan", "Kazakhstan", "Uzbekistan",
    "Iraq", "Egypt", "Libya", "Sudan", "Somalia", "Ethiopia", "Kenya", "Tanzania", "Uganda", "Ghana", "South Africa", "Zimbabwe",
    "Zambia", "Mozambique", "Angola", "Congo", "Cuba", "Venezuela", "Mexico", "Brazil", "Argentina", "Colombia", "Peru", "Chile",
    "Israel", "Japan", "South Korea", "Korea", "Taiwan", "Indonesia", "Philippines", "Brunei", "Macau", "Macao", "Bhutan",
    "New Zealand", "Ireland",
    # cities that stand for a country in a narrative
    "Kathmandu", "Karachi", "Lahore", "Islamabad", "Dhaka", "Colombo", "Shenzhen", "Shanghai", "Beijing", "Guangzhou", "Moscow",
    "Tehran", "Istanbul", "Doha", "Riyadh", "Muscat", "Manama", "Bangkok", "Kuala Lumpur", "Jakarta", "Manila", "Tokyo", "Seoul",
    "Hanoi", "Phnom Penh", "Yangon", "Kabul", "Damascus", "Beirut", "Baghdad", "Tripoli", "Lagos", "Nairobi", "Johannesburg",
    "Accra", "Kampala", "Zurich", "Geneva", "Frankfurt", "Paris", "Amsterdam", "New York", "Miami", "Toronto", "Sydney", "Dublin",
    "Limassol", "Nicosia", "Valletta", "Port Louis", "Dubai Marina",
)

# Third-party characterisations the record cannot verify. Flagged only when the phrase's
# key term is NOT already present in the case record.
_ASSERTION_PATTERNS = (
    (r"known\s+(?:links?|ties|associates?|connections?)(?:\s+(?:to|with)\s+[^.,;]{0,50}?(?=\s+(?:and|but|who|which|that)\b|[.,;]|$))?", "known-links"),
    (r"\bhawala\b(?:\s+\w+){0,3}", "hawala"),
    (r"\bterror(?:ism|ist|ists)?\b(?:\s+\w+){0,3}", "terrorism"),
    (r"\b(?:organi[sz]ed\s+crime|crime\s+syndicate|criminal\s+(?:network|gang|group|organi[sz]ation)s?)\b", "criminal-network"),
    (r"\b(?:FATF|grey|gray|black)[-\s]?list(?:ed)?\b", "fatf-listed"),
    (r"\bsanction(?:ed|s)\b(?:\s+\w+){0,3}", "sanctions"),
    (r"\b(?:shell|front)\s+(?:company|companies|entity|entities)\b", "shell-company"),
    (r"\bblack-?listed\b", "blacklisted"),
    (r"\bnotorious(?:ly)?\b", "notorious"),
    (r"\b(?:linked|connected|associated)\s+(?:to|with)\s+(?:known\s+)?(?:fraud|mule|criminal|terror)\w*(?:\s+\w+){0,3}", "linked-to"),
)

_HARD_TYPES = ("amount", "txn_id", "date", "channel", "geography", "identifier", "entity",
               "profile_income", "profile_fact", "evidence")

VERIFIED_CLASSES = [
    "amounts (₹/Rs/INR before or after the figure, lakh/crore, written in words, incl. subset sums)",
    "dates (ISO, d/m/y, dotted, d Mon y, with no year, or as ordinals)", "transaction IDs", "channels (by code or phrase: UPI, wire transfer, card, cash ...)",
    "geographies (foreign countries and common remittance cities, from a list)", "identifiers (UPI handle, account/card no., IFSC, PAN, phone, e-mail)",
    "named entities (company, bank, trust ... by suffix or known bank brand)", "declared income", "account age / tenure / opening year / dormancy / PEP status",
    "attribution, in unambiguous sentences only: party, direction and date of a single-transaction amount; side of a total; side of a ratio; \"all credits/debits\" claims; flagged parties (labelled UNVERIFIED)",
]
NOT_VERIFIED = [
    "which party an amount or date belongs to, and which way the money moved, except in the unambiguous single-amount sentences the attribution check reads (anything else is accepted wherever the text places it)",
    "interpretive statements and inferences (why a pattern is suspicious)",
    "third-party characterisations unless the term appears in the case record",
    "personal names and relationships not present as counterparties",
    "percentages / multiples not reproducible from the transaction data (flagged UNVERIFIED)",
    "occupation and lifestyle inferences (flagged UNVERIFIED)",
]


# ── helpers ──────────────────────────────────────────────────────────────────
def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _fmt_amount(v: float) -> str:
    if v >= 1e7:
        return f"₹{v / 1e7:.2f}Cr (₹{v:,.0f})"
    if v >= 1e5:
        return f"₹{v / 1e5:.2f}L (₹{v:,.0f})"
    return f"₹{v:,.0f}"


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _count_from_text(raw: str) -> int | None:
    """"14" or "fourteen" or "twenty-five" → an integer; None when it is neither."""
    raw = (raw or "").strip().lower()
    if raw.isdigit():
        return int(raw)
    parsed = _words_to_value([t for t in re.split(r"[\s-]+", raw) if t])
    return int(parsed[0]) if parsed else None


# ── amount extraction ────────────────────────────────────────────────────────
_AMT_PREFIXED = re.compile(
    r"(?<![A-Za-z0-9])(?:₹|Rs\.?|INR|rupees?)\s*(\d[\d,]*(?:\.\d+)?)\s*(lakhs?|lacs?|crores?|thousand|million|mn|cr|L|K|k|M)?(?![A-Za-z0-9₹])",
    re.I)
_AMT_UNIT_ONLY = re.compile(
    r"(?<![A-Za-z0-9₹.,])(\d[\d,]*(?:\.\d+)?)\s*(lakhs?|lacs?|crores?|cr)\b(?!\w)", re.I)
_AMT_FOREIGN = re.compile(
    r"(?<![A-Za-z0-9])(?:USD|US\$|\$|EUR|€|GBP|£|AED|SGD|HKD)\s*(\d[\d,]*(?:\.\d+)?)\s*(million|mn|m|k|thousand|lakh|crore)?", re.I)
# "7,85,000 INR", "785000 rupees", "2.5 million rupees": the currency AFTER the number
_AMT_SUFFIXED = re.compile(
    r"(?<![A-Za-z0-9₹.,])(\d[\d,]*(?:\.\d+)?)\s*(lakhs?|lacs?|crores?|thousand|million|mn|cr|k|L|M)?\s*(?:rupees?|INR|Rs\.?)(?![A-Za-z])", re.I)

# Amounts written in words: "twenty-five lakh rupees", "five hundred thousand rupees", "Rupees Seven Lakh Eighty Five Thousand".
_UNITS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
                                     "sixteen seventeen eighteen nineteen".split())}
_TENS = {w: 20 + 10 * i for i, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split())}
_SCALES = {"thousand": 1e3, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5, "million": 1e6, "crore": 1e7, "crores": 1e7}
_MONEY_SCALES = {"lakh", "lakhs", "lac", "lacs", "crore", "crores"}           # unambiguously money in Indian usage; "thousand"/"million" need a currency word
_NUMWORD = "|".join(sorted([*_UNITS, *_TENS, "hundred", "and", *_SCALES], key=len, reverse=True))
_WORD_AMT = re.compile(r"(?<![A-Za-z])((?:₹|Rs\.?|INR|rupees?)\s+)?((?:" + _NUMWORD + r")(?:[\s-]+(?:" + _NUMWORD + r"))*)(?![A-Za-z])(\s+(?:rupees?|INR|Rs\.?)(?![A-Za-z]))?", re.I)


def _words_to_value(tokens: list[str]) -> tuple[float, float] | None:
    """(value, tolerance) of a run of number words, or None when it is not a well-formed number."""
    total, current, last_scale, seen_number = 0.0, 0.0, None, False
    for t in tokens:
        if t == "and":
            continue
        if t in _UNITS:
            current += _UNITS[t]; seen_number = True; last_scale = None
        elif t in _TENS:
            current += _TENS[t]; seen_number = True; last_scale = None
        elif t == "hundred":
            if not seen_number and current == 0:
                return None
            current = (current or 1) * 100; last_scale = None
        elif t in _SCALES:
            if not seen_number and current == 0:
                return None
            total += (current or 1) * _SCALES[t]; current = 0; last_scale = _SCALES[t]
        else:
            return None
    if not seen_number:
        return None
    return total + current, (last_scale / 2 if last_scale else 0.5)


def extract_amounts(text: str) -> list[dict]:
    """[{value, tol, span, raw, foreign}] — value in rupees; tol = half-unit of displayed precision."""
    out: list[dict] = []
    taken: list[tuple[int, int]] = []

    def add(m, num_s, unit_s, foreign=False):
        try:
            base = _num(num_s)
        except ValueError:
            return
        unit = (unit_s or "").lower().rstrip(".")
        mult = _UNIT_MULT.get(unit, 1.0)
        decimals = len(num_s.split(".")[1]) if "." in num_s else 0
        value = base * mult
        tol = 0.5 if not unit else (mult * (10 ** -decimals)) / 2
        if not unit and value < 100 and not foreign:
            return                                   # "₹50" style trivia, not a transaction claim
        out.append({"value": value, "tol": tol, "span": m.span(), "raw": m.group(0).strip(), "foreign": foreign})
        taken.append(m.span())

    for m in _AMT_FOREIGN.finditer(text):
        add(m, m.group(1), m.group(2), foreign=True)
    for m in _AMT_PREFIXED.finditer(text):
        if not any(a <= m.start() < b for a, b in taken):
            add(m, m.group(1), m.group(2))
    for m in _AMT_UNIT_ONLY.finditer(text):
        if not any(a <= m.start() < b for a, b in taken):
            add(m, m.group(1), m.group(2))
    for m in _AMT_SUFFIXED.finditer(text):
        if not any(a <= m.start() < b or m.start() <= a < m.end() for a, b in taken):
            add(m, m.group(1), m.group(2))
    for m in _WORD_AMT.finditer(text):
        tokens = [t.lower() for t in re.split(r"[\s-]+", m.group(2).strip()) if t]
        while tokens and tokens[0] == "and":
            tokens.pop(0)
        while tokens and tokens[-1] == "and":
            tokens.pop()
        parsed = _words_to_value(tokens) if tokens else None
        if parsed is None or any(a <= m.start(2) < b for a, b in taken):
            continue
        value, tol = parsed
        currency = bool(m.group(1) or m.group(3))
        # "three UPI credits" is a count, not money; a figure in words needs a lakh/crore, or a currency word beside it
        if not (any(t in _MONEY_SCALES for t in tokens) or (currency and value >= 100)):
            continue
        out.append({"value": value, "tol": tol, "span": m.span(), "raw": m.group(0).strip(), "foreign": False})
        taken.append(m.span())
    return out


# ── date extraction ──────────────────────────────────────────────────────────
_ISO = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_DMY = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")
_D_MON_Y = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?,?\s+(\d{4})\b", re.I)
_MON_D_Y = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", re.I)
_DOT = re.compile(r"(?<![\d.])(\d{1,2})\.(\d{1,2})\.(\d{4})(?![\d.]\d)")
_YMD_SLASH = re.compile(r"\b(\d{4})/(\d{1,2})/(\d{1,2})\b")
_COMPACT = re.compile(r"(?<![\d.,₹])((?:19|20)\d{2})(\d{2})(\d{2})(?![\d])")
_MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)(?:[a-z]*)"
# a day and month with NO year ("27th August", "August 27", "the twenty-seventh of August"): checked against the record's days of the year
_D_MON = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?" + _MONTH + r"\b(?!\s*,?\s*\d{4})", re.I)
_MON_D = re.compile(r"\b" + _MONTH + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b(?!\s*,?\s*\d{4})(?!\s*(?:times|transactions|credits|debits|days|months|years))", re.I)
_ORDINALS = {w: i for i, w in enumerate(
    "first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth fourteenth fifteenth sixteenth seventeenth "
    "eighteenth nineteenth twentieth".split(), start=1)}
_ORDINALS.update({"thirtieth": 30})
_ORDINALS.update({f"{t}{sep}{u}": tv + uv for t, tv in (("twenty", 20), ("thirty", 30)) for sep in ("-", " ")
                  for u, uv in (("first", 1), ("second", 2), ("third", 3), ("fourth", 4), ("fifth", 5), ("sixth", 6), ("seventh", 7), ("eighth", 8), ("ninth", 9)) if tv + uv <= 31})
_ORD_MON = re.compile(r"\b(?:the\s+)?(" + "|".join(sorted((re.escape(k) for k in _ORDINALS), key=len, reverse=True)) + r")\s+(?:of\s+)?" + _MONTH + r"\b(?!\s*,?\s*\d{4})", re.I)


def _mk(y, m, d) -> date | None:
    try:
        return date(int(y), int(m), int(d))
    except ValueError:
        return None


def extract_dates(text: str) -> list[dict]:
    """[{date|None, raw}] — date None means it looked like a date but is not a valid calendar date."""
    found: list[dict] = []
    for m in _ISO.finditer(text):
        found.append({"date": _mk(*m.groups()), "raw": m.group(0)})
    for m in _DMY.finditer(text):
        d, mo, y = m.groups()
        found.append({"date": _mk(y, mo, d), "raw": m.group(0)})
    for m in _D_MON_Y.finditer(text):
        d, mon, y = m.groups()
        found.append({"date": _mk(y, _MONTHS[mon[:3].lower()], d), "raw": m.group(0)})
    for m in _MON_D_Y.finditer(text):
        mon, d, y = m.groups()
        found.append({"date": _mk(y, _MONTHS[mon[:3].lower()], d), "raw": m.group(0)})
    for m in _DOT.finditer(text):
        d, mo, y = m.groups()
        found.append({"date": _mk(y, mo, d), "raw": m.group(0)})
    for m in _YMD_SLASH.finditer(text):
        y, mo, d = m.groups()
        found.append({"date": _mk(y, mo, d), "raw": m.group(0)})
    for m in _COMPACT.finditer(text):
        y, mo, d = m.groups()
        if _mk(y, mo, d):                                   # 8 digits that are not a calendar date are just a number
            found.append({"date": _mk(y, mo, d), "raw": m.group(0)})
    taken = [m.span() for pat in (_ISO, _DMY, _D_MON_Y, _MON_D_Y, _DOT, _YMD_SLASH) for m in pat.finditer(text)]
    for pat, order in ((_D_MON, "dm"), (_MON_D, "md"), (_ORD_MON, "om")):
        for m in pat.finditer(text):
            if any(a <= m.start() < b for a, b in taken):
                continue
            g = m.groups()
            if order == "dm":
                day, mon = int(g[0]), g[1]
            elif order == "md":
                mon, day = g[0], int(g[1])
            else:
                day, mon = _ORDINALS[re.sub(r"\s+", " ", g[0].lower())], g[1]
            if mon.lower() == "may" and not m.group(0).lstrip("the ").lstrip()[:1].isdigit() and "May" not in m.group(0):
                continue                                    # lower-case "may 5" is a verb, not a month
            valid = _mk(2024, _MONTHS[mon[:3].lower()], day) is not None      # 2024 is a leap year: 29 Feb is a real day of the year
            found.append({"date": None, "partial": (_MONTHS[mon[:3].lower()], day), "valid_partial": valid, "raw": m.group(0).strip()})
            taken.append(m.span())
    return found


def _as_date(v: Any) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except (ValueError, TypeError):
        return None


# ── identifiers / entities ───────────────────────────────────────────────────
# An e-mail address is personal data and is never a checkable transaction fact; matched (and masked) before the UPI-handle
# pattern so one address is one finding. A spaced 12-digit number is the Aadhaar layout (a contiguous one is caught by account_no).
_EMAIL = re.compile(r"\b[\w.+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+\b")
_IDENT_PATTERNS = (
    ("aadhaar_number", re.compile(r"(?<!\d)\d{4}[ \-]\d{4}[ \-]\d{4}(?!\d)")),
    ("upi_handle", re.compile(r"\b[\w.\-]{2,}@[a-z]{2,}\b", re.I)),
    ("masked_upi", re.compile(r"\bUPI[-\s]?[A-Za-z0-9]*\d{2}[Xx*]{2,}\d{2}\b")),
    ("ifsc", re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")),
    ("pan", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("phone", re.compile(r"(?<!\d)[6-9]\d{9}(?!\d)")),
    ("phone_formatted", re.compile(r"(?<![\d+])(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]\d{5}(?!\d)|\+91[\s-]?[6-9]\d{9}(?!\d)")),
    ("spaced_number", re.compile(r"(?<!\d)\d{4}(?:[ -]\d{4}){3,4}(?!\d)")),
    ("account_no", re.compile(r"(?<![\d,.₹])\d{9,18}(?![\d,])")),
)
_ENTITY = re.compile(
    r"\b((?:[A-Z][A-Za-z0-9&.\-]*\s+){1,4}(?:Pvt\.?\s*Ltd\.?|Private\s+Limited|Ltd\.?|Limited|LLP|Bank|Corporation|Corp\.?|"
    r"Society|Trust|Enterprises|Traders|Industries|Infrastructure|Constructions|Roadways|Engineering|Exports|Hospital|Foundation|"
    r"Holdings|Group|Inc\.?|Co\.?|Company|Associates|Partners|Jewellers|Jewelers|Motors|Textiles|Pharma|Pharmaceuticals|Logistics|Finance|"
    r"Capital|Ventures|Services|Solutions|Technologies|International|Brothers|Bros\.?|Stores))\b")
_ENTITY_SONS = re.compile(r"\b([A-Z][A-Za-z0-9.\-]*\s+(?:&|and)\s+(?:Sons|Co\.?|Company|Associates|Brothers|Bros\.?))\b")
# Bank brands that are named without the word "Bank" ("ICICI received the funds").
_BANK_BRANDS = re.compile(r"\b(SBI|HDFC|ICICI|PNB|HSBC|IDFC|IDBI|RBL|Kotak|Barclays|Citibank)\b")
_TAIL_DIGITS = re.compile(r"\b(?:card|account|a/c|acct)\b[^.\n]{0,25}?\bending\s+(?:with\s+|in\s+)?(\d{3,6})\b", re.I)
_ENTITY_STOP = {"the", "a", "an", "of", "to", "from", "at", "by", "in", "on", "and", "with", "via", "through"}


_ENTITY_ABBREV = {"pvt", "ltd", "inc", "co", "corp", "bros", "mr", "mrs", "ms", "dr", "st", "no", "m/s"}


def _after_sentence_break(entity: str) -> str:
    """'July. DEF Engineering Pvt Ltd' -> 'DEF Engineering Pvt Ltd'. A capitalised word that ends in a full stop and is not an abbreviation
    ends the previous sentence; it is not part of the company name."""
    toks = entity.split()
    for i in range(len(toks) - 2, -1, -1):
        if toks[i].endswith(".") and toks[i].rstrip(".").lower() not in _ENTITY_ABBREV:
            return " ".join(toks[i + 1:])
    return entity


def _entity_supported(entity: str, record_norm: str) -> bool:
    toks = [t for t in _norm(entity).split() if t not in _ENTITY_STOP and len(t) > 1]
    suffixes = {"pvt", "ltd", "limited", "private", "llp", "bank", "corporation", "corp", "society", "trust"}
    core = [t for t in toks if t not in suffixes] or toks
    return bool(core) and all(t in record_norm.split() for t in core)


# ── profile parsing ──────────────────────────────────────────────────────────
_PROFILE_INCOME = re.compile(
    r"(?:₹|Rs\.?|INR)\s*(\d[\d,]*(?:\.\d+)?)\s*(lakhs?|lacs?|crores?|cr|L|K|k)?\s*(?:/|per\s+|a\s+|every\s+)\s*(month|mo|year|yr|annum|yearly|monthly)", re.I)
_PROFILE_INCOME_ANNUAL_WORDS = re.compile(
    r"(?:annual|yearly)\s+income\s*(?:of|is|:)?\s*(?:₹|Rs\.?|INR)\s*(\d[\d,]*(?:\.\d+)?)\s*(lakhs?|lacs?|crores?|cr|L|K|k)?", re.I)
_TENURE = re.compile(r"\b(?:banking|banked|customer|client|relationship|account(?:\s+holder)?)\b[^.]{0,40}?\bfor\s+(?:the\s+(?:last|past)\s+)?"
                     r"(?:about\s+|around\s+|over\s+|nearly\s+)?(\d+|(?:" + _NUMWORD + r")(?:[\s-]+(?:" + _NUMWORD + r"))*)\s*(month|year)s?\b", re.I)
_OPENED_YEAR = re.compile(r"\b(?:opened|onboarded|created|started|established|customer\s+since|banking\s+since|with\s+us\s+since)\b[^.]{0,30}?"
                          r"\b(?:in|on|during|since)?\s*(?:[A-Za-z]+\s+)?((?:19|20)\d{2})\b", re.I)
_ACCOUNT_AGE = re.compile(r"(?:account\s+)?(\d+)\s*(month|year)s?\s+old", re.I)


def parse_profile(text: str) -> dict:
    """Structured facts from a free-text KYC profile. Missing facts stay None."""
    t = text or ""
    monthly = annual = None
    m = _PROFILE_INCOME.search(t)
    if m:
        unit = (m.group(2) or "").lower()
        val = _num(m.group(1)) * _UNIT_MULT.get(unit, 1.0)
        per = m.group(3).lower()
        if per in ("month", "mo", "monthly"):
            monthly, annual = val, val * 12
        else:
            annual, monthly = val, val / 12
    else:
        m2 = _PROFILE_INCOME_ANNUAL_WORDS.search(t)
        if m2:
            unit = (m2.group(2) or "").lower()
            annual = _num(m2.group(1)) * _UNIT_MULT.get(unit, 1.0)
            monthly = annual / 12
    age_months = None
    a = _ACCOUNT_AGE.search(t)
    if a:
        age_months = int(a.group(1)) * (12 if a.group(2).lower() == "year" else 1)
    return {
        "monthly_income": monthly, "annual_income": annual, "account_age_months": age_months,
        "pep": bool(re.search(r"\bPEP\b|politically\s+exposed", t, re.I)),
        "dormant": bool(re.search(r"\bdormant\b|\binactive\b", t, re.I)),
        "nri": bool(re.search(r"\bNRI\b|non-resident", t, re.I)),
    }


# ── the validator ────────────────────────────────────────────────────────────
def validate_narrative(narrative: str, transactions: list[dict], *, profile_text: str = "",
                       alert_narrative: str = "", context_dates: list | None = None) -> dict:
    """Check every checkable fact in `narrative` against the case record. See module docstring."""
    narrative = narrative or ""
    transactions = transactions or []
    by_type: dict[str, list[str]] = {k: [] for k in _HARD_TYPES}
    unverified: list[dict] = []

    record_text = " ".join([profile_text or "", alert_narrative or ""])
    txn_text = " ".join(f"{t.get('counterparty') or ''} {t.get('channel') or ''}" for t in transactions)
    record_norm = _norm(record_text + " " + txn_text)
    profile = parse_profile(profile_text or "")

    if not transactions:
        by_type["evidence"].append("no transactions on record — nothing to verify the narrative against")

    # ── AMOUNTS ──────────────────────────────────────────────────────────────
    credits = [float(t.get("amount_inr") or 0) for t in transactions if t.get("type") == "CREDIT"]
    debits  = [float(t.get("amount_inr") or 0) for t in transactions if t.get("type") == "DEBIT"]
    allowed: list[tuple[float, str]] = [(float(t.get("amount_inr") or 0), "txn") for t in transactions]
    allowed += [(sum(credits), "credit_total"), (sum(debits), "debit_total")]
    for label, vals in (("credit_subset", credits), ("debit_subset", debits)):
        if 2 <= len(vals) <= 12:
            for r in range(2, len(vals) + 1):
                allowed += [(sum(c), label) for c in itertools.combinations(vals, r)]
    record_amounts = extract_amounts(record_text)
    allowed += [(a["value"], "record") for a in record_amounts]
    for k in ("monthly_income", "annual_income"):
        if profile[k]:
            allowed.append((profile[k], "profile"))
    allowed = [(v, k) for v, k in allowed if v > 0]

    n_amounts = 0
    for a in extract_amounts(narrative):
        n_amounts += 1
        if a["foreign"]:
            if a["raw"] not in record_text:
                by_type["amount"].append(f"{a['raw']} (foreign-currency amount not in case record)")
            continue
        if not any(abs(a["value"] - v) <= max(a["tol"], 0.5) for v, _ in allowed):
            by_type["amount"].append(_fmt_amount(a["value"]))

    # ── TXN IDs ──────────────────────────────────────────────────────────────
    known_ids = {str(t["txn_id"]).upper() for t in transactions if t.get("txn_id")}
    id_pat = re.compile(r"\b(?:TXN-[A-Z0-9-]+|T\d{2}[A-Z]?-\d+|ALERT-\d{2}-T\d+)\b", re.I)
    refs = [m.group(0).upper() for m in id_pat.finditer(narrative)]
    unresolved = sorted({r for r in refs if r not in known_ids})
    by_type["txn_id"] += unresolved

    # ── DATES ────────────────────────────────────────────────────────────────
    allowed_dates = {d for d in (_as_date(t.get("date")) for t in transactions) if d}
    allowed_dates |= {d for d in (_as_date(c) for c in (context_dates or [])) if d}
    allowed_dates |= {d["date"] for d in extract_dates(record_text) if d["date"]}
    n_dates = 0
    allowed_days = {(d.month, d.day) for d in allowed_dates}
    for d in extract_dates(narrative):
        n_dates += 1
        if d.get("partial"):                              # no year stated: it must at least be a day the record contains
            if not d["valid_partial"]:
                by_type["date"].append(d["raw"] + " (not a valid calendar date)")
            elif d["partial"] not in allowed_days:
                by_type["date"].append(d["raw"] + " (no year given; no such day in the case record)")
            continue
        if d["date"] is None or d["date"] not in allowed_dates:
            by_type["date"].append(d["raw"] + (" (not a valid calendar date)" if d["date"] is None else ""))

    # ── CHANNELS ─────────────────────────────────────────────────────────────
    txn_channels = {str(t.get("channel")).upper() for t in transactions if t.get("channel")}
    not_checkable: list[str] = []
    if txn_channels:
        mentioned = {CHANNELS[w.lower()] for w in re.findall(r"\b(" + "|".join(CHANNELS) + r")\b", narrative, re.I)}
        if _CASH_CHANNEL.search(narrative):
            mentioned.add("CASH")
        rec_up = record_text.upper()
        for ch in sorted(mentioned):
            if ch not in txn_channels and ch not in rec_up:
                by_type["channel"].append(ch)
        for pat, label, supports in _CHANNEL_PHRASES:
            m = pat.search(narrative)
            if m and not (txn_channels & supports) and m.group(0).lower() not in record_text.lower():
                by_type["channel"].append(f"{label} ({m.group(0).strip()})")
    else:
        not_checkable.append("channels (no channel data on transactions)")

    # ── GEOGRAPHIES ──────────────────────────────────────────────────────────
    for g in GEOGRAPHIES:
        if re.search(r"(?<![A-Za-z])" + re.escape(g) + r"(?![A-Za-z])", narrative, re.I):
            if not re.search(r"(?<![A-Za-z])" + re.escape(g) + r"(?![A-Za-z])", record_text + " " + txn_text, re.I):
                by_type["geography"].append(g)

    # ── IDENTIFIERS + ENTITIES ───────────────────────────────────────────────
    masked = narrative
    for a in extract_amounts(narrative):
        masked = masked[:a["span"][0]] + " " * (a["span"][1] - a["span"][0]) + masked[a["span"][1]:]
    rec_compact = re.sub(r"[\s\-]", "", (record_text + " " + txn_text).upper())
    for m in _EMAIL.finditer(masked):
        if re.sub(r"[\s\-]", "", m.group(0).upper()) not in rec_compact:
            by_type["identifier"].append(f"{m.group(0)} (email)")
        masked = masked[:m.start()] + " " * (m.end() - m.start()) + masked[m.end():]
    for kind, pat in _IDENT_PATTERNS:
        for m in pat.finditer(masked):
            tok = m.group(0)
            if kind == "account_no" and (_ISO.search(tok) or id_pat.search(tok)):
                continue
            if re.sub(r"[\s\-]", "", tok.upper()) not in rec_compact:
                by_type["identifier"].append(f"{tok} ({kind})")
    for m in _TAIL_DIGITS.finditer(narrative):
        if m.group(1) not in re.sub(r"[\s\-]", "", record_text + " " + txn_text):
            by_type["identifier"].append(f"{m.group(0).strip()} (card/account tail)")
    for m in _ENTITY.finditer(narrative):
        ent = _after_sentence_break(m.group(1))
        if len(ent.split()) < 2:                          # only the suffix was left after the sentence break
            continue
        if not _entity_supported(ent, record_norm):
            by_type["entity"].append(ent.strip())
    for pat in (_ENTITY_SONS, _BANK_BRANDS):
        for m in pat.finditer(narrative):
            ent = m.group(1)
            if not _entity_supported(ent, record_norm) and ent.strip() not in by_type["entity"]:
                by_type["entity"].append(ent.strip())

    # ── PROFILE CLAIMS ───────────────────────────────────────────────────────
    for m in itertools.chain(
            re.finditer(r"(?:declared|stated|reported|monthly|annual|yearly)\s+(?:(?:monthly|annual|yearly)\s+)?income[^.\d₹R]{0,20}"
                        r"(?:₹|Rs\.?|INR)\s*(\d[\d,]*(?:\.\d+)?)\s*(lakhs?|lacs?|crores?|cr|L|K|k)?", narrative, re.I),
            re.finditer(r"\b(?:earns?|earning|earned|salary\s+(?:of|is)|takes\s+home)\s+(?:about\s+|around\s+|approximately\s+|roughly\s+|nearly\s+|only\s+)?"
                        r"(?:₹|Rs\.?|INR)\s*(\d[\d,]*(?:\.\d+)?)\s*(lakhs?|lacs?|crores?|cr|L|K|k)?", narrative, re.I)):
        unit = (m.group(2) or "").lower()
        claimed = _num(m.group(1)) * _UNIT_MULT.get(unit, 1.0)
        tol = 0.5 if not unit else (_UNIT_MULT[unit] * (10 ** -(len(m.group(1).split(".")[1]) if "." in m.group(1) else 0))) / 2
        if profile["monthly_income"] is None:
            unverified.append({"type": "profile_income", "text": m.group(0).strip(),
                               "why": "declared income is not parseable from the customer profile"})
        elif not any(abs(claimed - v) <= max(tol, 0.5) for v in (profile["monthly_income"], profile["annual_income"])):
            by_type["profile_income"].append(
                f"{m.group(0).strip()} (profile: ₹{profile['monthly_income']:,.0f}/month, ₹{profile['annual_income']:,.0f}/year)")
    for m in re.finditer(r"\b(?:dormant|inactive)\s+(?:for\s+)?(?:the\s+)?(?:(?:last|past|previous)\s+)?(\d+)\s*(month|year)s?", narrative, re.I):
        if not profile["dormant"]:
            by_type["profile_fact"].append(f"'{m.group(0)}' — profile does not state the account was dormant")
    if re.search(r"\b(?:politically\s+exposed|PEP)\b", narrative, re.I) and not profile["pep"] \
            and not re.search(r"\bPEP\b|politically\s+exposed", record_text, re.I):
        by_type["profile_fact"].append("PEP status asserted but not in the customer profile / alert record")
    for m in re.finditer(r"account\s+(?:is\s+|was\s+)?(\d+)\s*(month|year)s?\s+old", narrative, re.I):
        claimed_m = int(m.group(1)) * (12 if m.group(2).lower() == "year" else 1)
        if profile["account_age_months"] is not None and abs(claimed_m - profile["account_age_months"]) > 1:
            by_type["profile_fact"].append(f"'{m.group(0)}' vs profile {profile['account_age_months']} months")
    ref_dates = [d for d in (_as_date(c) for c in (context_dates or [])) if d]
    age = profile["account_age_months"]
    for m in _TENURE.finditer(narrative):
        n = _count_from_text(m.group(1))
        unit = m.group(2).lower()
        if n is None:
            continue
        claimed_m = n * (12 if unit == "year" else 1)
        if age is None:
            unverified.append({"type": "tenure", "text": m.group(0).strip()[:100], "why": "the customer profile states no account age to check this against"})
        elif claimed_m > age + 1:
            by_type["profile_fact"].append(f"'{m.group(0).strip()[:80]}' — the profile records an account {age} months old")
    for m in _OPENED_YEAR.finditer(narrative):
        year = int(m.group(1))
        if age is None or not ref_dates:
            unverified.append({"type": "account_opening", "text": m.group(0).strip()[:100], "why": "no account age or reference date to check the year against"})
            continue
        ref = max(ref_dates)
        possible = {(ref - timedelta(days=30.44 * (age + off))).year for off in (-1, 0, 1)}
        if year not in possible:
            by_type["profile_fact"].append(f"'{m.group(0).strip()[:80]}' — an account {age} months old at {ref.isoformat()} was opened in {'/'.join(str(y) for y in sorted(possible))}")
    for term in ("aadhaar", "aadhar", "passport", "driving licence", "driving license", "voter id",
                 "video kyc", "re-kyc", "nominee", "joint holder", "co-applicant", "guarantor"):
        if re.search(r"\b" + re.escape(term) + r"\b", narrative, re.I) and term not in (record_text or "").lower():
            by_type["profile_fact"].append(f"'{term}' is asserted but not in the customer profile / alert record")
    for m in re.finditer(r"\b(?:salaried|self-employed|business\s+owner|student|pensioner|retired|housewife|homemaker|unemployed)\b", narrative, re.I):
        if m.group(0).lower() not in (profile_text or "").lower():
            unverified.append({"type": "occupation", "text": m.group(0),
                               "why": "occupation term not in the customer profile"})

    # ── PERCENTAGES / MULTIPLES (soft) ───────────────────────────────────────
    ratios: set[float] = set()
    tc, td = sum(credits), sum(debits)
    flagged_d = sum(float(t.get("amount_inr") or 0) for t in transactions if t.get("type") == "DEBIT" and t.get("is_flagged"))
    for num, den in ((td, tc), (flagged_d, tc), (flagged_d, td), (tc, td)):
        if den:
            ratios.add(round(num / den * 100, 2))
    for t in transactions:
        for den in (tc, td):
            if den:
                ratios.add(round(float(t.get("amount_inr") or 0) / den * 100, 2))
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*%", narrative):
        pct = float(m.group(1))
        if not any(abs(pct - r) <= 0.6 for r in ratios) and m.group(0) not in record_text:
            unverified.append({"type": "percentage", "text": m.group(0),
                               "why": "not reproducible from transaction data"})
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(?:x|×|times)\b", narrative, re.I):
        mult = float(m.group(1))
        cands = []
        if profile["monthly_income"]:
            cands += [tc / profile["monthly_income"], td / profile["monthly_income"]]
        if not any(abs(mult - c) <= max(0.6, c * 0.06) for c in cands) and m.group(0) not in record_text:
            unverified.append({"type": "multiple", "text": m.group(0).strip(),
                               "why": "not reproducible from declared income and transaction data"})

    # ── THIRD-PARTY CHARACTERISATIONS (soft) ─────────────────────────────────
    rec_low = (record_text + " " + txn_text).lower()
    cands: list[str] = []
    for pat, tag in _ASSERTION_PATTERNS:
        term = re.sub(r"\W+", " ", tag.replace("-", " ")).split()[0]
        for m in re.finditer(pat, narrative, re.I):
            snippet = m.group(0).strip()
            if term in rec_low or snippet.lower() in rec_low:
                continue
            cands.append(snippet)
    for snippet in sorted(set(cands), key=len, reverse=True):
        low = snippet.lower()
        if any(low in kept["text"].lower() for kept in unverified if kept["type"] == "third_party_characterisation"):
            continue
        unverified.append({"type": "third_party_characterisation", "text": snippet[:100],
                           "why": "cannot be verified from the case record"})

    # ── ATTRIBUTION (soft): is each verified fact attached to the right party, direction, date, side and flag? ──
    from skills import attribution
    unverified.extend(attribution.check(narrative, transactions, extract_amounts, extract_dates))

    hard_failed = {k: v for k, v in by_type.items() if v}
    by_type_out = {k: v for k, v in by_type.items() if v}
    return {
        "passed": not hard_failed,
        "unsupported_claims_by_type": by_type_out,
        "unresolved_txn_ids": unresolved,
        "unverified_assertions": unverified,
        "verification_scope": {"verified": VERIFIED_CLASSES, "not_verified": NOT_VERIFIED, "not_checkable_now": not_checkable},
        "fact_coverage": {"amounts_checked": n_amounts, "txn_ids_checked": len(refs), "dates_checked": n_dates,
                          "counterparties_checked": len({t.get("counterparty") for t in transactions if t.get("counterparty")})},
        "evidence_refs_found": sum(1 for tid in known_ids if tid in narrative.upper()),
    }
