"""
QW-2: Semantic model / DDL conformance.

Assert that every column referenced in domain/corpus/export/semantic_model.yaml
exists as a column in the corresponding DDL file.  No Snowflake connection needed.

Usage:
    python3 tests/test_semantic_model.py
    python3 -m pytest tests/test_semantic_model.py -v
"""

from __future__ import annotations
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("PyYAML is required: pip install pyyaml")
    sys.exit(1)

BASE           = Path(__file__).parent.parent
SEMANTIC_MODEL = BASE / "domain/corpus/export/semantic_model.yaml"
DDL_DIR        = BASE / "domain/corpus/export/ddl"

# Map semantic-model table name → DDL file + table name in that file
TABLE_DDL_MAP = {
    "regulatory_corpus": (DDL_DIR / "regulatory_corpus.sql", "REGULATORY_CORPUS"),
    "alerts":            (DDL_DIR / "views.sql",             "ALERTS_CURRENT"),   # view: status derived from ledger
    "decision_ledger":   (DDL_DIR / "regulatory_corpus.sql", "DECISION_LEDGER"),
    "transactions":      (DDL_DIR / "transactions.sql",      "TRANSACTIONS"),
}

# SQL keywords / aggregate / scalar function names to exclude from column checks
_SQL_KEYWORDS = {
    "COUNT", "COUNT_IF", "SUM", "AVG", "MIN", "MAX", "ROUND", "FLOOR", "CEIL",
    "ABS", "TRUNC", "CASE", "WHEN", "THEN", "ELSE", "END",
    "AND", "OR", "NOT", "IN", "IS", "NULL", "TRUE", "FALSE",
    "DISTINCT", "IF", "IFF", "DATEDIFF", "DAY", "NOW", "CURRENT_DATE",
    "CURRENT_TIMESTAMP", "COALESCE", "NULLIF", "CAST", "TRY_CAST", "ZEROIFNULL",
}


