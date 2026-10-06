-- 05_audit_export.sql — OPT-IN append-only audit-export store for DECISION_LEDGER. Run as ACCOUNTADMIN. Idempotent.
-- NOT part of `scripts/deploy_snowflake.py --apply`; apply deliberately with:
--     python3 scripts/audit_ledger.py provision --apply
-- {{DEPLOY_USER}} is substituted by that script with the connecting user.
--
-- WHAT THIS IS FOR (see skills/audit.py, SECURITY.md §2)
--   RBAC stops the app role from changing the ledger; ROW_HASH makes an in-place EDIT detectable. Neither reveals that a row
--   was DELETED by someone holding the ledger-owner role. This store keeps a hash-chained list of (decision id, row hash)
--   somewhere the ledger owner (FIU_ADMIN_ROLE) has NO privileges, so a later reconciliation can report deleted rows,
--   rows changed since export and a broken chain.
--
-- WHAT THIS IS NOT
--   Not WORM storage — Snowflake has none. FIU_AUDIT_ROLE owns the table and could alter it, and so can ACCOUNTADMIN.
--   Separation of duties is the control: in a real deployment grant FIU_AUDIT_ROLE to a DIFFERENT person than FIU_ADMIN_ROLE,
--   never grant it to SYSADMIN / the admin chain, and ALSO copy each export (scripts/audit_ledger.py export --out FILE) to
--   storage outside this account with write-once retention. Rows deleted BEFORE their first export are not detectable.
USE ROLE ACCOUNTADMIN;

CREATE ROLE IF NOT EXISTS FIU_AUDIT_ROLE COMMENT = 'Audit exporter: reads the ledger, appends to FIU_COPILOT.AUDIT.LEDGER_EXPORT; no other role may write there';
GRANT ROLE FIU_AUDIT_ROLE TO USER {{DEPLOY_USER}};

GRANT USAGE  ON WAREHOUSE FIU_WH                                  TO ROLE FIU_AUDIT_ROLE;
GRANT USAGE  ON DATABASE  FIU_COPILOT                             TO ROLE FIU_AUDIT_ROLE;
GRANT USAGE  ON SCHEMA    FIU_COPILOT.AML                         TO ROLE FIU_AUDIT_ROLE;
GRANT SELECT ON TABLE     FIU_COPILOT.AML.DECISION_LEDGER         TO ROLE FIU_AUDIT_ROLE;
GRANT SELECT ON VIEW      FIU_COPILOT.AML.DECISION_LEDGER_INTEGRITY_V TO ROLE FIU_AUDIT_ROLE;

CREATE SCHEMA IF NOT EXISTS FIU_COPILOT.AUDIT COMMENT = 'Append-only audit export of DECISION_LEDGER. Owned by FIU_AUDIT_ROLE, NOT by FIU_ADMIN_ROLE';
GRANT OWNERSHIP ON SCHEMA FIU_COPILOT.AUDIT TO ROLE FIU_AUDIT_ROLE COPY CURRENT GRANTS;

USE ROLE FIU_AUDIT_ROLE;
CREATE TABLE IF NOT EXISTS FIU_COPILOT.AUDIT.LEDGER_EXPORT (
    SEQ                  NUMBER        NOT NULL,   -- 1, 2, 3 … contiguous: a gap means a record was removed
    EXPORT_ID            VARCHAR(64)   NOT NULL,   -- one value per export run
    DECISION_ID          VARCHAR(50)   NOT NULL,
    ALERT_ID             VARCHAR(100),
    DISPOSITION          VARCHAR(20),
    DECISION_MADE_AT_UTC VARCHAR(40),
    ROW_HASH             VARCHAR(64),              -- the ledger row's ROW_HASH at export time; NULL for a legacy (unhashed) row
    CONTENT_ANCHORED     BOOLEAN       NOT NULL,   -- FALSE = existence only (legacy row)
    PREV_CHAIN_HASH      VARCHAR(64)   NOT NULL,   -- chain: SHA-256(prev | seq | decision_id | row_hash | made_at)
    CHAIN_HASH           VARCHAR(64)   NOT NULL,
    EXPORTED_AT          TIMESTAMP_TZ  DEFAULT CURRENT_TIMESTAMP(),
    EXPORTED_BY          VARCHAR(100)  DEFAULT CURRENT_ROLE(),
    CONSTRAINT PK_LEDGER_EXPORT PRIMARY KEY (SEQ)  -- informational in Snowflake (not enforced); verify_chain() detects gaps/duplicates
);
COMMENT ON TABLE FIU_COPILOT.AUDIT.LEDGER_EXPORT IS
    'Hash-chained, append-only export of DECISION_LEDGER (skills/audit.py). Written only by FIU_AUDIT_ROLE; the app role has SELECT. A witness for deleted-row detection, not WORM storage.';

USE ROLE ACCOUNTADMIN;
-- The app (reconciliation panel) and the live reports may READ the export; nobody but the audit role writes it.
GRANT USAGE  ON SCHEMA FIU_COPILOT.AUDIT              TO ROLE FIU_APP_ROLE;
GRANT SELECT ON TABLE  FIU_COPILOT.AUDIT.LEDGER_EXPORT TO ROLE FIU_APP_ROLE;
