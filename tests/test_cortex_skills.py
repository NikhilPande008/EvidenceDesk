"""
The Cortex Code CLI skill files in .cortex/skills/ must not drift from the repository they describe (T6).

  * each skill is a directory holding SKILL.md with YAML frontmatter whose `name` is the directory's name and whose `description` is a real sentence;
  * every script a skill tells the reader to run exists, and every --flag it shows for that script is one the script actually defines;
  * no skill carries a clean-room environment name (the renderer refuses a file that does) or a credential-looking string;
  * every skill that can write says in words that it does not do so unasked.

Offline. Usage:  python3 tests/test_cortex_skills.py     (or pytest)
"""

from __future__ import annotations

import re

from _helpers import ROOT, Runner

SKILLS_DIR = ROOT / ".cortex" / "skills"
EXPECTED = {"evidencedesk-verify-pack", "evidencedesk-audit-ledger", "evidencedesk-load-feed", "evidencedesk-deploy-check", "evidencedesk-measure"}


def _skills() -> dict[str, str]:
    return {p.parent.name: p.read_text(encoding="utf-8") for p in sorted(SKILLS_DIR.glob("*/SKILL.md"))}


def _frontmatter(text: str) -> dict[str, str]:
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert m, "no YAML frontmatter"
    out = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip()
    return out


def test_every_skill_is_a_directory_with_a_skill_md_whose_name_is_the_directory():
    skills = _skills()
    assert set(skills) == EXPECTED, set(skills) ^ EXPECTED
    for name, text in skills.items():
        fm = _frontmatter(text)
        assert fm.get("name") == name, (name, fm)
        assert len(fm.get("description", "")) > 60 and fm["description"].endswith("."), (name, fm.get("description"))
        assert set(fm) <= {"name", "description", "tools"}, (name, set(fm))
    print(f"  [PASS] {len(skills)} skills, each a directory with a SKILL.md whose frontmatter name is the directory name and whose description is a sentence")


def test_every_script_a_skill_runs_exists_and_every_flag_shown_for_it_is_defined():
    checked = 0
    for name, text in _skills().items():
        for block in re.findall(r"```\n(.*?)```", text, re.S):
            for line in block.splitlines():
                m = re.search(r"python3 ((?:-m )?[\w./-]+)", line)
                if not m:
                    continue
                target = m.group(1)
                if target == "-m pytest" or target.startswith("-m"):
                    continue
                path = ROOT / target
                assert path.exists(), f"{name}: runs {target}, which does not exist"
                source = path.read_text(encoding="utf-8")
                for flag in re.findall(r"(?<![\w-])(--[a-z][a-z0-9-]*)", line.split("#")[0]):
                    assert f'"{flag}"' in source or f"'{flag}'" in source or re.search(rf"\b{re.escape(flag)}\b", source), f"{name}: {target} shown with {flag}, which it does not define"
                    checked += 1
    assert checked >= 10, f"only {checked} flags were checked: the pattern is not finding the commands"
    print(f"  [PASS] every script a skill runs exists, and the {checked} flags shown for them are defined by those scripts")


def test_the_skills_carry_no_environment_name_or_secret_and_the_writing_ones_say_they_do_not_write_unasked():
    for name, text in _skills().items():
        assert not re.search(r"FIU_[A-Z_]+_CR\d*\b|FIU_COPILOT_[A-Z0-9]+", text), f"{name}: a suffixed clean-room name"
        assert not re.search(r"eyJ[A-Za-z0-9_-]{20,}|SNOWFLAKE_TOKEN\s*=|password\s*=", text, re.I), name
    for name in ("evidencedesk-audit-ledger", "evidencedesk-load-feed", "evidencedesk-deploy-check"):
        assert re.search(r"Never [^.\n]*(--apply|UPDATE|DELETE)", _skills()[name]), f"{name}: no explicit refusal to write unasked"
    assert "never prevented" in _skills()["evidencedesk-audit-ledger"], "concurrency is detected, not prevented: the skill must not suggest otherwise"
    print("  [PASS] no clean-room name or secret in any skill; each skill that can write refuses to do so unasked; concurrency is stated as detected, never prevented")


def test_the_skill_files_are_tracked_not_swallowed_by_the_markdown_ignore_rule():
    import subprocess
    for name in EXPECTED:
        r = subprocess.run(["git", "check-ignore", "-q", f".cortex/skills/{name}/SKILL.md"], cwd=ROOT)
        assert r.returncode == 1, f"{name}/SKILL.md is git-ignored: it would not reach the repository"
    print("  [PASS] none of the SKILL.md files is git-ignored")


TESTS = [
    test_every_skill_is_a_directory_with_a_skill_md_whose_name_is_the_directory,
    test_every_script_a_skill_runs_exists_and_every_flag_shown_for_it_is_defined,
    test_the_skills_carry_no_environment_name_or_secret_and_the_writing_ones_say_they_do_not_write_unasked,
    test_the_skill_files_are_tracked_not_swallowed_by_the_markdown_ignore_rule,
]

if __name__ == "__main__":
    raise SystemExit(Runner("Cortex Code CLI skill files (.cortex/skills)").run(TESTS))
