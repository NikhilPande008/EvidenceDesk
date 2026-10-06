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
pip install -r requirements.txt
python -m py_compile streamlit_app.py skills/*.py scripts/*.py tests/*.py
python -m pytest tests -q -p no:cacheprovider
```

## Deployment approach

Review the plan produced by `scripts/deploy_snowflake.py` before authorising any change. Use its clean-room/profile mechanism for demonstrations and testing. The deployment scripts, role SQL, and `snowflake.yml` are executable artifacts; they are the source of truth for object names, grants, and uploaded modules.

Do not publish connection names, account identifiers, role memberships, query results, deployment logs, screenshots, or health-check output in a public repository.

## Production gate

Production use requires approved identity controls, least-privilege access, masking and row-access policies, data-residency review, regulated-record retention, monitoring, incident response, and formal Compliance/Legal approval. See [SECURITY.md](SECURITY.md).

