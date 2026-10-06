-- 09_alert_feed_suspicion_time.sql: ONE-OFF migration for an account deployed BEFORE ALERTS carried the optional SUSPICION_FORMED_AT feed field.
-- A fresh deployment (scripts/deploy_snowflake.py) does not need this: alerts.sql creates the column and setup_alerts.py loads it.
--
-- Run as FIU_ADMIN_ROLE, then re-run the views and the seed so the column is exposed and populated:
--   python3 scripts/deploy_snowflake.py --step ddl      (re-creates ALERTS_CURRENT with the column)
--   python3 scripts/setup_alerts.py                     (loads the offsets, relative to NOW, so the queue shows a live mix of deadlines)
-- Idempotent.
USE ROLE FIU_ADMIN_ROLE;
USE WAREHOUSE FIU_WH;
USE SCHEMA FIU_COPILOT.AML;

ALTER TABLE ALERTS ADD COLUMN IF NOT EXISTS SUSPICION_FORMED_AT TIMESTAMP_TZ;
COMMENT ON COLUMN ALERTS.SUSPICION_FORMED_AT IS
    'Optional feed field: when the upstream investigator or case system recorded that suspicion had formed. It starts the 7-working-day STR clock. NULL when the feed did not supply it; the application never infers it from ALERT_DATE, and the earliest SUSPICION_FORMED_AT in DECISION_LEDGER takes precedence over it.';
