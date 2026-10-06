# Contributor Handoff

## Product boundary

EvidenceDesk is a synthetic-data AML investigation and decision-defensibility prototype. It supports an authorised human decision; it does not autonomously file reports or provide legal advice.

## Before changing code

1. Read the affected code and tests.
2. Preserve fail-closed model handling, deterministic evidence grounding, regulatory-basis checks, human review, and safe rendering.
3. Do not introduce real customer data, credentials, account identifiers, or deployment evidence into Git.
4. Update tests for every behavioural change.

## Before release

```bash
python -m py_compile streamlit_app.py skills/*.py scripts/*.py tests/*.py
python -m pytest tests -q -m "not live" -p no:cacheprovider
```

Use `-m "not live"`. With credentials in `.env`, a plain `pytest tests` also runs the live tests against whichever database `.env` names, which may not be the one you meant.

Run any Snowflake-connected checks only in an authorised non-production environment. Review generated plans before applying them. Keep live results, logs, screenshots, and customer-specific operating procedures outside the public repository.

## Documentation rule

Public documentation must remain concise and accurate. Code, schemas, tests, and approved deployment configuration are authoritative for implementation behaviour. Do not state that an environment, regulatory source, control, or business outcome has been verified unless independently evidenced and approved for disclosure.

