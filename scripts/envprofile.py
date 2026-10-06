"""
envprofile.py — deploy the SAME artifacts into a second, isolated environment (a "clean room").

The repository names its Snowflake objects once, in many files (FIU_COPILOT.AML in the app, the ledger module,
the seed scripts, the DDL, the semantic model; FIU_WH; FIU_ADMIN_ROLE / FIU_APP_ROLE / FIU_AUDIT_ROLE). Rather than
fork those files, a *profile* renders a copy of the tree in which exactly those five identifiers carry a suffix
(default `_CR`: database FIU_COPILOT_CR, warehouse FIU_WH_CR, roles FIU_ADMIN_ROLE_CR, …). Every deployment step
then runs from the rendered copy, so the clean room exercises the real bootstrap / roles / ownership / DDL / data /
grants / verify / app path against an environment that shares NO named object with production.

Safety properties (each is asserted by tests/test_deploy_profile.py):
  * the `default` profile is the identity — nothing is rendered, nothing changes for the production flow;
  * rendering is reversible (un-rendering the copy gives back the source byte-for-byte), so the ONLY difference
    between source and copy is the five identifiers — the proof that the clean room deploys the shipped code;
  * after rendering, no production identifier survives anywhere in the copy (a leftover would address production);
  * `.env`, caches and editor backups are never copied; the build directory is only ever wiped if this module made it.

What a clean room in the SAME account still shares (cannot be isolated by naming): the account itself, the Cortex
account parameters (cross-region inference), the SNOWFLAKE.CORTEX_USER database role, SYSTEM_COMPUTE_POOL_CPU, ACCOUNTADMIN
and the connecting user. A different Snowflake ACCOUNT would isolate those too; this module does not create one.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

PROD_NAMES = ("FIU_COPILOT", "FIU_WH", "FIU_ADMIN_ROLE", "FIU_APP_ROLE", "FIU_AUDIT_ROLE")
SCHEMA = "AML"
MARKER = ".fiu-render"
DEFAULT_SUFFIX = "CR"

# Text files get identifier substitution; anything else is copied byte-for-byte.
TEXT_SUFFIXES = {".py", ".sql", ".yaml", ".yml", ".toml", ".txt", ".ini", ".json", ".cfg", ".csv", ".ndjson", ".sh", ".example"}
# Documentation and design files are not part of the deployment (nothing deployed or tested reads them) and routinely MENTION the clean-room
# names, which would not round-trip; they are left out of the copy.
SKIP_DIRS = {".git", ".github", "__pycache__", ".pytest_cache", ".claude", ".venv", "venv", "build", "dist", "node_modules", "output", "design", "evidence"}
SKIP_SUFFIXES = {".md"}
SKIP_FILES = {".env", ".DS_Store", MARKER}
# Files that DEFINE the identifiers (the mapping itself and its tests) are copied byte-for-byte: rendering them would corrupt the mapping.
VERBATIM = {"scripts/envprofile.py", "tests/test_deploy_profile.py"}
SKIP_PATTERNS = (re.compile(r"\.bak"), re.compile(r"\.pyc$"))

_NAME = "|".join(sorted(PROD_NAMES, key=len, reverse=True))
# An identifier is a whole token: not preceded / followed by [A-Za-z0-9_]  (so SNOWFLAKE_APP_ROLE, FIU_AML_COPILOT,
# FIU_WH_CR are never touched). Case-insensitive so generated lower-case SQL (fiu_copilot.aml.…) is renamed too.
_PROD_RE = re.compile(rf"(?<![A-Za-z0-9_])({_NAME})(?![A-Za-z0-9_])", re.I)


class ProfileError(ValueError):
    pass


@dataclass(frozen=True)
class Profile:
    name: str            # "default" | "cleanroom"
    suffix: str          # "" (default) or e.g. "CR"

    def __post_init__(self):
        if self.suffix and not re.fullmatch(r"[A-Z][A-Z0-9]{0,7}", self.suffix):
            raise ProfileError(f"suffix must be 1-8 upper-case letters/digits starting with a letter, got {self.suffix!r}")
        if self.name == "default" and self.suffix:
            raise ProfileError("the default profile has no suffix")
        if self.name != "default" and not self.suffix:
            raise ProfileError("a non-default profile needs a suffix (otherwise it would address production)")

    # -- names -------------------------------------------------------------------------------------------------
    def n(self, prod_name: str) -> str:
        if prod_name not in PROD_NAMES:
            raise ProfileError(f"{prod_name!r} is not a profile-managed identifier")
        return f"{prod_name}_{self.suffix}" if self.suffix else prod_name

    @property
    def is_default(self) -> bool:
        return not self.suffix

    @property
    def database(self) -> str:
        return self.n("FIU_COPILOT")

    @property
    def schema(self) -> str:
        return SCHEMA

    @property
    def warehouse(self) -> str:
        return self.n("FIU_WH")

    @property
    def admin_role(self) -> str:
        return self.n("FIU_ADMIN_ROLE")

    @property
    def app_role(self) -> str:
        return self.n("FIU_APP_ROLE")

    @property
    def audit_role(self) -> str:
        return self.n("FIU_AUDIT_ROLE")

    @property
    def streamlit_fqn(self) -> str:
        return f"{self.database}.{SCHEMA}.FIU_AML_COPILOT"

    def names(self) -> dict[str, str]:
        return {p: self.n(p) for p in PROD_NAMES}

    def scope_env(self) -> dict[str, str]:
        """Environment that points every child process at THIS profile's objects, overriding whatever .env says."""
        return {"SNOWFLAKE_DATABASE": self.database, "SNOWFLAKE_SCHEMA": self.schema, "SNOWFLAKE_WAREHOUSE": self.warehouse,
                "SNOWFLAKE_APP_ROLE": self.app_role}

    # -- rendering ---------------------------------------------------------------------------------------------
    def render_text(self, text: str) -> str:
        if self.is_default:
            return text

        def sub(m: re.Match) -> str:
            tok = m.group(1)
            return tok + "_" + (self.suffix if tok.isupper() else self.suffix.lower())
        return _PROD_RE.sub(sub, text)

    def unrender_text(self, text: str) -> str:
        if self.is_default:
            return text
        rx = re.compile(rf"(?<![A-Za-z0-9_])({_NAME})_{self.suffix}(?![A-Za-z0-9_])", re.I)
        return rx.sub(lambda m: m.group(1), text)

    def leftovers(self, text: str) -> list[str]:
        """Production identifiers still present in (rendered) text. Must be empty for a non-default profile."""
        if self.is_default:
            return []
        return [m.group(1) for m in _PROD_RE.finditer(text)]


