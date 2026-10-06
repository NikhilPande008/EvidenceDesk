"""
CoCo Skills — FIU-IND AML Decision-Defensibility Copilot

`skills.core.SKILLS` is the single registry of what this package exposes (tests/test_docs_consistency.py
keeps README/EVIDENCE/DEPLOY in step with it):

  Cortex-backed skills (LLM / Search)
    regulatory_lookup           Cortex Search over CORPUS_SEARCH, governance applied (PROVEN-first, superseded handled)
    suspicion_evaluator         11-factor assessment via Cortex Complete — strict, fail-closed parsing + grounding
    ground_of_suspicion_writer  Part (c) draft via Cortex Complete — READY only if every gate passes
    str_quality_checker         10-point heuristic via Cortex Complete + deterministic evidence gate — fail-closed
  Database skill
    alert_disposition_recorder  append-only DECISION_LEDGER INSERT with ROW_HASH + provenance; gates enforced at write
  Deterministic controls (no LLM)
    validate_gos_evidence, evidence_sufficiency_summary, challenge_disposition, screen_request
  Analytics client
    CorpusAnalyst               NL→SQL over ALERTS_CURRENT + DECISION_LEDGER + TRANSACTIONS via Cortex Analyst REST

Usage (Streamlit-in-Snowflake):   CoPilotSkills(get_active_session())
Usage (local connector):          CoPilotSkills(skills.connection.connect_from_env())
"""

from skills.core import CoPilotSkills, CorpusAnalyst, SKILLS

__all__ = ["CoPilotSkills", "CorpusAnalyst", "SKILLS"]
