---
name: evidencedesk-deploy-check
description: Plan and check an EvidenceDesk deployment into an isolated clean-room Snowflake environment and read its health report; never touches the production namespace.
---

# Deploy and health-check into a clean-room environment

`scripts/deploy_snowflake.py` reproduces the Snowflake side from a rendered copy of the repository in which five account-level identifiers carry a suffix, so a
clean-room run shares no named object with production (`scripts/envprofile.py`). Every step connects as the role it is meant for and is checked against the
profile's scope.

## Steps

1. Plan only. This is the default and changes nothing:

   ```
   python3 scripts/deploy_snowflake.py --profile cleanroom --suffix <SUFFIX>
   ```

2. Show the user the plan. Wait for an explicit go-ahead before `--apply`. Steps can be run one at a time with `--step` (`preflight`, `bootstrap`, `roles`,
   `ownership`, `ddl`, `data`, `grants`, `verify`, `app`, `health`, `test`).
3. After an applied run, read the health report (read-only; HEALTHY, UNAVAILABLE or UNVERIFIED per check):

   ```
   python3 scripts/health_check.py --profile cleanroom --suffix <SUFFIX>
   ```

   Report UNVERIFIED as UNVERIFIED. It means the check could not be run as the connecting role, not that it passed. `--deep` makes billed model calls: only on request.
4. The `verify` step proves UPDATE and DELETE on the ledger are denied to the application role. Quote its output, not the expectation.

## Rules

- Use `--profile cleanroom` for anything you apply. Never run `--apply` on the default (production) profile in this skill, and never without the user's go-ahead.
- `teardown` drops the clean-room environment. Never include it unless the user asks for it by name.
- Do not write suffixed environment names into repository files: the renderer refuses a file that already contains one.
- Credentials come from `.env`. Never print or repeat them.
