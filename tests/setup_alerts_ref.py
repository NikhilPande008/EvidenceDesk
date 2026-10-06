"""Re-export of the seed data (scripts/setup_alerts.py) for live tests — one source of truth."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from setup_alerts import ALERTS, TRANSACTIONS  # noqa: E402,F401
