"""
load_corpus.py — Load domain/corpus/rules/*.yaml into Snowflake REGULATORY_CORPUS

Usage:
    pip install snowflake-connector-python pyyaml python-dotenv
    python scripts/load_corpus.py

Configuration: see .env.example / skills/connection.py (SNOWFLAKE_ROLE is honoured — run as the
object-owner role, FIU_ADMIN_ROLE, per DEPLOY.md).

Run modes:
    --dry-run     Print rows that would be inserted without touching Snowflake
    --upsert      Use MERGE (replace existing rows by RULE_ID) — safe to re-run
    Default: INSERT only; fails on duplicate RULE_ID
"""

import os
import sys
import json
import argparse
import glob
from datetime import date, datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
from skills.connection import (  # noqa: E402
    SnowflakeConfigError, SnowflakeConnectError, connect_from_env, load_env, missing_config,
)

# ── paths ────────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).parent.parent
RULES_DIR = REPO_ROOT / "domain" / "corpus" / "rules"
MANIFEST  = yaml.safe_load((REPO_ROOT / "domain" / "corpus" / "manifest.yaml").read_text())

SNAPSHOT_DATE  = date.fromisoformat(MANIFEST["snapshot_date"])   # fallback when a rule has none
CORPUS_VERSION = MANIFEST["corpus_version"]

# ── YAML → row ────────────────────────────────────────────────────────────────

def parse_rule(rule: dict, source_file: str) -> dict:
    """Convert one YAML rule entry to a flat dict matching REGULATORY_CORPUS columns."""
    ps = rule.get("primary_source", {}) or {}

    # dates
    def to_date(val):
        if val is None:
            return None
        if isinstance(val, date):
            return val
        try:
            return date.fromisoformat(str(val))
        except ValueError:
            return None

    supersession = rule.get("supersession") or {}
    return {
        "RULE_ID":              rule["id"],
        "CATEGORY":             rule.get("category", "UNKNOWN"),
        "SUBCATEGORY":          rule.get("subcategory"),
        "RULE_TEXT":            rule.get("rule", "").strip(),
        "APPLIES_TO":           json.dumps(rule.get("applies_to") or []),
        "SOURCE_DOCUMENT":      ps.get("document"),
        "SOURCE_URL":           ps.get("url"),
        "SOURCE_URL_VERIFIED":  bool(ps.get("url_verified", False)),
        "SOURCE_SECTION":       ps.get("section"),
        "SOURCE_ACCESSED_DATE": to_date(ps.get("accessed_date")),
        "EFFECTIVE_DATE":       to_date(rule.get("effective_date")),
        "SNAPSHOT_DATE":        to_date(rule.get("snapshot_date")) or SNAPSHOT_DATE,
        "LAST_VERIFIED":        to_date(rule.get("last_verified")),
        "EVIDENCE_LEVEL":       rule.get("evidence_level", "NEEDS-VERIFICATION"),
        "MY_SYNTHESIS":         (rule.get("my_synthesis") or "").strip() or None,
        "GAP_NOTES":            (rule.get("gap_notes") or "").strip() or None,
        "RELATED_RULES":        json.dumps(rule.get("related_rules") or []),
        # governance (finding #4)
        "SOURCE_AUTHORITY":     rule.get("source_authority"),
        "CORPUS_VERSION":       rule.get("corpus_version") or CORPUS_VERSION,
        "REVIEW_STATUS":        rule.get("review_status"),
        "OWNER":                rule.get("owner"),
        "VERIFIED_BY":          rule.get("verified_by"),
        "SUPERSEDED_BY":        rule.get("superseded_by"),
        "REPLACES":             rule.get("replaces") or supersession.get("supersedes"),
        # lifecycle (Phase 14) — optional; written only if a rule supplies one (see with_lifecycle_columns)
        "LAST_REVIEWED":        to_date(rule.get("last_reviewed")),
        "REVIEW_SLA_DAYS":      rule.get("review_sla_days"),
        "APPROVAL_STATUS":      rule.get("approval_status"),
        "APPROVED_BY":          rule.get("approved_by"),
        "APPROVED_ON":          to_date(rule.get("approved_on")),
    }


