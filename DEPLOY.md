# Deployment Guide

This repository is a prototype. Deploy only to a non-production Snowflake account or isolated namespace that you are authorised to use. Never use a deployment command against a customer-data environment without approved change control.

## Prerequisites

- Python supported by `requirements.txt`
- Snowflake CLI and an authorised Snowflake connection
- A Snowflake role with only the privileges approved for the target environment
- Credentials supplied through `.env`, environment variables, or a secrets manager; never Git

Install dependencies and validate the checkout before deployment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -c constraints.txt
python -m py_compile streamlit_app.py skills/*.py scripts/*.py tests/*.py
python -m pytest tests -q -m "not live" -p no:cacheprovider
```

`-m "not live"` keeps the run offline. With credentials in `.env`, a plain `pytest tests` also runs the live tests against whichever database `.env` names.

## Deployment approach

Review the plan produced by `scripts/deploy_snowflake.py` before authorising any change. Use its clean-room/profile mechanism for demonstrations and testing. The deployment scripts, role SQL, and `snowflake.yml` are executable artifacts; they are the source of truth for object names, grants, and uploaded modules.

Do not publish connection names, account identifiers, role memberships, query results, deployment logs, screenshots, or health-check output in a public repository.

## Updating a deployment that already exists

A fresh deployment needs none of this. An account deployed before the answer key was split out of `ALERTS` and before `ALERTS.SUSPICION_FORMED_AT` existed must be migrated in this order, as `FIU_ADMIN_ROLE` (or the owner role of the target environment). The order matters; a wrong order stops the schema step or breaks the queue.

1. `deploy/09_alert_feed_suspicion_time.sql`: adds the column. It must come first, because `alerts.sql` comments on that column and the schema step stops without it.
2. `deploy/08_move_gold_labels.sql`, steps 1 and 2: creates `ALERT_GOLD_LABELS` and copies the labels. Leave step 3 commented out for now.
3. `python scripts/deploy_snowflake.py --apply --step ddl`: recreates the tables and the views, so `ALERTS_CURRENT` stops selecting `GOLD_DISPOSITION`.
4. `SNOWFLAKE_ROLE=FIU_ADMIN_ROLE python scripts/upload_semantic_model.py`: the role is needed because `.env` normally names the app role, which lacks the privilege to write to the stage.
5. `deploy/08_move_gold_labels.sql`, step 3: drops `ALERTS.GOLD_DISPOSITION`, and only now. Dropping it while the old view still selects it makes the queue fail with `SF-000904` (invalid identifier).
6. `python scripts/deploy_snowflake.py --apply --step data --step grants --step verify`, then `--step app --step health`. The view is recreated with `CREATE OR REPLACE` and no `COPY GRANTS`, so its grants are discarded, which is why the grants step comes after the schema step.

Check afterwards that `DECISION_LEDGER` has the same row count as before. None of these steps leaves a row in it: the schema step only creates the table if it is missing, and the verify step's test insert is rolled back.

If the schema step stops on `CREATE CORTEX SEARCH SERVICE ... 003041` ("already exists, but current role has no privileges"), the existing `CORPUS_SEARCH` service belongs to another role. Drop it as its owner and re-run the schema step, which recreates it and rebuilds its index.

## Production gate

Production use requires approved identity controls, least-privilege access, masking and row-access policies, data-residency review, regulated-record retention, monitoring, incident response, and formal Compliance/Legal approval. See [SECURITY.md](SECURITY.md).

