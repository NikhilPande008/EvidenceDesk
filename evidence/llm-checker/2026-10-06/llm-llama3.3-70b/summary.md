# Validator against a model as the checker: llm-llama3.3-70b

- Run (UTC): 2026-10-06 02:57:47Z  ·  commit `dab155d`  ·  cases: 160  ·  model: `llama3.3-70b`, temperature 0, structured output, no fallback model, concurrency 4
- **Synthetic data; the author wrote the validator and the cases. Counts over these cases with Wilson intervals; not accuracy in the field.**

| Question | Deterministic validator | `llama3.3-70b` as checker |
|---|---|---|
| Fabricated narratives caught (S2 + S3, unseen stress sets) | 65/80 (81.2%, 95% interval 71.3-88.3) | 76/80 (95.0%, 95% interval 87.8-98.0) |
|   of which S3 (written before round 2, never tuned on) | 30/38 (78.9%, 95% interval 63.6-88.9) | 37/38 (97.4%, 95% interval 86.5-99.5) |
| Mis-attributions caught (set Q: every fact real, wrongly bound) | 12/20 (60.0%, 95% interval 38.7-78.1) | 19/20 (95.0%, 95% interval 76.4-99.1) |
| Faithful narratives wrongly flagged | 0/40 (0.0%, 95% interval 0.0-8.8) | 39/40 (97.5%, 95% interval 87.1-99.6) |
| Correct statements wrongly flagged (set R) | 0/20 (0.0%, 95% interval 0.0-16.1) | 14/20 (70.0%, 95% interval 48.1-85.5) |

- Model seconds per call: median 22.3, max 121.7 (concurrency 4); median tokens per call 811; unusable replies 5.
- The validator takes microseconds and no tokens.
- Repeatability at temperature 0: 24 of 24 repeated cases (100.0%) gave the same flag on all three asks.