def load_yaml_files() -> list[dict]:
    rows = []
    files = sorted(glob.glob(str(RULES_DIR / "*.yaml")))
    if not files:
        print(f"ERROR: No YAML files found in {RULES_DIR}", file=sys.stderr)
        sys.exit(1)

    for fpath in files:
        fname = Path(fpath).name
        with open(fpath, "r") as f:
            data = yaml.safe_load(f)
        rules = data.get("rules", [])
        for rule in rules:
            try:
                rows.append(parse_rule(rule, fname))
            except KeyError as e:
                print(f"WARNING: Skipping {rule.get('id', '?')} in {fname} — missing field {e}")
        print(f"  {fname}: {len(rules)} rules")

    return rows


# ── Snowflake helpers ─────────────────────────────────────────────────────────

INSERT_SQL = """
INSERT INTO REGULATORY_CORPUS (
    RULE_ID, CATEGORY, SUBCATEGORY, RULE_TEXT, APPLIES_TO,
    SOURCE_DOCUMENT, SOURCE_URL, SOURCE_URL_VERIFIED, SOURCE_SECTION, SOURCE_ACCESSED_DATE,
    EFFECTIVE_DATE, SNAPSHOT_DATE, LAST_VERIFIED, EVIDENCE_LEVEL,
    MY_SYNTHESIS, GAP_NOTES, RELATED_RULES,
    SOURCE_AUTHORITY, CORPUS_VERSION, REVIEW_STATUS, OWNER, VERIFIED_BY, SUPERSEDED_BY, REPLACES
) VALUES (
    %(RULE_ID)s, %(CATEGORY)s, %(SUBCATEGORY)s, %(RULE_TEXT)s, PARSE_JSON(%(APPLIES_TO)s),
    %(SOURCE_DOCUMENT)s, %(SOURCE_URL)s, %(SOURCE_URL_VERIFIED)s, %(SOURCE_SECTION)s, %(SOURCE_ACCESSED_DATE)s,
    %(EFFECTIVE_DATE)s, %(SNAPSHOT_DATE)s, %(LAST_VERIFIED)s, %(EVIDENCE_LEVEL)s,
    %(MY_SYNTHESIS)s, %(GAP_NOTES)s, PARSE_JSON(%(RELATED_RULES)s),
    %(SOURCE_AUTHORITY)s, %(CORPUS_VERSION)s, %(REVIEW_STATUS)s, %(OWNER)s, %(VERIFIED_BY)s, %(SUPERSEDED_BY)s, %(REPLACES)s
)
"""

