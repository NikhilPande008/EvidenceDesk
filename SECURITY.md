# Security and Data-Use Boundary

## Prototype boundary

This repository uses synthetic data only. Do not load real customer, account, transaction, identity, or regulatory-filing data into this prototype without a separately approved production design.

Credentials belong in managed secrets or local ignored configuration, never in source code, tests, documentation, logs, or commits.

## Implemented safeguards

The application is designed to use role-based access, constrained database writes, deterministic fact grounding, fail-closed AI-output handling, and safe rendering of untrusted content. These controls reduce risk; they do not make the prototype production-ready on their own.

The decision-ledger design supports provenance and integrity checking. It does **not make owner-role deletion impossible**. An independent audit export can detect records changed after export (`MODIFIED_SINCE_EXPORT`) or missing from an export (`DELETED_RECORD`), but such an export is **NOT provisioned** by this public prototype. Use external retention-locked storage for a production audit record.

## Required before production data

- SSO, phishing-resistant MFA, and authenticated decision-maker identity.
- Least-privilege roles, separation of duties, network restrictions, and access reviews.
- Dynamic masking, row-access policies, tokenisation/minimisation, and controlled prompt content.
- Approved model access, data-residency review, monitoring, audit logging, and incident response.
- Retention, legal hold, and independent retention-locked/WORM archival aligned to applicable obligations.
- Formal security, privacy, Compliance, Legal, and model-risk approval.

## Responsible disclosure

Do not disclose suspected vulnerabilities, credentials, customer information, or deployment details in public issues. Report them privately to the repository owner.
