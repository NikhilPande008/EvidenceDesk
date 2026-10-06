"""
Scope and relevance guard for free-text regulatory questions.

The corpus covers ONE perimeter: India, PMLA 2002, FIU-IND and RBI guidance for banks and financial institutions.
Cortex Search always returns its top-k, so without a guard a question about another regime gets five Indian rules back
labelled PROVEN. This module decides, deterministically and before any result is shown, whether the corpus can answer.

Two checks, both pure (no database, model, network or clock):

  screen_scope(question)            BEFORE the search. Names a jurisdiction, regime or sector the corpus does not cover
                                    (UAE goAML, FinCEN, VASPs, SEBI-only entities ...) and returns the redirect.
  support_check(question, rules)    AFTER the search. The question's distinctive words must actually appear in what came
                                    back; a result set that shares almost nothing with the question is not an answer.

Either one failing means: no rules are shown, `legal_conclusion_permitted` is False, and the officer is told to route
the question to the parent entity's compliance function. A guard never *adds* a rule, so it cannot make an answer
less safe; it can only withhold one.

Limits (stated, not hidden): the out-of-perimeter lists are finite, and the support check is lexical. A question about
an unlisted regime that happens to reuse Indian vocabulary can still pass; the gold query set records those misses
as known gaps instead of hiding them (tests/fixtures/regulatory_gold_queries.json).
"""

from __future__ import annotations

import re

SCOPE_IN = "IN_SCOPE"
SCOPE_OUT_OF_PERIMETER = "OUT_OF_PERIMETER"
SCOPE_WEAK_MATCH = "WEAK_MATCH"

REASON_JURISDICTION = "OUT_OF_JURISDICTION"
REASON_REGIME = "OUT_OF_REGIME"
REASON_ENTITY_TYPE = "OUT_OF_ENTITY_TYPE"
REASON_WEAK = "WEAK_MATCH"

CORPUS_PERIMETER = {
    "jurisdiction": "India",
    "statute": "PMLA 2002",
    "regulators": ("FIU-IND", "RBI"),
    "entity_types": ("banking companies", "financial institutions"),
}

# Below this share of a question's distinctive words found in the returned rules, the result set is not an answer.
MIN_COVERAGE = 0.5
# A question that names an all-caps acronym the returned rules never mention (SAR, COAF, FINTRAC) is about something the
# corpus does not know; with only moderate word coverage that is enough to abstain.
MIN_COVERAGE_WITH_UNKNOWN_ACRONYM = 0.7
# Cortex Search returns a cosine similarity for every hit. On the gold query set (tests/fixtures/regulatory_gold_queries.json,
# 53 queries, scored live) every answerable question's top hit scored 0.448 or higher, while off-topic questions
# scored 0.32-0.41. The floor sits just below the lowest answerable score of the 43 calibration queries; the 10-query
# holdout (H01-H10) was not used to set it. Recalibrate with scripts/eval_retrieval_gold.py whenever the corpus or the search
# service's embedding model changes. Foreign-regime questions that reuse Indian STR vocabulary score HIGH (0.5-0.65), so
# this floor cannot catch them; screen_scope and support_check exist for those.
MIN_COSINE = 0.42
_ACRONYM_TOKEN = re.compile(r"\b[A-Z][A-Z0-9]{2,5}\b")

_CS = 0
_CI = re.IGNORECASE


def _p(pattern: str, flags: int = _CI) -> re.Pattern:
    return re.compile(pattern, flags)


