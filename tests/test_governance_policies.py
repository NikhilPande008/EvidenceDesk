"""
Opt-in column masking (T7): the SQL does what its header says, undoes exactly what it does, and the driver changes nothing unless told to.

  * the apply file creates a masking policy per column and attaches it; the remove file detaches and drops the same ones, and nothing else;
  * the policy compares CURRENT_ROLE() with the application role (not IS_ROLE_IN_SESSION, which a role hierarchy would satisfy) and masks everyone else;
  * neither file touches DECISION_LEDGER or any data, and neither is part of the default deploy;
  * the driver's default is a plan, `--apply` is needed to execute, and the probe only SELECTs.

Offline (no Snowflake). Usage:  python3 tests/test_governance_policies.py     (or pytest)
"""

from __future__ import annotations

import re

from _helpers import ROOT, Runner

APPLY = (ROOT / "deploy/10_governance_optin.sql").read_text()
REMOVE = (ROOT / "deploy/10_governance_remove.sql").read_text()
DRIVER = (ROOT / "scripts/governance_policies.py").read_text()


def _code(sql: str) -> str:
    return "\n".join(line for line in sql.splitlines() if not line.strip().startswith("--"))


def test_apply_creates_and_attaches_one_policy_per_column_and_remove_undoes_exactly_those():
    created = re.findall(r"CREATE MASKING POLICY IF NOT EXISTS (\w+)", _code(APPLY))
    attached = re.findall(r"ALTER TABLE (\w+) MODIFY COLUMN (\w+) SET MASKING POLICY (\w+)", _code(APPLY))
    assert sorted(created) == ["MASK_COUNTERPARTY", "MASK_CUSTOMER_PROFILE"]
    assert sorted(attached) == [("ALERTS", "CUSTOMER_PROFILE", "MASK_CUSTOMER_PROFILE"), ("TRANSACTIONS", "COUNTERPARTY", "MASK_COUNTERPARTY")]
    detached = re.findall(r"ALTER TABLE (\w+) MODIFY COLUMN (\w+) UNSET MASKING POLICY", _code(REMOVE))
    dropped = re.findall(r"DROP MASKING POLICY IF EXISTS (\w+)", _code(REMOVE))
    assert sorted(detached) == sorted((t, c) for t, c, _ in attached) and sorted(dropped) == sorted(created)
    print("  [PASS] two policies, one per column; the remove file detaches and drops exactly those and nothing else")


def test_the_policy_gives_clear_text_to_the_application_role_only_and_compares_the_current_role():
    for sql in re.findall(r"CREATE MASKING POLICY.*?;", _code(APPLY), re.S):
        assert "CURRENT_ROLE() = 'FIU_APP_ROLE'" in sql and "ELSE '*** masked ***'" in sql, sql
        assert "IS_ROLE_IN_SESSION" not in sql, "a role that inherits the application role through a hierarchy must not get the clear text"
    assert "IS_ROLE_IN_SESSION" not in _code(APPLY)
    assert 'MASK = "*** masked ***"' in DRIVER, "the probe counts the same marker the policy writes"
    print("  [PASS] clear text only when CURRENT_ROLE() is the application role; every other role, including the owner, reads the marker")


def test_neither_file_touches_the_ledger_or_any_data_and_neither_is_in_the_default_deploy():
    for name, sql in (("apply", APPLY), ("remove", REMOVE)):
        code = _code(sql).upper()
        assert "DECISION_LEDGER" not in code, name
        for forbidden in ("INSERT", "UPDATE ", "DELETE", "TRUNCATE", "MERGE", "DROP TABLE", "DROP SCHEMA", "DROP DATABASE", "GRANT", "REVOKE"):
            assert forbidden not in code, f"{name}: {forbidden}"
    deploy = (ROOT / "scripts/deploy_snowflake.py").read_text()
    assert "10_governance" not in deploy, "opt-in: not a step of the deploy driver"
    assert "ledger" in APPLY.lower() and "not a row-access policy" in APPLY.lower(), "the header says what it does not do"
    print("  [PASS] no ledger, no data change, no grant; not a deploy step; the header states its limits (no row access, free text unmasked)")


def test_the_driver_plans_by_default_executes_only_with_apply_and_the_probe_only_selects():
    assert "if not args.apply:\n        return cmd_plan(args)" in DRIVER and DRIVER.count("if not args.apply:") == 2
    probe = DRIVER[DRIVER.index("def cmd_probe"):DRIVER.index("def main")]
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|MERGE|ALTER|DROP|CREATE|GRANT)\b", probe.replace("CREATE", "", 0)), "the probe must only read"
    code = DRIVER.split("from __future__", 1)[1]        # the docstring says the ledger is not touched; the code must not name it
    assert "DECISION_LEDGER" not in code and 'TARGETS = (("TRANSACTIONS", "COUNTERPARTY"' in code
    print("  [PASS] plan by default; apply and remove need --apply; the probe issues SELECTs only and never names the ledger")


TESTS = [
    test_apply_creates_and_attaches_one_policy_per_column_and_remove_undoes_exactly_those,
    test_the_policy_gives_clear_text_to_the_application_role_only_and_compares_the_current_role,
    test_neither_file_touches_the_ledger_or_any_data_and_neither_is_in_the_default_deploy,
    test_the_driver_plans_by_default_executes_only_with_apply_and_the_probe_only_selects,
]

if __name__ == "__main__":
    raise SystemExit(Runner("Opt-in column masking (offline)").run(TESTS))
