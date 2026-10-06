-- 08_move_gold_labels.sql: ONE-OFF migration for an account deployed BEFORE the answer key was split out of ALERTS.
-- A fresh deployment (scripts/deploy_snowflake.py) does not need this: eval_labels.sql creates the table and setup_alerts.py loads it.
--
-- Why: ALERTS.GOLD_DISPOSITION was readable by FIU_APP_ROLE and exposed through ALERTS_CURRENT and Cortex Analyst's semantic model, so an officer
-- could ask the copilot for "the correct answer". After this migration the labels are in ALERT_GOLD_LABELS, which the app role cannot read.
--
-- Run as FIU_ADMIN_ROLE, in this order. Idempotent up to STEP 3.
--   STEP 0   if the account also predates deploy/09_alert_feed_suspicion_time.sql, run that first. The schema step (alerts.sql) comments on the column 09 adds and stops without it.
--   STEP 1-2 (this file, below)  create the table and copy the labels, if the old column still exists.
--   STEP 2b  re-run the views and the semantic model:   python3 scripts/deploy_snowflake.py --step ddl     and     python3 scripts/upload_semantic_model.py
--            (ALERTS_CURRENT must stop selecting the column before it can be dropped.)
--   STEP 3 (the two ALTERs at the end of this file)  drop the old constraint and column. Uncomment them only after STEP 2b succeeded.
-- Afterwards run deploy/04_verify_ledger_rbac.sql as FIU_APP_ROLE: overall must be PASS, including answer_key_read_denied.
USE ROLE FIU_ADMIN_ROLE;
USE WAREHOUSE FIU_WH;
USE SCHEMA FIU_COPILOT.AML;

-- STEP 1
CREATE TABLE IF NOT EXISTS ALERT_GOLD_LABELS (
    ALERT_ID          VARCHAR(20)   NOT NULL,
    GOLD_DISPOSITION  VARCHAR(20)   NOT NULL,
    LABEL_SOURCE      VARCHAR(100)  DEFAULT 'scenario author (synthetic)',
    LOADED_AT         TIMESTAMP_TZ  DEFAULT CURRENT_TIMESTAMP(),
    CONSTRAINT PK_ALERT_GOLD_LABELS PRIMARY KEY (ALERT_ID),
    CONSTRAINT CHK_GOLD_DISP CHECK (GOLD_DISPOSITION IN ('FILE', 'NOT_FILE', 'CONTESTED'))
);

-- STEP 2: copy only if the old column is still there
EXECUTE IMMEDIATE $$
DECLARE
  has_col NUMBER DEFAULT 0;
BEGIN
  SELECT COUNT(*) INTO :has_col FROM FIU_COPILOT.INFORMATION_SCHEMA.COLUMNS
   WHERE TABLE_SCHEMA = 'AML' AND TABLE_NAME = 'ALERTS' AND COLUMN_NAME = 'GOLD_DISPOSITION';
  IF (has_col > 0) THEN
    EXECUTE IMMEDIATE 'MERGE INTO FIU_COPILOT.AML.ALERT_GOLD_LABELS t USING (SELECT ALERT_ID, GOLD_DISPOSITION FROM FIU_COPILOT.AML.ALERTS) s '
                   || 'ON t.ALERT_ID = s.ALERT_ID WHEN NOT MATCHED THEN INSERT (ALERT_ID, GOLD_DISPOSITION) VALUES (s.ALERT_ID, s.GOLD_DISPOSITION)';
  END IF;
  RETURN 'labels copied: ' || has_col;
END;
$$;

SELECT GOLD_DISPOSITION, COUNT(*) AS N FROM ALERT_GOLD_LABELS GROUP BY 1 ORDER BY 1;   -- expect CONTESTED 4, FILE 9, NOT_FILE 3 (16 in all) on an account seeded before the Gulf-remittance alerts; setup_alerts.py then adds ALERT-17 to ALERT-19, giving CONTESTED 4, FILE 10, NOT_FILE 5 (19)

-- STEP 3 (uncomment ONLY after STEP 2b: the view no longer selects the column)
-- ALTER TABLE ALERTS DROP CONSTRAINT CHK_GOLD_DISP;
-- ALTER TABLE ALERTS DROP COLUMN GOLD_DISPOSITION;
