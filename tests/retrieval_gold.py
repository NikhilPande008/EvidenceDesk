"""
Gold-query evaluation for the regulatory reference: loader, an offline stand-in for Cortex Search, and scoring.

Used by tests/test_scope_guard.py (offline) and scripts/eval_retrieval_gold.py (live, needs Snowflake).

The offline stand-in ranks the PROVEN and ASSUMED YAML rules by IDF-weighted word overlap and ALWAYS returns the top
five, even when nothing overlaps, because that is how Cortex Search behaves and it is exactly the case the guard exists
for. It is a proxy for the guard's behaviour, not a measurement of Cortex Search; the live runner measures that.
"""

from __future__ import annotations

import glob
import json
import math
from pathlib import Path

import yaml

from skills import scope_guard as SG

ROOT = Path(__file__).resolve().parent.parent
GOLD_PATH = ROOT / "tests" / "fixtures" / "regulatory_gold_queries.json"


def load_gold() -> list[dict]:
    return json.loads(GOLD_PATH.read_text())["queries"]


def yaml_rules() -> list[dict]:
    """The searchable corpus (PROVEN + ASSUMED) in the shape lookup results carry."""
    out = []
    for f in sorted(glob.glob(str(ROOT / "domain/corpus/rules/*.yaml"))):
        for r in yaml.safe_load(open(f))["rules"]:
            if r["evidence_level"] in ("PROVEN", "ASSUMED"):
                out.append({"rule_id": r["id"], "rule_text": " ".join(str(r["rule"]).split()), "my_synthesis": " ".join(str(r.get("my_synthesis") or "").split()),
                            "category": r.get("category"), "source_document": (r.get("primary_source") or {}).get("document"),
                            "evidence_level": r["evidence_level"]})
    return out


class StubSearch:
    """IDF-weighted overlap over the YAML corpus. Always returns `limit` rules."""

    def __init__(self, rules: list[dict] | None = None):
        self.rules = rules or yaml_rules()
        self.terms = [set(SG.distinctive_terms(SG._rule_text(r))) for r in self.rules]
        df: dict[str, int] = {}
        for ts in self.terms:
            for t in ts:
                df[t] = df.get(t, 0) + 1
        n = len(self.rules)
        self.idf = {t: math.log((n + 1) / (c + 0.5)) for t, c in df.items()}

    def top(self, question: str, limit: int = 5) -> list[dict]:
        q = SG.distinctive_terms(question)
        scored = []
        for i, (r, ts) in enumerate(zip(self.rules, self.terms)):
            scored.append((-sum(self.idf.get(t, 0.0) for t in q if t in ts), i, r))
        return [r for _, _, r in sorted(scored)[:limit]]


def decide_offline(question: str, search: StubSearch) -> dict:
    """The guard's decision for one question: the same two checks regulatory_lookup_with_basis applies."""
    perimeter = SG.screen_scope(question)
    if not perimeter["in_scope"]:
        return {"decision": "abstain", "reason": perimeter["reason_code"], "stage": "screen", "rules": []}
    rules = search.top(question)
    support = SG.support_check(question, rules)
    if not support["supported"]:
        return {"decision": "abstain", "reason": SG.REASON_WEAK, "stage": "support", "coverage": support["coverage"],
                "uncovered": support["uncovered"], "rules": []}
    return {"decision": "answer", "reason": None, "stage": "answered", "coverage": support["coverage"], "rules": [r["rule_id"] for r in rules]}


def score(gold: list[dict], decisions: dict[str, dict]) -> dict:
    """Metrics over the gold set. `decisions` maps query id to {decision, reason, rules}. Known gaps are reported apart."""
    answer = [q for q in gold if q["expect"] == "answer"]
    abstain = [q for q in gold if q["expect"] == "abstain" and not q.get("known_gap")]
    gaps = [q for q in gold if q.get("known_gap")]
    answered_ok = [q["id"] for q in answer if decisions[q["id"]]["decision"] == "answer"]
    abstained_ok = [q["id"] for q in abstain if decisions[q["id"]]["decision"] == "abstain"]
    reason_ok = [q["id"] for q in abstain if decisions[q["id"]].get("reason") == q.get("reason")]
    gaps_caught = [q["id"] for q in gaps if decisions[q["id"]]["decision"] == "abstain"]
    hits = [q["id"] for q in answer if set(q.get("expected_rules") or ()) & set(decisions[q["id"]].get("rules") or ())]
    pct = lambda a, b: round(100 * len(a) / b, 1) if b else None  # noqa: E731
    return {
        "queries": len(gold),
        "in_scope": len(answer), "in_scope_answered": len(answered_ok), "in_scope_answer_rate_pct": pct(answered_ok, len(answer)),
        "false_abstentions": [q["id"] for q in answer if q["id"] not in answered_ok],
        "out_of_scope": len(abstain), "out_of_scope_abstained": len(abstained_ok), "out_of_scope_abstain_rate_pct": pct(abstained_ok, len(abstain)),
        "wrongly_answered": [q["id"] for q in abstain if q["id"] not in abstained_ok],
        "abstain_reason_matches": len(reason_ok),
        "known_gaps": len(gaps), "known_gaps_caught": gaps_caught,
        "expected_rule_hit_at_5": len(hits), "expected_rule_hit_rate_pct": pct(hits, len(answer)),
    }