MERGE_SQL = """
MERGE INTO REGULATORY_CORPUS AS target
USING (SELECT
    %(RULE_ID)s::VARCHAR        AS RULE_ID,
    %(CATEGORY)s::VARCHAR       AS CATEGORY,
    %(SUBCATEGORY)s::VARCHAR    AS SUBCATEGORY,
    %(RULE_TEXT)s::TEXT         AS RULE_TEXT,
    PARSE_JSON(%(APPLIES_TO)s)  AS APPLIES_TO,
    %(SOURCE_DOCUMENT)s::TEXT   AS SOURCE_DOCUMENT,
    %(SOURCE_URL)s::VARCHAR     AS SOURCE_URL,
    %(SOURCE_URL_VERIFIED)s::BOOLEAN AS SOURCE_URL_VERIFIED,
    %(SOURCE_SECTION)s::VARCHAR AS SOURCE_SECTION,
    %(SOURCE_ACCESSED_DATE)s::DATE AS SOURCE_ACCESSED_DATE,
    %(EFFECTIVE_DATE)s::DATE    AS EFFECTIVE_DATE,
    %(SNAPSHOT_DATE)s::DATE     AS SNAPSHOT_DATE,
    %(LAST_VERIFIED)s::DATE     AS LAST_VERIFIED,
    %(EVIDENCE_LEVEL)s::VARCHAR AS EVIDENCE_LEVEL,
    %(MY_SYNTHESIS)s::TEXT      AS MY_SYNTHESIS,
    %(GAP_NOTES)s::TEXT         AS GAP_NOTES,
    PARSE_JSON(%(RELATED_RULES)s) AS RELATED_RULES,
    %(SOURCE_AUTHORITY)s::VARCHAR AS SOURCE_AUTHORITY,
    %(CORPUS_VERSION)s::VARCHAR   AS CORPUS_VERSION,
    %(REVIEW_STATUS)s::VARCHAR    AS REVIEW_STATUS,
    %(OWNER)s::VARCHAR            AS OWNER,
    %(VERIFIED_BY)s::VARCHAR      AS VERIFIED_BY,
    %(SUPERSEDED_BY)s::VARCHAR    AS SUPERSEDED_BY,
    %(REPLACES)s::VARCHAR         AS REPLACES
) AS source ON target.RULE_ID = source.RULE_ID
WHEN MATCHED THEN UPDATE SET
    CATEGORY             = source.CATEGORY,
    SUBCATEGORY          = source.SUBCATEGORY,
    RULE_TEXT            = source.RULE_TEXT,
    APPLIES_TO           = source.APPLIES_TO,
    SOURCE_DOCUMENT      = source.SOURCE_DOCUMENT,
    SOURCE_URL           = source.SOURCE_URL,
    SOURCE_URL_VERIFIED  = source.SOURCE_URL_VERIFIED,
    SOURCE_SECTION       = source.SOURCE_SECTION,
    SOURCE_ACCESSED_DATE = source.SOURCE_ACCESSED_DATE,
    EFFECTIVE_DATE       = source.EFFECTIVE_DATE,
    SNAPSHOT_DATE        = source.SNAPSHOT_DATE,
    LAST_VERIFIED        = source.LAST_VERIFIED,
    EVIDENCE_LEVEL       = source.EVIDENCE_LEVEL,
    MY_SYNTHESIS         = source.MY_SYNTHESIS,
    GAP_NOTES            = source.GAP_NOTES,
    RELATED_RULES        = source.RELATED_RULES,
    SOURCE_AUTHORITY     = source.SOURCE_AUTHORITY,
    CORPUS_VERSION       = source.CORPUS_VERSION,
    REVIEW_STATUS        = source.REVIEW_STATUS,
    OWNER                = source.OWNER,
    VERIFIED_BY          = source.VERIFIED_BY,
    SUPERSEDED_BY        = source.SUPERSEDED_BY,
    REPLACES             = source.REPLACES,
    UPDATED_AT           = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (
    RULE_ID, CATEGORY, SUBCATEGORY, RULE_TEXT, APPLIES_TO,
    SOURCE_DOCUMENT, SOURCE_URL, SOURCE_URL_VERIFIED, SOURCE_SECTION, SOURCE_ACCESSED_DATE,
    EFFECTIVE_DATE, SNAPSHOT_DATE, LAST_VERIFIED, EVIDENCE_LEVEL,
    MY_SYNTHESIS, GAP_NOTES, RELATED_RULES,
    SOURCE_AUTHORITY, CORPUS_VERSION, REVIEW_STATUS, OWNER, VERIFIED_BY, SUPERSEDED_BY, REPLACES
) VALUES (
    source.RULE_ID, source.CATEGORY, source.SUBCATEGORY, source.RULE_TEXT, source.APPLIES_TO,
    source.SOURCE_DOCUMENT, source.SOURCE_URL, source.SOURCE_URL_VERIFIED, source.SOURCE_SECTION,
    source.SOURCE_ACCESSED_DATE, source.EFFECTIVE_DATE, source.SNAPSHOT_DATE, source.LAST_VERIFIED,
    source.EVIDENCE_LEVEL, source.MY_SYNTHESIS, source.GAP_NOTES, source.RELATED_RULES,
    source.SOURCE_AUTHORITY, source.CORPUS_VERSION, source.REVIEW_STATUS, source.OWNER,
    source.VERIFIED_BY, source.SUPERSEDED_BY, source.REPLACES
)
"""


LIFECYCLE_COLUMNS = ("LAST_REVIEWED", "REVIEW_SLA_DAYS", "APPROVAL_STATUS", "APPROVED_BY", "APPROVED_ON")
_CASTS = {"LAST_REVIEWED": "::DATE", "APPROVED_ON": "::DATE", "REVIEW_SLA_DAYS": "::NUMBER", "APPROVAL_STATUS": "::VARCHAR", "APPROVED_BY": "::VARCHAR"}


