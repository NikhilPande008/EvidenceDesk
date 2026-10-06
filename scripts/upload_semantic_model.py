"""
upload_semantic_model.py — upload the Cortex Analyst semantic model to @SEMANTIC_STAGE.

Run as the object-owner role (FIU_ADMIN_ROLE) — see DEPLOY.md. FIU_APP_ROLE only needs READ on the stage.

Usage:
    python3 scripts/upload_semantic_model.py
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))
from skills.connection import (  # noqa: E402
    SnowflakeConfigError, SnowflakeConnectError, connect_from_env, load_env, missing_config,
)

YAML_FILE = REPO_ROOT / "domain" / "corpus" / "export" / "semantic_model.yaml"


def main():
    load_env(REPO_ROOT)
    if missing_config():
        print("ERROR: missing Snowflake configuration: " + ", ".join(missing_config()) +
              " (copy .env.example to .env).", file=sys.stderr)
        sys.exit(1)
    if not YAML_FILE.exists():
        print(f"ERROR: {YAML_FILE} not found", file=sys.stderr)
        sys.exit(1)
    try:
        conn = connect_from_env()
    except (SnowflakeConfigError, SnowflakeConnectError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        sys.exit(1)
    cur = conn.cursor()
    try:
        cur.execute("CREATE STAGE IF NOT EXISTS SEMANTIC_STAGE")
        print("Stage SEMANTIC_STAGE: ready")
        # AUTO_COMPRESS=FALSE keeps the file as plain YAML at @SEMANTIC_STAGE/semantic_model.yaml
        cur.execute(f"PUT 'file://{YAML_FILE}' @SEMANTIC_STAGE OVERWRITE=TRUE AUTO_COMPRESS=FALSE")
        for row in cur.fetchall():
            print(f"PUT result: {row[0]} -> {row[1]} ({row[6]})")
        cur.execute("LIST @SEMANTIC_STAGE")
        print("\nFiles in @SEMANTIC_STAGE:")
        for f in cur.fetchall():
            print(f"  {f[0]}  ({f[1]} bytes)")
        print("\nCortex Analyst is called through its REST endpoint (/api/v2/cortex/analyst/message) with")
        print("semantic_model_file=@FIU_COPILOT.AML.SEMANTIC_STAGE/semantic_model.yaml — there is no")
        print("SNOWFLAKE.CORTEX.ANALYST SQL function. The app's Dashboard 'Ask the data' box exercises it.")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
