"""Probe for tests/test_reliability.py — NOT collected by default (the filename has no `test_` prefix).

The first test deliberately leaks an environment variable; the conftest guard must fail it, name only the KEY (never the
value), and restore the environment so the second test is unaffected."""

import os


def test_a_leaks_an_environment_variable():
    os.environ["SNOWFLAKE_LEAK_PROBE"] = "probe-secret-value-731"


def test_b_runs_after_and_sees_a_clean_environment():
    assert "SNOWFLAKE_LEAK_PROBE" not in os.environ
