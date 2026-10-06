-- 10_governance_optin.sql — OPT-IN column masking on the two columns that name people and parties. Run as FIU_ADMIN_ROLE. Idempotent.
-- NOT part of `scripts/deploy_snowflake.py`: python3 scripts/governance_policies.py apply --apply
-- Undo: deploy/10_governance_remove.sql (python3 scripts/governance_policies.py remove --apply).
--
-- WHAT IT DOES
--   Two masking policies. A role that is NOT the application role reads '*** masked ***' in
--     TRANSACTIONS.COUNTERPARTY   (the name of the party on the other side of a row)
--     ALERTS.CUSTOMER_PROFILE     (occupation, declared income and account notes)
--   so an analyst, a BI tool or a support role granted SELECT on these tables for some other reason does not receive them in clear. The application role (and so
--   the hosted app, which runs as it) reads them unmasked: the officer needs them to decide.
--
-- WHAT IT DOES NOT DO
--   * It does not touch DECISION_LEDGER. The ledger's append-only guarantee is privilege-based (04_verify_ledger_rbac.sql) and is not changed here.
--   * It is not a row-access policy and does not restrict WHICH alerts a role sees: that needs an entitlement source (a desk, a branch, a jurisdiction) that this
--     prototype does not have, and inventing one would be decoration.
--   * It does not mask ALERT_NARRATIVE or the ledger's free text, which can repeat the same names. A masking policy on a column protects that column.
--   * The owner role (FIU_ADMIN_ROLE) also reads masked values once this is applied. Loading data (MERGE) is unaffected.
--   * Masking policies need Snowflake Enterprise edition or higher. On an edition without them the first statement fails with the edition message and nothing is applied.
--
-- The comparison is on CURRENT_ROLE(), not IS_ROLE_IN_SESSION(): a role that happens to inherit the application role through a hierarchy does not get the clear text.
USE ROLE FIU_ADMIN_ROLE;
USE WAREHOUSE FIU_WH;
USE SCHEMA FIU_COPILOT.AML;

CREATE MASKING POLICY IF NOT EXISTS MASK_COUNTERPARTY AS (val VARCHAR) RETURNS VARCHAR ->
    CASE WHEN CURRENT_ROLE() = 'FIU_APP_ROLE' THEN val ELSE '*** masked ***' END;

CREATE MASKING POLICY IF NOT EXISTS MASK_CUSTOMER_PROFILE AS (val VARCHAR) RETURNS VARCHAR ->
    CASE WHEN CURRENT_ROLE() = 'FIU_APP_ROLE' THEN val ELSE '*** masked ***' END;

ALTER TABLE TRANSACTIONS MODIFY COLUMN COUNTERPARTY SET MASKING POLICY MASK_COUNTERPARTY;
ALTER TABLE ALERTS MODIFY COLUMN CUSTOMER_PROFILE SET MASKING POLICY MASK_CUSTOMER_PROFILE;
