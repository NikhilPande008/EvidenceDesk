"""
The code must stay valid on Python 3.11, the version CI compiles with, even when it is written and tested on a newer interpreter.

Python 3.12 (PEP 701) lets an f-string reuse its own quote character inside {...}, put a backslash there, and spread an expression over lines. 3.11 rejects all three with a
SyntaxError that a developer on 3.12 or later never sees. On 3.12 and later this test reads the tokens and reports those constructs; on 3.11 the compiler itself is the check
and this test passes trivially. The first time this slipped through was scripts/eval_live_replay.py, caught by CI, not by the suite.

Offline. Usage:  python3 tests/test_python_311_syntax.py     (or pytest)
"""

from __future__ import annotations

import io
import subprocess
import sys
import tokenize
from pathlib import Path

from _helpers import ROOT, Runner


def pep701_constructs(source: str) -> list[tuple[int, str]]:
    """(line, what) for every f-string that is only valid from Python 3.12: the outer quote reused inside {...}, or a backslash or a newline inside {...}."""
    if sys.version_info < (3, 12):
        return []                                    # 3.11 and earlier tokenise an f-string as one STRING token; the compiler already rejects these
    found: list[tuple[int, str]] = []
    frames: list[dict] = []                          # one per open f-string: its quote and how deep inside {...} the tokens are
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.FSTRING_START:
            if frames and frames[-1]["depth"] > 0:
                outer, inner = frames[-1]["quote"], tok.string[tok.string.index(tok.string[-1]):]
                if inner == outer:
                    found.append((tok.start[0], f"an f-string inside {{...}} reuses the enclosing quote {outer}"))
            frames.append({"quote": tok.string[tok.string.index(tok.string[-1]):], "depth": 0})
        elif tok.type == tokenize.FSTRING_END:
            frames.pop()
        elif frames and tok.type == tokenize.OP and tok.string == "{" :
            frames[-1]["depth"] += 1
        elif frames and tok.type == tokenize.OP and tok.string == "}":
            frames[-1]["depth"] -= 1
        elif frames and frames[-1]["depth"] > 0:
            if tok.type == tokenize.STRING:
                quote = '"""' if tok.string.lstrip("rbuRBUfF").startswith('"""') else "'''" if tok.string.lstrip("rbuRBUfF").startswith("'''") else tok.string.lstrip("rbuRBUfF")[0]
                if quote == frames[-1]["quote"]:
                    found.append((tok.start[0], f"a string inside {{...}} reuses the enclosing quote {quote}"))
                if "\\" in tok.string:
                    found.append((tok.start[0], "a backslash inside {...}"))
            elif tok.type in (tokenize.NL, tokenize.COMMENT):
                found.append((tok.start[0], "a newline or comment inside {...}"))
    return found


def test_the_checker_finds_the_construct_that_broke_ci_and_passes_the_fixed_form():
    if sys.version_info < (3, 12):
        print("  [PASS] Python 3.11: the compiler is the check (skipped here by design)")
        return
    broken = '''print(f"draft={(d['status'] + f' unsupported={len(d['unsupported_facts'])}') if d else '-'}")\n'''
    assert any("reuses the enclosing quote" in why for _, why in pep701_constructs(broken)), pep701_constructs(broken)
    assert pep701_constructs('x = f"{d["k"]}"\n') and pep701_constructs('x = f"{a}\\\\"\n') == []
    fixed = '''cell = d["status"] + " unsupported=" + str(len(d["unsupported_facts"]))\nprint(f"draft={cell} {r.get('error') or ''}")\n'''
    assert pep701_constructs(fixed) == [], pep701_constructs(fixed)
    triple_ok = 'y = f"""{d["k"]}"""\n'
    assert pep701_constructs(triple_ok) == [], "a double quote inside a triple-quoted f-string is valid on 3.11"
    print("  [PASS] the checker flags a reused quote inside {...}, accepts the fixed form and a triple-quoted outer string")


def test_no_tracked_python_file_uses_syntax_that_python_3_11_rejects():
    files = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    assert len(files) > 100, f"only {len(files)} files listed: git may be unavailable here"
    problems = []
    for rel in files:
        for line, why in pep701_constructs((Path(ROOT) / rel).read_text(encoding="utf-8")):
            problems.append(f"{rel}:{line}: {why}")
    assert not problems, "Python 3.12-only syntax (CI compiles with 3.11):\n  " + "\n  ".join(problems)
    print(f"  [PASS] {len(files)} Python files: no f-string syntax that only Python 3.12 accepts")


TESTS = [
    test_the_checker_finds_the_construct_that_broke_ci_and_passes_the_fixed_form,
    test_no_tracked_python_file_uses_syntax_that_python_3_11_rejects,
]

if __name__ == "__main__":
    raise SystemExit(Runner("Python 3.11 syntax guard").run(TESTS))
