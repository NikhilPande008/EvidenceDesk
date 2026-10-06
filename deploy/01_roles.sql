-- 01_roles.sql — minimum-viable RBAC (two roles). Run as ACCOUNTADMIN. Idempotent.
-- {{DEPLOY_USER}} is substituted by scripts/deploy_snowflake.py with the connecting user
-- (or run manually after replacing it).
--
--   FIU_ADMIN_ROLE  OWNS the objects (tables, views, stage, search service). Used only for
--                   provisioning / seeding. Never used by the running app.
--   FIU_APP_ROLE    what the Streamlit app runs as. Least privilege:
--                     · SELECT on reference + alert data,
--                     · INSERT + SELECT (NO UPDATE / DELETE / TRUNCATE) on DECISION_LEDGER,
--                     · Cortex Complete / Search / Analyst access.
--                   Cannot create, alter or drop anything. See 03_grants.sql, SECURITY.md.
USE ROLE ACCOUNTADMIN;

CREATE ROLE IF NOT EXISTS FIU_ADMIN_ROLE COMMENT = 'Owns FIU_COPILOT.AML objects; provisioning only';
CREATE ROLE IF NOT EXISTS FIU_APP_ROLE   COMMENT = 'Runtime role for the AML Copilot app: ledger INSERT+SELECT only';

GRANT ROLE FIU_ADMIN_ROLE TO ROLE SYSADMIN;

GRANT USAGE  ON WAREHOUSE FIU_WH        TO ROLE FIU_ADMIN_ROLE;
GRANT USAGE  ON DATABASE  FIU_COPILOT   TO ROLE FIU_ADMIN_ROLE;
GRANT ALL PRIVILEGES ON SCHEMA FIU_COPILOT.AML TO ROLE FIU_ADMIN_ROLE;

-- The operator who deploys / demos needs to be able to assume both roles.
GRANT ROLE FIU_ADMIN_ROLE TO USER {{DEPLOY_USER}};
GRANT ROLE FIU_APP_ROLE   TO USER {{DEPLOY_USER}};
