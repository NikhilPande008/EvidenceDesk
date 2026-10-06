-- 07_decision_outcomes.sql — OPT-IN append-only feed of DOWNSTREAM OUTCOMES for recorded decisions. Run as ACCOUNTADMIN, AFTER 05_audit_export.sql
-- (it needs the FIU_COPILOT.AUDIT schema and the FIU_AUDIT_ROLE that script creates). Idempotent. NOT part of `scripts/deploy_snowflake.py --apply`:
--     python3 scripts/audit_ledger.py provision --outcomes --apply
--
-- WHAT THIS IS FOR (skills/feedback.py, KPIs on the Business value page)
--   The decision ledger records what the officer decided and why. It cannot record what happened NEXT: a QA reviewer confirming or overturning a
--   closure, an STR returned for rework, a regulator query. Those are the only adjudicated signals that turn the false-positive and rework PROXIES
--   into measurements. Without this feed the app reports "outcomes: not provisioned" and infers nothing.
--
-- WHO WRITES IT
--   A second-line / integration process — NEVER the officer's app role (which receives SELECT only, below). In this prototype the table is owned by
--   FIU_AUDIT_ROLE to avoid minting a sixth role name; in production give it its own role held by the QA / integration service, not by the people
--   who record decisions. Append-only by privilege (the app role cannot write), not WORM: the owner can alter it. Feedback is for monitoring and
--   future calibration only — nothing reads this table to change a score, a gate or a prompt.
USE ROLE FIU_AUDIT_ROLE;

CREATE TABLE IF NOT EXISTS FIU_COPILOT.AUDIT.DECISION_OUTCOMES (
    OUTCOME_ID     VARCHAR(64)   NOT NULL,   -- one per outcome event (UUID)
    DECISION_ID    VARCHAR(50)   NOT NULL,   -- the ledger decision this outcome is about
    ALERT_ID       VARCHAR(100),
    OUTCOME_TYPE   VARCHAR(40)   NOT NULL,
    OUTCOME_AT     TIMESTAMP_TZ  NOT NULL,   -- when it happened in the source system
    SOURCE_SYSTEM  VARCHAR(100),             -- for example the QA tool or case-management system that reported it
    NOTE           VARCHAR(500),             -- free text for the second line; the application never displays it
    RECORDED_BY    VARCHAR(100)  DEFAULT CURRENT_ROLE(),
    CREATED_AT     TIMESTAMP_TZ  DEFAULT CURRENT_TIMESTAMP(),
    CONSTRAINT CHK_OUTCOME_TYPE CHECK (OUTCOME_TYPE IN ('STR_SUBMITTED', 'STR_ACKNOWLEDGED', 'STR_RETURNED_FOR_REWORK', 'FIU_QUERY_RECEIVED', 'LEA_REQUEST_RECEIVED',
                                                         'CLOSURE_CONFIRMED_BY_QA', 'CLOSURE_OVERTURNED_BY_QA', 'CASE_REOPENED', 'NO_FURTHER_ACTION')),
    CONSTRAINT PK_DECISION_OUTCOMES PRIMARY KEY (OUTCOME_ID)       -- informational in Snowflake (not enforced)
);
COMMENT ON TABLE FIU_COPILOT.AUDIT.DECISION_OUTCOMES IS
    'Downstream outcomes of recorded decisions (QA review, rework, regulator queries). Written only by the second-line / integration role; the application role has SELECT. Used for monitoring and future calibration only.';

USE ROLE ACCOUNTADMIN;
-- The Model quality and Business value pages may READ the outcomes (the schema USAGE grant already exists from 05_audit_export.sql).
GRANT SELECT ON TABLE FIU_COPILOT.AUDIT.DECISION_OUTCOMES TO ROLE FIU_APP_ROLE;
