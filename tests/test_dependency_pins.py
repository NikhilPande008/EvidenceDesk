"""
requirements.txt gives the supported ranges and constraints.txt gives the exact versions the offline suite was run on. They must agree, and the Streamlit floor must stay at the
lowest version that was actually measured.

The floor exists because test_queue_filters_survive_case_navigation fails on Streamlit 1.56 to 1.60 (a KeyError inside AppTest's own widget-state handling) and passes on 1.61 and later;
a fresh clone on 1.56 and pandas 3.0.2 gave 602 passed and 1 failed, which the README's count did not say. This test does not run Streamlit; it keeps the two files honest.

Offline. Usage:  python3 tests/test_dependency_pins.py     (or pytest)
"""

from __future__ import annotations

from packaging.requirements import Requirement
from packaging.version import Version

from _helpers import ROOT, Runner

MEASURED_STREAMLIT_FLOOR = Version("1.61.0")           # the lowest version the whole offline suite was run on (603 passed)
FAILING_STREAMLIT = Version("1.60.0")                  # the highest version on which the navigation test failed


def _lines(name: str) -> list[str]:
    out = []
    for raw in (ROOT / name).read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out


def _requirements() -> dict[str, Requirement]:
    return {r.name.lower(): r for r in map(Requirement, _lines("requirements.txt"))}


def _constraints() -> dict[str, Requirement]:
    return {r.name.lower(): r for r in map(Requirement, _lines("constraints.txt"))}


def test_every_requirement_has_an_exact_pin_inside_its_range():
    reqs, pins = _requirements(), _constraints()
    assert reqs, "requirements.txt lists nothing"
    missing = sorted(set(reqs) - set(pins))
    assert not missing, f"constraints.txt has no pin for: {missing}"
    problems = []
    for name, pin in pins.items():
        specs = list(pin.specifier)
        if len(specs) != 1 or specs[0].operator != "==":
            problems.append(f"{name}: a constraint must be one exact '==' pin, got '{pin.specifier}'")
            continue
        if name not in reqs:
            problems.append(f"{name}: pinned but not a requirement")
        elif not reqs[name].specifier.contains(specs[0].version, prereleases=True):
            problems.append(f"{name}=={specs[0].version} is outside the range in requirements.txt ({reqs[name].specifier})")
    assert not problems, "\n  ".join(problems)
    print(f"  [PASS] {len(pins)} exact pins, each inside its requirement's range, none missing")


def test_the_streamlit_floor_is_the_measured_one():
    spec = _requirements()["streamlit"].specifier
    assert spec.contains(str(MEASURED_STREAMLIT_FLOOR)), f"requirements.txt excludes the measured version {MEASURED_STREAMLIT_FLOOR}: {spec}"
    assert not spec.contains(str(FAILING_STREAMLIT)), f"requirements.txt allows {FAILING_STREAMLIT}, on which test_queue_filters_survive_case_navigation fails: {spec}"
    pinned = Version(next(iter(_constraints()["streamlit"].specifier)).version)
    assert pinned >= MEASURED_STREAMLIT_FLOOR, f"constraints.txt pins Streamlit {pinned}, below the measured floor {MEASURED_STREAMLIT_FLOOR}"
    print(f"  [PASS] Streamlit range {spec} excludes {FAILING_STREAMLIT} and includes {MEASURED_STREAMLIT_FLOOR}; pinned {pinned}")


TESTS = [
    test_every_requirement_has_an_exact_pin_inside_its_range,
    test_the_streamlit_floor_is_the_measured_one,
]

if __name__ == "__main__":
    raise SystemExit(Runner("Dependency pins").run(TESTS))