# STRONG signals: a named foreign regime, regulator or platform, or an entity type the corpus excludes
# (domain/corpus/rules: regulatory_perimeter.excludes). They apply even when the question also names PMLA, because
# "what is the UAE equivalent of a PMLA STR" is still a question the corpus cannot answer.
# (pattern, label shown to the officer, reason). Labels are constants: the officer's own words are never echoed back.
_STRONG: tuple[tuple[re.Pattern, str, str], ...] = (
    (_p(r"\b(goaml|cbuae|difc|adgm|federal decree|decree[- ]law)\b"), "the UAE", REASON_JURISDICTION),
    (_p(r"\b(sama)\b"), "Saudi Arabia", REASON_JURISDICTION),
    (_p(r"\b(qfiu|qfcra)\b"), "the Gulf states", REASON_JURISDICTION),
    (_p(r"\b(sanctions? screening|sdn list|un security council list)\b"), "sanctions screening", REASON_REGIME),
    (_p(r"\b(fincen|bank secrecy act|patriot act|ofac)\b"), "the United States", REASON_JURISDICTION),
    (_p(r"\b(money laundering regulations 2017|proceeds of crime act 2002|national crime agency)\b"), "the United Kingdom", REASON_JURISDICTION),
    (_p(r"\b(hkma|austrac|finma|bafin|amld[0-9]*|amla)\b"), "a jurisdiction outside India", REASON_JURISDICTION),
    # A foreign financial-intelligence unit or its portal (holdout 2: JFIU, NFIU, MROS). Names only; a place on its own stays a geography.
    (_p(r"\b(jfiu|nfiu|mros|fintrac|tracfin|coaf|jafic|amlc|kofiu|fiu-nl|goaml)\b"), "a jurisdiction outside India", REASON_JURISDICTION),
    (_p(r"\b(vasps?|virtual (digital )?assets?|vdas?|crypto\w*|bitcoin|stablecoins?|nfts?|defi)\b"), "virtual asset service providers", REASON_ENTITY_TYPE),
    (_p(r"\b(sebi|irdai|pfrda|stock ?brokers?|mutual funds?|insurers?|insurance compan\w+|depository participants?)\b"), "SEBI, IRDAI or PFRDA regulated entities", REASON_ENTITY_TYPE),
    (_p(r"\b(payment aggregators?|casinos?|real estate agents?)\b"), "entities outside the bank and financial-institution scope of this corpus", REASON_ENTITY_TYPE),
    (_p(r"\b(gdpr|sox|sarbanes|basel iii|mifid)\b"), "a regime outside AML reporting", REASON_REGIME),
)

# AMBIGUOUS signals: a foreign place or short acronym is a REGIME question only when it sits beside a regulatory-intent
# word ("what are the STR requirements in the UAE"), and only when the question names no Indian instrument. A place on
# its own is a transaction geography ("does the STR need to say the beneficiary is in Dubai") and stays in scope.
_INDIA_MARKERS = _p(r"\b(india\w*|pmla|fiu-?ind|rbi|finnet|fingate)\b")
_ACRONYMS = _p(r"\b(FCA|NCA|MAS|SAR|SARs|UK|USA|US|EU)\b", _CS)

_PLACES = (
    "uae", "emirates", "emirati", "dubai", "abu dhabi", "saudi", "riyadh", "qatar", "bahrain", "kuwait", "oman", "gulf",
    "united kingdom", "united states", "european union", "britain", "british", "american",
    "afghanistan", "argentina", "australia", "australian", "austria", "bangladesh", "belgium", "brazil", "brazilian", "canada", "canadian",
    "chile", "china", "chinese", "colombia", "denmark", "egypt", "finland", "france", "french", "germany", "german", "ghana", "greece",
    "hong kong", "indonesia", "indonesian", "iran", "iranian", "iraq", "ireland", "israel", "italy", "italian", "japan", "japanese", "kenya",
    "korea", "korean", "luxembourg", "macau", "malaysia", "malaysian", "mauritius", "mexico", "mexican", "myanmar", "nepal", "netherlands",
    "dutch", "new zealand", "nigeria", "nigerian", "norway", "pakistan", "pakistani", "peru", "philippines", "poland", "portugal",
    "russia", "russian", "singapore", "south africa", "spain", "spanish", "sri lanka", "sweden", "switzerland", "swiss", "taiwan",
    "thailand", "turkey", "turkish", "ukraine", "vietnam", "zimbabwe",
)
_PLACE_RE = _p(r"\b(" + "|".join(sorted((re.escape(c) for c in _PLACES), key=len, reverse=True)) + r")\b")
# Holdout 2 showed the cue list above is too narrow: "What is the deadline to file a suspicious activity report in Germany?" asks for another
# regime's requirement without using any of its words. A foreign place beside a REGULATORY-INTENT word (file, report, deadline, threshold, keep,
# penalty, must ...) is also a regime question, unless the place is an attribute of a transaction the officer is describing: a remitter in Dubai, a
# beneficiary in Singapore, funds received from Oman. Those are what an Indian STR must say about a counterparty, and stay in scope.
_REG_INTENT = _p(r"\b(file|files|filing|filed|report|reports|reporting|reported|submit|submits|submission|deadline|deadlines|threshold|thresholds|"
                 r"retain|retention|keep|kept|penalt\w+|fines?|triggers?|agency|receives?|have to|has to|must|should|duty|duties|covered)\b")
