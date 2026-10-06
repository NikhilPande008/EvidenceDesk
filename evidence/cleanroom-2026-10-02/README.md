# evidence/cleanroom-2026-10-02 — logs from the clean-room run

Produced 2026-10-02 (03:57–04:22 UTC) by `scripts/deploy_snowflake.py --profile cleanroom`, `scripts/health_check.py`, `scripts/env_fingerprint.py` and the live suites. **Synthetic data only.** The Snowflake account, organisation, user name, e-mail, local paths and the app's URL id are scrubbed (`<org>`, `<account>`, `<user>`, `<repo>`, `<build>`, `<url_id>`); nothing in this folder is a credential. Each file is the unedited output of its command apart from that scrubbing. Narrative and interpretation: [EVIDENCE.md](../../EVIDENCE.md), Phase 12.

| File | Command | What it shows |
|---|---|---|
| `01_preflight.log` | `--apply --step preflight` | the clean-room namespace was **empty** (database, warehouse, three roles absent) |
| `02_bootstrap_roles_ownership.log` | `--step bootstrap --step roles --step ownership` | 4 + 9 statements ok; ownership: nothing to transfer |
| `03_ddl.log` | `--step ddl` | 4 DDL files (26 statements), incl. the Cortex Search service |
| `04_data.log` | `--step data` | corpus, alerts + transactions, semantic model, Search refresh |
| `05_grants_verify.log` | `--step grants --step verify` | 17 grants; RBAC proof `overall = PASS` (UPDATE / DELETE denied, secondary roles NONE) |
| `06_health_before_app.log` | `--step health` (before the app) | data plane HEALTHY; app UNAVAILABLE (does not exist yet) |
| `07_app.log` | `--step app` | hosted app **created by the app role**; temporary `CREATE STREAMLIT` grant revoked; post-condition |
| `08_health_after_app.log` | `--step health` | app HEALTHY: 13 / 13 code files byte-identical |
| `09_live_tests.log` | `--step test` | the live suites as the owner role (`19 passed, 1 skipped`) then the app role (`18 passed, 1 skipped, 1 deselected`) |
| `10_prod_verify.log` | `--apply --step verify` (**production**) | the same RBAC proof against production: `PASS` |
| `11_seed_cleanroom.log` | a scratch script (not in the repo) | 3 real `DEFERRED` decisions committed in the **clean room** through the real recorder; census 3 INTACT |
| `12_audit.log` | `--profile cleanroom --apply --step audit` | audit role / schema / table provisioned; 3 records exported; reconciliation `CONSISTENT`, chain valid |
| `13_deletion_sim.log` | live tests `reconciliation`, `simulated_deletion` | a simulated deletion from the 3 real rows is reported `DELETED_RECORD` (in memory; nothing deleted) |
| `14_cleanroom_health_deep.log`, `cleanroom_health_deep.json` | `health_check.py --deep` (clean room) | **13 healthy · 0 unavailable · 0 unverified** |
| `15_cleanroom_live_health_tests.log` | live health tests | the two health live tests + reconciliation + simulated deletion: 4 passed |
| `16_recovery_drills.log` | a scratch script (not in the repo) | Time Travel reads; a scratch clone at a timestamp equals the live ledger (same `HASH_AGG`) |
| `17_prod_health_deep.log`, `prod_health_deep.json` | `health_check.py --deep` (**production**, read-only) | 9 healthy · **1 unavailable** (hosted app one file behind) · 3 unverified |
| `prod_before.json`, `prod_after.json`, `18_prod_compare.log` | `env_fingerprint.py` | production's counts, `HASH_AGG` of every table, grants hash, app and Search metadata: **identical** before and after |
| `20_prod_redeploy.log` | `deploy_snowflake.py --apply --step app` (**production**, at the owner's instruction) | the redeploy: existing app owned by `FIU_APP_ROLE` → `--replace`, no temporary grant; post-condition *owner = FIU_APP_ROLE, CREATE privileges = none* |
| `21_prod_health_after_redeploy.log`, `prod_health_after_redeploy.json` | `health_check.py --deep` (**production**) | after the redeploy: hosted app **HEALTHY, 13 / 13 byte-identical** (bundle `d00ebbca…`); 10 healthy · 0 unavailable · 3 unverified |
| `prod_after_redeploy.json`, `22_prod_compare_after_redeploy.log` | `env_fingerprint.py` | production's data fingerprint after the redeploy vs the original `prod_before.json`: **IDENTICAL** |
| `19_cortex_latency_cleanroom.txt` | read-only `QUERY_HISTORY_BY_WAREHOUSE` | every Cortex Complete call of the run: seconds, model, outcome |
| `ledger-export-cleanroom.ndjson` | `audit_ledger.py export --out` | the hash-chained export of the 3 clean-room rows (decision ids and row hashes only) |
| `render_report.json` | the renderer's report | 86 files, 311 identifier substitutions, 0 production identifiers left, tree hash |

**Tree hashes.** The rendered copy was re-rendered as tooling and test files were edited during the session (`af098163…` for files 01–09 and 11, `b49a779a…` for 12–13, `e562efb5…` for 14–16 and `render_report.json`; 10, 17, 18 and the fingerprints ran from the repository itself). The **13 files of the deployed app never changed**: the health check reports the same bundle digest `44097f553ea800d9…` in every run.