def with_lifecycle_columns(sql: str, rows: list[dict]) -> str:
    """Add the lifecycle columns to the statement ONLY for those some rule actually supplies. The shipped YAML supplies none, so the
    statement is byte-for-byte the original and a table that has not been migrated still loads."""
    extra = [c for c in LIFECYCLE_COLUMNS if any(r.get(c) is not None for r in rows)]
    if not extra:
        return sql
    if "MERGE INTO" in sql:
        sql = sql.replace("    %(REPLACES)s::VARCHAR         AS REPLACES\n", "    %(REPLACES)s::VARCHAR         AS REPLACES,\n" +
                          ",\n".join(f"    %({c})s{_CASTS.get(c, '')} AS {c}" for c in extra) + "\n")
        sql = sql.replace("    REPLACES             = source.REPLACES,\n", "    REPLACES             = source.REPLACES,\n" +
                          "".join(f"    {c} = source.{c},\n" for c in extra))
        sql = sql.replace("SOURCE_AUTHORITY, CORPUS_VERSION, REVIEW_STATUS, OWNER, VERIFIED_BY, SUPERSEDED_BY, REPLACES\n) VALUES (\n    source.RULE_ID",
                          "SOURCE_AUTHORITY, CORPUS_VERSION, REVIEW_STATUS, OWNER, VERIFIED_BY, SUPERSEDED_BY, REPLACES, " + ", ".join(extra) + "\n) VALUES (\n    source.RULE_ID")
        sql = sql.replace("    source.VERIFIED_BY, source.SUPERSEDED_BY, source.REPLACES\n)", "    source.VERIFIED_BY, source.SUPERSEDED_BY, source.REPLACES, " + ", ".join(f"source.{c}" for c in extra) + "\n)")
    else:
        sql = sql.replace("OWNER, VERIFIED_BY, SUPERSEDED_BY, REPLACES\n) VALUES (", "OWNER, VERIFIED_BY, SUPERSEDED_BY, REPLACES, " + ", ".join(extra) + "\n) VALUES (")
        sql = sql.replace("%(SUPERSEDED_BY)s, %(REPLACES)s\n)", "%(SUPERSEDED_BY)s, %(REPLACES)s, " + ", ".join(f"%({c})s" for c in extra) + "\n)")
    return sql


def get_connection():
    return connect_from_env()


def run_load(rows: list[dict], upsert: bool):
    sql = with_lifecycle_columns(MERGE_SQL if upsert else INSERT_SQL, rows)
    mode = "UPSERT (MERGE)" if upsert else "INSERT"

    conn = get_connection()
    cur  = conn.cursor()
    ok, failed = 0, []

    try:
        for row in rows:
            try:
                cur.execute(sql, row)
                ok += 1
            except Exception as e:
                failed.append((row["RULE_ID"], str(e)))
    finally:
        cur.close()
        conn.close()

    print(f"\n{mode} complete: {ok} rows succeeded, {len(failed)} failed")
    for rule_id, err in failed:
        print(f"  FAILED {rule_id}: {err}")

    if failed:
        sys.exit(1)


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Load corpus YAML → Snowflake REGULATORY_CORPUS")
    parser.add_argument("--dry-run", action="store_true", help="Print rows; do not write to Snowflake")
    parser.add_argument("--upsert",  action="store_true", help="MERGE on RULE_ID (safe to re-run)")
    args = parser.parse_args()

    load_env(REPO_ROOT)

    print(f"Reading YAML files from: {RULES_DIR}")
    rows = load_yaml_files()
    print(f"\nTotal rules parsed: {len(rows)}")

    # evidence level summary
    by_level = {}
    for r in rows:
        by_level[r["EVIDENCE_LEVEL"]] = by_level.get(r["EVIDENCE_LEVEL"], 0) + 1
    for level, count in sorted(by_level.items()):
        print(f"  {level}: {count}")

    if args.dry_run:
        print("\n--- DRY RUN: first 3 rows ---")
        for row in rows[:3]:
            print(json.dumps({k: str(v) if isinstance(v, date) else v for k, v in row.items()}, indent=2))
        print("\nDry run complete. No data written.")
        return

    if missing_config():
        print("ERROR: missing Snowflake configuration: " + ", ".join(missing_config()) +
              " (copy .env.example to .env).", file=sys.stderr)
        sys.exit(1)

    try:
        run_load(rows, upsert=args.upsert)
    except (SnowflakeConfigError, SnowflakeConnectError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        sys.exit(1)

    print("\nCORPUS_SEARCH is defined in regulatory_corpus.sql (created by scripts/deploy_snowflake.py);")
    print("it refreshes from REGULATORY_CORPUS within its TARGET_LAG (1 hour) — or run:")
    print("  ALTER CORTEX SEARCH SERVICE FIU_COPILOT.AML.CORPUS_SEARCH REFRESH;")


if __name__ == "__main__":
    main()