_TXN_GEO = _p(r"\b(remitter|remitters|beneficiary|beneficiaries|sender|senders|recipient|recipients|payee|payer|counterpart\w*|"
              r"(?:our|the|a|an|his|her|their) (?:customer|client)(?! due diligence)|account holder|"
              r"remittances?|funds|payments?|wires?|transfers?|received|sent|credited|debited|transferred|wired|remitted)\b")
_REGIME_CUE = _p(r"\b(law|laws|act|decree|regulation|regulations|regulator|regulatory|rules|requirements?|obligations?|"
                 r"framework|fiu|authority|central bank|guidelines?|statute|legislation)\b")

# Words that carry no subject matter. Everything else in a question must be found in the returned rules.
_GENERIC = frozenset("""
a about above after again against all also am an and any are aren as at be because been before being below between both
but by can could did do does doing done down during each either else every few for from further get give given had has
have having he her here hers him his how i if in into is it its just like make many may me might more most must my no nor
not now of off on once only or other our out over own per same shall she should so some such than that the their them
then there these they this those through to too under until up upon us use used using very was we were what when where
which while who whom why will with within without would you your
requirement requirements obligation obligations rule rules regulation regulations regulatory law laws legal act acts
provision provisions section sections apply applies applicable applicability need needs needed required require requires
explain tell describe list state say mean means meaning definition define difference steps step process procedure
india indian entity entities reporting guidance guideline guidelines compliance comply complying
""".split())

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-]*")


