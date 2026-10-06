-- 04_verify_ledger_rbac.sql — PROOF that the app role cannot mutate the ledger, and cannot read the answer key. Runs as FIU_APP_ROLE.
--
-- SAFETY RULE (learned the hard way, 2026-09-30): a verification must NEVER execute a statement that
-- destroys data if the check turns out to FAIL. An earlier version attempted TRUNCATE and DROP; because
-- Snowflake's default SECONDARY ROLES are ALL, the session also carried the owner role, both statements
-- SUCCEEDED, and the ledger was truncated and dropped. So:
--   * USE SECONDARY ROLES NONE first, and the script FAILS if any secondary role is still active;
--   * mutation is attempted only with statements that are no-ops even if they are (wrongly) allowed:
--       UPDATE ... WHERE 1 = 0   and   DELETE ... WHERE 1 = 0     (privilege is checked at compile time);
--   * TRUNCATE / DROP / ALTER are NOT executed. Their absence is proven from the GRANTS: the app role's
--     privileges on the ledger must be exactly {INSERT, SELECT} and it must not own the table
--     (TRUNCATE needs the TRUNCATE privilege; DROP/ALTER need OWNERSHIP).
--   * INSERT is attempted inside a transaction that is ROLLED BACK.
-- Expected: overall = 'PASS'. scripts/deploy_snowflake.py --step verify runs this and exits non-zero otherwise.
USE ROLE FIU_APP_ROLE;
USE SECONDARY ROLES NONE;
USE WAREHOUSE FIU_WH;

EXECUTE IMMEDIATE $$
DECLARE
  who            VARCHAR DEFAULT CURRENT_ROLE();
  secondary      VARCHAR DEFAULT CURRENT_SECONDARY_ROLES()::VARCHAR;
  isolated       BOOLEAN DEFAULT FALSE;
  select_ok      BOOLEAN DEFAULT FALSE;
  insert_ok      BOOLEAN DEFAULT FALSE;
  update_denied  BOOLEAN DEFAULT FALSE;  update_msg VARCHAR DEFAULT '';
  delete_denied  BOOLEAN DEFAULT FALSE;  delete_msg VARCHAR DEFAULT '';
  privs          VARCHAR DEFAULT '';
  privs_exact    BOOLEAN DEFAULT FALSE;
  not_owner      BOOLEAN DEFAULT FALSE;
  key_denied     BOOLEAN DEFAULT FALSE;  key_msg VARCHAR DEFAULT '';
  key_grants     NUMBER  DEFAULT -1;
BEGIN
  isolated := (secondary ILIKE '%"roles":""%');   -- CURRENT_SECONDARY_ROLES() = {"roles":"","value":""} after USE SECONDARY ROLES NONE

  BEGIN
    SELECT COUNT(*) FROM FIU_COPILOT.AML.DECISION_LEDGER;
    select_ok := TRUE;
  EXCEPTION WHEN OTHER THEN select_ok := FALSE;
  END;

  BEGIN
    BEGIN TRANSACTION;
    INSERT INTO FIU_COPILOT.AML.DECISION_LEDGER
      (DECISION_ID, ALERT_ID, CUSTOMER_REF, DISPOSITION, DECISION_MAKER_ID, DECISION_MADE_AT, RATIONALE_TEXT)
      SELECT 'RBAC-VERIFY-' || UUID_STRING(), 'RBAC-VERIFY', 'RBAC-VERIFY', 'DEFERRED', 'RBAC-VERIFY',
             CURRENT_TIMESTAMP(), 'rbac verification row - rolled back';
    insert_ok := TRUE;
    ROLLBACK;
  EXCEPTION WHEN OTHER THEN
    insert_ok := FALSE;
    ROLLBACK;
  END;

  BEGIN
    UPDATE FIU_COPILOT.AML.DECISION_LEDGER SET RATIONALE_TEXT = RATIONALE_TEXT WHERE 1 = 0;
  EXCEPTION WHEN OTHER THEN update_denied := TRUE; update_msg := SQLERRM;
  END;
  BEGIN
    DELETE FROM FIU_COPILOT.AML.DECISION_LEDGER WHERE 1 = 0;
  EXCEPTION WHEN OTHER THEN delete_denied := TRUE; delete_msg := SQLERRM;
  END;

  -- TRUNCATE / DROP / ALTER: proven from grants, never executed.
  SHOW GRANTS TO ROLE FIU_APP_ROLE;
  SELECT COALESCE(LISTAGG(DISTINCT "privilege", ',') WITHIN GROUP (ORDER BY "privilege"), '') INTO :privs
    FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()))
    WHERE "granted_on" = 'TABLE' AND "name" = 'FIU_COPILOT.AML.DECISION_LEDGER';
  privs_exact := (privs = 'INSERT,SELECT');
  not_owner := (privs NOT ILIKE '%OWNERSHIP%');

  -- The answer key (ALERT_GOLD_LABELS) must be unreadable: a read is refused, AND the app role holds no grant of any kind on it.
  -- (A read on a table that does not exist is also refused; the grants count below is the part that does not depend on the table existing.)
  BEGIN
    SELECT COUNT(*) FROM FIU_COPILOT.AML.ALERT_GOLD_LABELS;
    key_denied := FALSE;
  EXCEPTION WHEN OTHER THEN key_denied := TRUE; key_msg := SQLERRM;
  END;
  SHOW GRANTS TO ROLE FIU_APP_ROLE;
  SELECT COUNT(*) INTO :key_grants FROM TABLE(RESULT_SCAN(LAST_QUERY_ID())) WHERE "name" ILIKE '%ALERT_GOLD_LABELS%';

  RETURN OBJECT_CONSTRUCT(
    'role', who, 'secondary_roles', secondary, 'isolated', isolated,
    'select_ok', select_ok, 'insert_ok', insert_ok,
    'update_denied', update_denied, 'update_msg', LEFT(update_msg, 120),
    'delete_denied', delete_denied, 'delete_msg', LEFT(delete_msg, 120),
    'ledger_privileges', privs, 'privileges_are_exactly_insert_select', privs_exact, 'app_role_is_not_owner', not_owner,
    'answer_key_read_denied', key_denied, 'answer_key_msg', LEFT(key_msg, 120), 'answer_key_grants_to_app_role', key_grants,
    'truncate_drop_alter', 'not executed - denied by grants (see ledger_privileges)',
    'overall', IFF(isolated AND select_ok AND insert_ok AND update_denied AND delete_denied AND privs_exact AND not_owner AND key_denied AND key_grants = 0, 'PASS', 'FAIL')
  );
END;
$$;
