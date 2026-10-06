---
name: evidencedesk-measure
description: Run EvidenceDesk's offline tests and measurement harnesses and report the numbers with their limits - counts and intervals, first measurement versus regression record, which model answered.
---

# Measure, and say what the number is

## Offline gate (no Snowflake, no model)

```
FIU_SKIP_DOTENV=1 python3 -m pytest tests -q
```

Most test files under `tests/` also run on their own, without pytest (`python tests/<name>.py`); those standalone runs are part of the gate too. Report passed, failed and skipped counts as printed. A skipped test is not a pass.

## Harnesses (need the clean-room environment and a role that can call Cortex)

| What | Command | Notes |
|---|---|---|
| Fabrication benchmark | `python3 scripts/eval_fabrication_benchmark.py --write` | Deterministic validator over fabricated and faithful narratives |
| Retrieval gold set | `python3 scripts/eval_retrieval_gold.py --write [--label <name>]` | Cortex Search against labelled regulatory questions |
| Live replay | `python3 scripts/eval_live_replay.py --write [--label <name>] [--alerts A,B] [--no-draft]` | A real model over the seeded alerts; billed |
| Validator vs a model as checker | `python3 scripts/eval_llm_checker.py --model <m> --label <name> --write` | Billed; `--offline` runs the validator alone |

## How to report a result

- Give counts, never a bare percentage, and the interval where the harness prints one. Say how many cases and who wrote them.
- Name the model that answered. If a fallback model answered any call, the run is not a clean one-model result; say which alerts.
- **First measurement or regression record.** A rule written after seeing a case cannot be tested on that case. Label a result "first measurement" only if the
  rule was frozen before the cases existed. If a rule is changed in response to a result, that result becomes a regression record and a new held-out set is needed.
- Do not edit a rule, a label or a threshold in response to a held-out miss and then re-report the same cases as held out.
- Nothing in these harnesses records a decision to the ledger. If a command would, stop.
- Synthetic data, an author-written validator and author-written labels mean none of this is accuracy on real cases. Say so once, at the top.