def _extract_ddl_columns(ddl_path: Path, table_name: str) -> set[str]:
    """Extract column names from a CREATE TABLE block in a DDL file."""
    text = ddl_path.read_text()
    pattern = re.compile(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?" + re.escape(table_name) + r"\s*\(",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        # views declare an explicit column list: CREATE [OR REPLACE] VIEW NAME ( col, col, ... ) AS
        vm = re.search(r"CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+" + re.escape(table_name) + r"\s*\((.*?)\)\s*AS\b",
                       text, re.IGNORECASE | re.DOTALL)
        if vm:
            return {c.strip().upper() for c in vm.group(1).split(",") if c.strip()}
        return set()

    # Walk forward to collect the table body (handle nested parens)
    start = match.end()
    depth = 1
    body_chars = []
    i = start
    while i < len(text) and depth > 0:
        c = text[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        if depth > 0:
            body_chars.append(c)
        i += 1
    body = "".join(body_chars)

    columns: set[str] = set()
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("--") or line.upper().startswith("CONSTRAINT"):
            continue
        col_match = re.match(r"^([A-Z_][A-Z0-9_]*)\s", line, re.IGNORECASE)
        if col_match:
            columns.add(col_match.group(1).upper())
    return columns


def _extract_semantic_columns(model: dict, table_name: str) -> set[str]:
    """
    Extract column name candidates from dimension/measure/time_dimension expr
    fields for a given table.  Only bare identifiers are flagged — SQL keywords
    and aggregate function names are excluded.
    """
    columns: set[str] = set()
    for table in model.get("tables", []):
        if table.get("name", "").lower() != table_name.lower():
            continue
        all_items = (
            table.get("dimensions", [])
            + table.get("measures", [])
            + table.get("time_dimensions", [])
        )
        for item in all_items:
            expr = str(item.get("expr", ""))
            # Strip single-quoted string literals so 'NOT_FILE', 'CONTESTED', etc.
            # are not mistaken for column references.
            expr_stripped = re.sub(r"'[^']*'", "", expr)
            for ident in re.findall(r"\b([A-Z_][A-Z0-9_]*)\b", expr_stripped, re.IGNORECASE):
                up = ident.upper()
                if up not in _SQL_KEYWORDS and not up.isdigit():
                    columns.add(up)
    return columns


def test_semantic_model_columns_exist_in_ddl():
    """Every column referenced in semantic_model.yaml must exist in the DDL."""
    with open(SEMANTIC_MODEL) as f:
        model = yaml.safe_load(f)

    mismatches: list[str] = []

    for table_name, (ddl_path, ddl_table) in TABLE_DDL_MAP.items():
        semantic_cols = _extract_semantic_columns(model, table_name)
        ddl_cols      = _extract_ddl_columns(ddl_path, ddl_table)

        if not ddl_cols:
            mismatches.append(
                f"{table_name}: could not extract DDL columns from {ddl_path.name}"
            )
            continue

        missing = semantic_cols - ddl_cols
        if missing:
            mismatches.append(
                f"{table_name}: {len(missing)} semantic model column(s) absent in DDL: "
                f"{sorted(missing)}"
            )
        else:
            print(
                f"  [PASS] {table_name}: {len(semantic_cols)} column refs checked, "
                f"all present in DDL"
            )

    if mismatches:
        for m in mismatches:
            print(f"  [FAIL] {m}")
        raise AssertionError("Semantic model references columns not in DDL — see above")


def test_nv_filter_in_cortex_search_ddl():
    """CREATE CORTEX SEARCH SERVICE DDL must be uncommented and include NV filter."""
    ddl_text = (DDL_DIR / "regulatory_corpus.sql").read_text()

    # Must contain un-commented CREATE CORTEX SEARCH SERVICE
    assert re.search(
        r"^CREATE\s+(?:OR\s+REPLACE\s+|.*?IF\s+NOT\s+EXISTS\s+)?CORTEX\s+SEARCH\s+SERVICE\s+(?:IF\s+NOT\s+EXISTS\s+)?CORPUS_SEARCH",
        ddl_text,
        re.IGNORECASE | re.MULTILINE,
    ), "CREATE CORTEX SEARCH SERVICE CORPUS_SEARCH must not be commented out"

    # Must include the NV filter
    assert "EVIDENCE_LEVEL IN ('PROVEN', 'ASSUMED')" in ddl_text, \
        "CORTEX SEARCH SERVICE DDL must filter to PROVEN+ASSUMED (NV Layer 1)"

    print("  [PASS] CORPUS_SEARCH DDL: service is active, NV filter present")


def test_semantic_model_satisfies_the_cortex_analyst_contract():
    """Regression for the live failures found 2026-09-30: Analyst rejected the model because
    `verified_at` was a date string and `decision_ledger` had no primary key for the join.
    Offline mirror of the validation rules Cortex Analyst applies."""
    model = yaml.safe_load(SEMANTIC_MODEL.read_text())
    tables = {t["name"]: t for t in model["tables"]}

    def logical_cols(t):
        return {c["name"] for k in ("dimensions", "time_dimensions", "measures", "facts") for c in (t.get(k) or [])}

    for name, t in tables.items():
        pk = (t.get("primary_key") or {}).get("columns")
        assert pk, f"table {name} needs a primary_key (required when it is the ONE side of a join)"
        assert set(pk) <= logical_cols(t), f"{name}: primary_key {pk} must name logical columns"
    for r in model.get("relationships", []):
        assert r["relationship_type"] in ("many_to_one", "one_to_one"), r["name"]
        assert r["join_type"] in ("inner", "left_outer", "full_outer", "cross"), r["name"]
        for rc in r["relationship_columns"]:
            assert rc["left_column"] in logical_cols(tables[r["left_table"]]), (r["name"], rc)
            assert rc["right_column"] in logical_cols(tables[r["right_table"]]), (r["name"], rc)
    for q in model.get("verified_queries", []):
        assert isinstance(q["verified_at"], int) and not isinstance(q["verified_at"], bool), \
            f"{q['name']}: verified_at must be an integer Unix timestamp, got {q['verified_at']!r}"
        assert "AML.ALERTS " not in q["sql"] and "AML.ALERTS\n" not in q["sql"], f"{q['name']}: use ALERTS_CURRENT"
    print(f"  [PASS] semantic model meets the Cortex Analyst contract: {len(tables)} tables with primary keys, "
          f"{len(model['relationships'])} many_to_one relationships, {len(model['verified_queries'])} verified queries with integer verified_at")


TESTS = [
    test_semantic_model_columns_exist_in_ddl,
    test_semantic_model_satisfies_the_cortex_analyst_contract,
    test_nv_filter_in_cortex_search_ddl,
]

if __name__ == "__main__":
    print("Running semantic-model / DDL conformance tests...\n")
    passed = 0
    failed = 0
    for test_fn in TESTS:
        try:
            test_fn()
            passed += 1
        except Exception as exc:
            failed += 1
            print(f"  [FAIL] {test_fn.__name__}: {exc}")
    print(f"\n{passed}/{passed + failed} tests passed.")
    if failed:
        sys.exit(1)
