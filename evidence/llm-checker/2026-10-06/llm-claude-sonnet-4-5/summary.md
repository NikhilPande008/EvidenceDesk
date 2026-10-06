# Validator against a model as the checker: llm-claude-sonnet-4-5

- Run (UTC): 2026-10-06 03:11:10Z  ·  commit `0539151`  ·  cases: 160  ·  model: `claude-sonnet-4-5`, temperature 0, structured output, no fallback model, concurrency 4
- **Synthetic data; the author wrote the validator and the cases. Counts over these cases with Wilson intervals; not accuracy in the field.**

| Question | Deterministic validator | `claude-sonnet-4-5` as checker |
|---|---|---|
| Fabricated narratives caught (S2 + S3, unseen stress sets) | 65/80 (81.2%, 95% interval 71.3-88.3) | 80/80 (100.0%, 95% interval 95.4-100.0) |
|   of which S3 (written before round 2, never tuned on) | 30/38 (78.9%, 95% interval 63.6-88.9) | 38/38 (100.0%, 95% interval 90.8-100.0) |
| Mis-attributions caught (set Q: every fact real, wrongly bound) | 12/20 (60.0%, 95% interval 38.7-78.1) | 18/20 (90.0%, 95% interval 69.9-97.2) |
| Faithful narratives wrongly flagged | 0/40 (0.0%, 95% interval 0.0-8.8) | 15/40 (37.5%, 95% interval 24.2-53.0) |
| Correct statements wrongly flagged (set R) | 0/20 (0.0%, 95% interval 0.0-16.1) | 5/20 (25.0%, 95% interval 11.2-46.9) |

- Model seconds per call: median 14.0, max 18.4 (concurrency 4); median tokens per call 1522; unusable replies 0.
- The validator takes microseconds and no tokens.
- Repeatability at temperature 0: 23 of 24 repeated cases (95.8%) gave the same flag on all three asks.
