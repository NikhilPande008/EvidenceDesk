#!/usr/bin/env python3
"""
Render the capability, architecture, security-checklist, scalability, limitation and roadmap TABLES of ARCHITECTURE.md, PRODUCTION_READINESS.md and
KNOWN_LIMITATIONS.md FROM skills/readiness.py — the single source — so a document cannot claim more (or less) than the code says.

  python3 scripts/render_readiness_docs.py            # print what would be written
  python3 scripts/render_readiness_docs.py --write    # rewrite the marked blocks in place
  python3 scripts/render_readiness_docs.py --check    # exit 1 if any document is out of date (tests/test_readiness.py does the same)

Each rendered block sits between `<!-- readiness:NAME:start -->` and `<!-- readiness:NAME:end -->`; everything outside the markers is hand-written.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skills import readiness as R  # noqa: E402

DOCS = {
    "ARCHITECTURE.md": ("architecture", "scalability", "capabilities"),
    "PRODUCTION_READINESS.md": ("checklist",),
    "KNOWN_LIMITATIONS.md": ("limitations", "roadmap"),
}


def _cell(text) -> str:
    return str(text if text is not None else "—").replace("|", "\\|").replace("\n", " ")


def _table(headers: list[str], rows: list[list]) -> str:
    return "\n".join(["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"] + ["| " + " | ".join(_cell(c) for c in r) + " |" for r in rows])


def render(name: str) -> str:
    if name == "architecture":
        rows = [[s["n"], s["name"], s["latency"], R.TIER_LABEL[s["status"]], s["prototype"], s["production"]] for s in R.ARCHITECTURE_STAGES]
        return _table(["#", "Stage", "Latency class", "Status", "In this prototype", "In production"], rows)
    if name == "scalability":
        return _table(["Topic", "Prototype today", "Approach at scale"], [[x["topic"], x["prototype"], x["approach"]] for x in R.SCALABILITY])
    if name == "capabilities":
        out = []
        for tier in R.TIERS:
            items = [c for c in R.CAPABILITIES if c["status"] == tier]
            out += [f"### {R.TIER_LABEL[tier]} ({len(items)})", "", R.TIER_MEANING[tier], ""]
            if tier == R.IMPLEMENTED:
                out.append(_table(["ID", "Area", "Capability", "Evidence", "Where", "Limits"], [[c["id"], c["area"], c["capability"], c["evidence"], c["where"], c["limits"]] for c in items]))
            elif tier == R.SIMULATED:
                out.append(_table(["ID", "Area", "Capability", "Simulated by", "Production replaces it with"], [[c["id"], c["area"], c["capability"], c["simulated_by"], c["production"]] for c in items]))
            else:
                out.append(_table(["ID", "Area", "Capability", "What production needs"], [[c["id"], c["area"], c["capability"], c["production"]] for c in items]))
            out.append("")
        return "\n".join(out).rstrip()
    if name == "checklist":
        rows = [[c["control"], R.TIER_LABEL[c["status"]], c["today"], c["production"], c["evidence"] or "—"] for c in R.PRODUCTION_CHECKLIST]
        return _table(["Control", "Status", "Today", "Production needs", "Evidence"], rows)
    if name == "limitations":
        return "\n".join(f"{i}. {line}" for i, line in enumerate(R.KNOWN_LIMITATIONS, 1))
    if name == "roadmap":
        return _table(["Priority", "Item", "Why"], [[r["priority"], r["item"], r["why"]] for r in R.ROADMAP])
    raise KeyError(name)


def block(name: str, body: str) -> str:
    return f"<!-- readiness:{name}:start -->\n{body}\n<!-- readiness:{name}:end -->"


def rendered(path: Path, names: tuple[str, ...]) -> str:
    text = path.read_text()
    for n in names:
        pat = re.compile(rf"<!-- readiness:{n}:start -->.*?<!-- readiness:{n}:end -->", re.S)
        if not pat.search(text):
            raise SystemExit(f"{path.name}: marker block '{n}' is missing")
        text = pat.sub(lambda m, n=n: block(n, render(n)), text)
    return text


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    missing_docs = [name for name in DOCS if not (ROOT / name).exists()]
    if missing_docs:
        if len(missing_docs) == len(DOCS) and mode == "--check":
            print("readiness reports are intentionally private and not tracked in this public repository")
            return 0
        raise SystemExit("missing readiness document(s): " + ", ".join(missing_docs))
    stale = []
    for doc, names in DOCS.items():
        path = ROOT / doc
        new = rendered(path, names)
        if new != path.read_text():
            stale.append(doc)
            if mode == "--write":
                path.write_text(new)
    if mode == "--check":
        if stale:
            print("OUT OF DATE (run: python3 scripts/render_readiness_docs.py --write): " + ", ".join(stale))
            return 1
        print("readiness documents are up to date")
        return 0
    print(("rewrote: " if mode == "--write" else "would rewrite: ") + (", ".join(stale) or "nothing (up to date)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
