# Evidence

Records of the runs behind the numbers in the top-level README. All data is synthetic, and the author wrote the alerts, the validators and the labels, so these are counts over those cases and not accuracy in the field.

| Folder | What it holds |
|---|---|
| `fabrication-benchmark/` | The deterministic evidence gate on fabricated and faithful narratives (offline). `2026-10-05/` keeps the frozen baselines and first measurements; `2026-10-06/` is a re-run |
| `retrieval-gold/` | The regulatory lookup and its scope guard on labelled questions, including the holdouts and their baselines |
| `live-replay/` | A real model over the seeded alerts: the full runs, the retry, the held-out Gulf-remittance alerts, the three-model comparison (`MODEL_COMPARISON_2026-10-06.md`) and `2026-10-06/COMBINED.md` |
| `llm-checker/` | The validator against a model as the checker on 160 cases (`2026-10-06/COMPARISON.md`) |
| `heldout-gcc/` | The prediction, the first measurement and the frozen-rule hash for the three alerts written after the nexus rule was frozen |
| `governance/` | The opt-in column-masking probe, run in the isolated environment and then removed |
| `feed-load/` | The feed loader's write path, run live inside a rolled-back transaction |
| `cleanroom-2026-10-06/` | The live suites and the health report on the isolated environment after the redeploy: the first run (with its one stale-constant failure per role) and the full re-run after the correction |
| `public-sources/` | Notes on public documents the problem statement relies on (the FIU-IND annual report), with the page of every figure and how it was read. The documents themselves are not stored |
| `cleanroom-2026-10-02/` | One file: three real ledger rows that the offline hash check reads (`tests/test_dossier.py`) |
| `coco/` | The Cortex Code CLI protocol. No session is recorded |

## Read these first

- **Commit ids inside the records are from an earlier history.** Run summaries say, for example, "commit `e2021d8` + uncommitted changes". They name the working history as it was when each run happened. That history was later squashed into one commit, so those ids no longer resolve. The records are kept exactly as generated.
- **Some files are not kept.** The raw model replies (`raw_responses.json`) and the per-case `results.json` files of the validator-versus-model comparison were removed to keep the repository small. The summaries and the other results files carry the findings, and the replies the application ships for its "saved assessment" button are in `skills/saved_responses_data.py`.
- **Earlier deployment logs were removed.** What remains in `cleanroom-2026-10-02/` is the file the offline hash check needs.