DEFAULT = Profile("default", "")


def cleanroom(suffix: str = DEFAULT_SUFFIX) -> Profile:
    return Profile("cleanroom", suffix)


def get_profile(name: str, suffix: str | None = None) -> Profile:
    if name == "default":
        return DEFAULT
    if name == "cleanroom":
        return cleanroom(suffix or DEFAULT_SUFFIX)
    raise ProfileError(f"unknown profile {name!r} (use 'default' or 'cleanroom')")


# ── tree rendering ───────────────────────────────────────────────────────────────────────────────────────────

def _skip(rel: Path) -> bool:
    if any(part in SKIP_DIRS for part in rel.parts[:-1]) or rel.name in SKIP_FILES:
        return True
    return rel.suffix.lower() in SKIP_SUFFIXES or any(p.search(rel.name) for p in SKIP_PATTERNS)


def default_build_dir(profile: Profile) -> Path:
    return Path(tempfile.gettempdir()) / "fiu-copilot-build" / profile.name


def render_tree(profile: Profile, src: Path, dst: Path) -> dict:
    """Render `src` into `dst` for `profile`. Returns a report; raises ProfileError if the copy could address production."""
    if profile.is_default:
        raise ProfileError("the default profile is not rendered — deploy from the repository itself")
    src, dst = Path(src).resolve(), Path(dst).resolve()
    if dst == src or src in dst.parents or dst in src.parents:
        raise ProfileError(f"build directory {dst} must be outside the repository {src}")
    if dst.exists():
        if not (dst / MARKER).exists() and any(dst.iterdir()):
            raise ProfileError(f"refusing to wipe {dst}: it is not a directory this tool rendered (no {MARKER} marker)")
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    (dst / MARKER).write_text(f"rendered for profile {profile.name} suffix {profile.suffix}\n")

    files = text_files = changed_files = substitutions = 0
    per_name: dict[str, int] = {n: 0 for n in PROD_NAMES}
    manifest: dict[str, str] = {}
    for path in sorted(src.rglob("*")):
        rel = path.relative_to(src)
        if path.is_dir() or _skip(rel):
            continue
        out = dst / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        files += 1
        if str(rel) in VERBATIM:
            shutil.copy2(path, out)
            manifest[str(rel)] = hashlib.sha256(path.read_bytes()).hexdigest()
            continue
        if path.suffix.lower() in TEXT_SUFFIXES:
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                shutil.copy2(path, out)
                manifest[str(rel)] = hashlib.sha256(path.read_bytes()).hexdigest()
                continue
            text_files += 1
            rendered = profile.render_text(text)
            if profile.unrender_text(rendered) != text:       # reversibility: the ONLY change is the identifiers
                raise ProfileError(f"{rel}: rendering is not reversible (the file already contains a suffixed identifier?)")
            left = profile.leftovers(rendered)
            if left:
                raise ProfileError(f"{rel}: production identifier(s) survived rendering: {sorted(set(left))}")
            if rendered != text:
                changed_files += 1
                for m in _PROD_RE.finditer(text):
                    substitutions += 1
                    per_name[m.group(1).upper()] += 1
            out.write_text(rendered, encoding="utf-8")
            shutil.copymode(path, out)
            manifest[str(rel)] = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
        else:
            shutil.copy2(path, out)
            manifest[str(rel)] = hashlib.sha256(path.read_bytes()).hexdigest()
    report = {"profile": profile.name, "suffix": profile.suffix, "names": profile.names(), "files": files, "text_files": text_files,
              "files_changed": changed_files, "substitutions": substitutions, "per_identifier": per_name,
              "tree_sha256": hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()}
    (dst / MARKER).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report
