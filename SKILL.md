# CoCo Skills — FIU-IND AML Decision-Defensibility Copilot
**Version:** 1.0
**Hackathon:** Snowflake CoCo CLI Hackathon, GCC Edition. Track: Risk, Fraud and Regulatory Intelligence Copilot

---

## What is a CoCo Skill?

In this project a skill is a named, reusable Python method on `CoPilotSkills`
(`skills/core.py`, registered in `SKILLS`). Each wraps one Snowflake capability
(Cortex Search, Cortex Complete, Cortex Analyst, or plain SQL) with a defined input
contract, output contract and deterministic checks around it. The fixed pipeline is
three Cortex Complete calls in a set order; **Cortex Agents are not used**, and these
Python skills are not Cortex Code CLI skill files. The Cortex Code CLI skill files are in
`.cortex/skills/` (they describe how to operate this repository; see `evidence/coco/README.md`: no CLI session is recorded). The `alert_disposition_recorder` skill
re-derives evidence quality, the decision gate and the regulatory basis at write time
rather than trusting what the UI passed in.

---

## Registered Skills

### 1. `regulatory_lookup`

| Field | Value |
|---|---|
| **Purpose** | Given a natural-language regulatory question, return the relevant corpus entries with source citations and evidence levels |
| **Cortex capability** | Cortex Search (CORPUS_SEARCH service) |
| **Input** | `question: str` — e.g. "What is the STR filing deadline?" |
| **Output** | JSON: `{rule_id, rule_text, evidence_level, source_document, source_url, snapshot_date}[]` |
| **Constraint** | Never returns `NEEDS-VERIFICATION` entries. Always includes `evidence_level` in output. Abstains (no rules, no legal conclusion) when the question is outside the India perimeter, or when the best hits are weakly related to it (`skills/scope_guard.py`; measured in `evidence/retrieval-gold/`). |
| **CoCo phase evidence** | Development (skill definition), Execution (live query against CORPUS_SEARCH) |

**System prompt excerpt:**
> "You are a regulatory reference assistant for Indian AML compliance. When answering,
> cite only rules with evidence_level PROVEN or ASSUMED. Always include the source document
> and snapshot date. Never present NEEDS-VERIFICATION rules as authoritative."

---

### 2. `suspicion_evaluator`

| Field | Value |
|---|---|
| **Purpose** | Evaluate a given alert/case against the 11 PO suspicion factors (POE-002 to POE-012) |
| **Cortex capability** | Cortex Complete (`SNOWFLAKE.CORTEX.COMPLETE`); strict JSON validation and fact grounding run deterministically on the result |
| **Input** | `case_context: {customer_kyc, transactions[], signal_tags[]}` |
| **Output** | JSON: `{factor_id, factor_name, assessment: triggered|clear|insufficient_data, evidence}[]` |
| **Constraint** | Must assess all 11 factors; must flag factors where data is insufficient. |
| **CoCo phase evidence** | Development (tool definition), Execution (demo case walkthrough) |

**System prompt excerpt:**
> "Evaluate this AML alert against each of the 11 PO evaluation factors from
> FIU-IND Reporting Format Guide v2.2 (corpus entries POE-002 to POE-012).
> For each factor, state: triggered | clear | insufficient_data, and cite the
> specific transaction or profile detail that supports your assessment."

---

### 3. `ground_of_suspicion_writer`

| Field | Value |
|---|---|
| **Purpose** | Draft a non-templated, specific Part (c) Ground of Suspicion narrative for an STR |
| **Cortex capability** | Cortex Complete (uses the `suspicion_evaluator` output); the draft is checked by the deterministic evidence gate |
| **Input** | `case_context: {...}`, `poe_assessment: [...]` (from `suspicion_evaluator`) |
| **Output** | `narrative: str` — specific to this customer, citing transactions, POE factors, and RFIs triggered |
| **Constraint** | Output is validated against the 10-point templated-narrative checklist (DOMAIN.md §7) before returning. Must include: specific transactions, profile contradiction, RFIs triggered, why alternatives were rejected. |
| **CoCo phase evidence** | Development (prompt + validation logic), Execution + Test (checklist pass/fail) |