def _stem(word: str) -> str:
    w = word.lower().strip("-")
    for suffix in ("ations", "ation", "ings", "ing", "ies", "es", "ed", "s"):
        if len(w) > len(suffix) + 3 and w.endswith(suffix):
            return w[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return w


def distinctive_terms(question: str) -> list[str]:
    """Subject-matter words of a question, lower-cased and lightly stemmed, in order, de-duplicated."""
    seen: list[str] = []
    for tok in _TOKEN.findall(question or ""):
        low = tok.lower()
        if low in _GENERIC or len(low) < 3 or low.isdigit():
            continue
        stem = _stem(low)
        if stem not in seen:
            seen.append(stem)
    return seen


def _out(label: str, reason: str) -> dict:
    return {"in_scope": False, "status": SCOPE_OUT_OF_PERIMETER, "reason_code": reason, "label": label,
            "redirect": redirect_for(reason)}


def screen_scope(question: str) -> dict:
    """Is the question inside the corpus perimeter? {in_scope, status, reason_code, label, redirect}."""
    text = question or ""
    for pattern, label, reason in _STRONG:
        if pattern.search(text):
            return _out(label, reason)
    if not _INDIA_MARKERS.search(text) and (_ACRONYMS.search(text) or _PLACE_RE.search(text)):
        if _REGIME_CUE.search(text):
            return _out(_place_label(text), REASON_JURISDICTION)
        if _REG_INTENT.search(text) and not _TXN_GEO.search(text):
            return _out(_place_label(text), REASON_JURISDICTION)
    return {"in_scope": True, "status": SCOPE_IN, "reason_code": None, "label": None, "redirect": None}


def _place_label(text: str) -> str:
    """A fixed label for the place a question is about: UAE and Saudi are named because the redirect differs little but the
    officer should see that the question was understood; everything else is 'a jurisdiction outside India'."""
    low = text.lower()
    if re.search(r"\b(uae|emirates|emirati|dubai|abu dhabi)\b", low):
        return "the UAE"
    if re.search(r"\b(saudi|riyadh)\b", low):
        return "Saudi Arabia"
    if re.search(r"\b(qatar|bahrain|kuwait|oman|gulf)\b", low):
        return "the Gulf states"
    return "a jurisdiction outside India"


def redirect_for(reason: str) -> str:
    if reason == REASON_ENTITY_TYPE:
        return "Ask the guidance owner for that entity type, or the compliance function that covers that business line."
    if reason == REASON_REGIME:
        return "Ask the compliance function that owns that regime."
    return "Route it to the parent entity's compliance function (MLRO) or the local regulator's published guidance."


def _rule_text(rule: dict) -> str:
    return " ".join(str(rule.get(k) or "") for k in ("rule_id", "rule_text", "my_synthesis", "category", "source_document"))


def support_check(question: str, rules: list[dict]) -> dict:
    """Do the returned rules actually talk about what was asked?

    coverage = share of the question's distinctive words that appear (exact stem, or prefix for words of five letters
    or more) anywhere in the returned rules. A question with no distinctive words (for example "what is it?") cannot
    be supported by any result."""
    terms = distinctive_terms(question)
    if _PLACE_RE.search(question or "") and _TXN_GEO.search(question or ""):
        places = {_stem(w.lower()) for m in _PLACE_RE.finditer(question or "") for w in _TOKEN.findall(m.group(0))}
        terms = [t for t in terms if t not in places]          # "the remitter is in Dubai": Dubai describes the transaction, not the question's subject
    if not terms:
        return {"supported": False, "coverage": 0.0, "terms": [], "uncovered": [], "unknown_acronyms": [],
                "reason_code": REASON_WEAK, "note": "the question has no subject-matter words"}
    haystack = " ".join(_rule_text(r) for r in rules).lower()
    words = {_stem(w) for w in _TOKEN.findall(haystack)}

    def found(term: str) -> bool:
        # Short terms ("str", "ctr", "kyc") must match exactly: as a prefix, "str" would "find" "structure".
        if term in words:
            return True
        if len(term) < 5:
            return False
        return any((w.startswith(term) or term.startswith(w)) and len(w) >= 5 for w in words)

    uncovered = [t for t in terms if not found(t)]
    coverage = round((len(terms) - len(uncovered)) / len(terms), 3)
    parts = words | {p for w in words for p in w.split("-") if p}
    unknown_acronyms: list[str] = []
    if not (question or "").isupper():                      # an all-caps question has no acronyms to single out
        unknown_acronyms = [a for a in dict.fromkeys(_ACRONYM_TOKEN.findall(question or "")) if a.lower() not in parts]
    supported = (bool(rules) and coverage >= MIN_COVERAGE
                 and not (unknown_acronyms and coverage < MIN_COVERAGE_WITH_UNKNOWN_ACRONYM))
    note = ""
    if not supported:
        note = ("the question names terms the corpus never mentions" if unknown_acronyms and coverage >= MIN_COVERAGE
                else "the returned rules share too few of the question's words")
    return {"supported": supported, "coverage": coverage, "terms": terms, "uncovered": uncovered,
            "unknown_acronyms": unknown_acronyms, "reason_code": None if supported else REASON_WEAK, "note": note}


def semantic_check(cosine: float | None) -> dict:
    """Is the best hit semantically close to the question? Unchecked (and therefore passing) when the search returned no
    score, as on the keyword fallback: the lexical check still applies there."""
    if cosine is None:
        return {"supported": True, "checked": False, "cosine": None, "floor": MIN_COSINE}
    value = round(float(cosine), 3)
    return {"supported": value >= MIN_COSINE, "checked": True, "cosine": value, "floor": MIN_COSINE}


def abstention(scope: dict) -> dict:
    """The `scope` block attached to a lookup result when the corpus cannot answer."""
    return {"status": scope["status"], "reason_code": scope["reason_code"], "label": scope.get("label"),
            "redirect": scope.get("redirect"), "perimeter": dict(CORPUS_PERIMETER)}