**Quality gate (10-point templated-narrative checklist):**
All 10 items from DOMAIN.md §7 must pass. If any item fails, the skill returns
the narrative with a `quality_failures: [...]` field and does not mark it READY.

---

### 4. `alert_disposition_recorder`

| Field | Value |
|---|---|
| **Purpose** | Record a FILE or NOT-FILE decision in the append-only DECISION_LEDGER |
| **Cortex capability** | Snowflake table write (DECISION_LEDGER) with a SHA-256 row hash; the decision gate is re-run at write time |
| **Input** | `alert_id, customer_ref, disposition, rationale_text, rules_cited[], rfi_triggers[], poe_assessment[]` |
| **Output** | `decision_id: str` — the UUID of the created DECISION_LEDGER row |
| **Constraint** | Append-only — no UPDATE or DELETE. Rationale text is mandatory for both FILE and NOT-FILE dispositions. SLA remaining is computed and stored. |
| **CoCo phase evidence** | Development (table DDL), Execution (live write), Test (the application role's UPDATE and DELETE are denied; the ledger is append-only for that role, not immutable) |

---

### 5. `str_quality_checker`

| Field | Value |
|---|---|
| **Purpose** | Validate a draft Ground of Suspicion against the 10-point FIU-IND templated-narrative checklist |
| **Cortex capability** | Cortex Complete plus the deterministic evidence gate (a model failure fails closed) |
| **Input** | `narrative: str`, `case_context: {...}` |
| **Output** | `{passed: bool, checklist: [{item, pass: bool, note}], quality_score: int/10}` |
| **Constraint** | A score < 8/10 triggers a REVISE recommendation before filing. |
| **CoCo phase evidence** | Test (checklist scoring against gold-standard scenarios) |

---

## Skill composition — happy path

```
Alert arrives
    │
    ▼
regulatory_lookup("What rules apply to this transaction type?")
    │ returns: applicable corpus rules
    ▼
suspicion_evaluator(case_context)
    │ returns: POE factor assessment
    ▼
ground_of_suspicion_writer(case_context, poe_assessment)
    │ returns: draft narrative + quality_failures[]
    ▼
str_quality_checker(narrative, case_context)
    │ if passed:
    ▼
alert_disposition_recorder(FILE, narrative, rules_cited, ...)
    │ returns: decision_id → DECISION_LEDGER row
    ▼
FINGate 2.0 filing (manual step — PO reviews and submits)
```

---

## CoCo evidence capture — phase map

This table says where each phase's project artifacts live. It is a map of this repository, not a record of Cortex Code CLI sessions: none is recorded (`evidence/coco/README.md`).

| Phase | What to capture | Location |
|---|---|---|
| **Plan** | Corpus schema design, stack architecture, skill contracts | SCHEMA.md, SNOWFLAKE-FIT.md, this file |
| **Development** | YAML rule files, SQL DDL, Cortex Search service CREATE, skill system prompts | domain/corpus/rules/, export/ddl/, skill prompts/ |
| **Execution** | Populated REGULATORY_CORPUS table, working Cortex Search queries, demo walkthrough of alert → disposition | Demo screenshots, SQL outputs, `evidence/cleanroom-2026-10-02/`, `evidence/retrieval-gold/` |
| **Test** | Cortex Search returns cited rules; NEEDS-VERIFICATION excluded; out-of-scope questions abstain; quality-checker scores; DECISION_LEDGER append-only for the application role (the owner role can still delete rows); PO factor coverage | tests/corpus_retrieval_tests.sql, tests/test_scope_guard.py, `scripts/eval_retrieval_gold.py`, test scenarios |
