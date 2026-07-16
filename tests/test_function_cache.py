"""The per-function result cache — the thing that makes diff-scoped CI affordable.

WHY THIS EXISTS: `profile_function_cached` was written, was correct, and had never once
executed — zero callers, zero tests, in either this repo or Detective. It is the mechanism a
pull-request check needs: profiling is priced per FUNCTION and keyed by that function's own
source, so touching one function in a file does not re-profile its neighbours.

The load-bearing property is not the hit — it is the MISS. A cache that serves a stale result
reports a number that is plausible, confident, and wrong, which is the single failure mode this
whole tool exists to refuse. So the tests below spend their effort proving invalidation and
eviction, not speed.

A hit is proved by POISONING the cached entry and showing the poison comes back. Timing would
be flaky and would only show that something was fast, not that the cache was read.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from Wesker.ci import profile_function_cached

_CALC = "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n"
_TEST = (
    "from src.calc import add, sub\n\n\n"
    "def test_add():\n    assert add(2, 3) == 5\n\n\n"
    "def test_sub():\n    assert sub(5, 3) == 2\n"
)


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A minimal real project on disk: the cache resolves source off the filesystem."""
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "__init__.py").write_text("")
    (tmp_path / "src" / "calc.py").write_text(_CALC)
    (tmp_path / "tests" / "test_calc.py").write_text(_TEST)
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    return tmp_path


def _keys(root: Path) -> list[str]:
    return sorted(json.loads((root / ".wesker" / "function_cache.json").read_text()))


def test_a_cold_call_profiles_and_writes_one_content_addressed_entry(project):
    """The key carries the function's source hash, not just its name — that is what lets a
    later run tell "unchanged" from "merely same-named"."""
    result = profile_function_cached(".", "src/calc.py", "add")

    assert result is not None
    assert result["total_mutants"] > 0
    keys = _keys(project)
    assert len(keys) == 1
    assert keys[0].startswith("src/calc.py::add:")


def test_a_warm_call_is_served_from_cache_rather_than_reprofiled(project):
    """Proved by poison, not by a stopwatch: if the second call returns the sentinel, it read
    the cache. If it returned a real profile, it re-ran the engine and the cache is decorative."""
    profile_function_cached(".", "src/calc.py", "add")
    cache_file = project / ".wesker" / "function_cache.json"
    key = _keys(project)[0]

    cache_file.write_text(json.dumps({key: {"function_key": "POISON"}}))
    again = profile_function_cached(".", "src/calc.py", "add")

    assert again == {"function_key": "POISON"}


def test_editing_one_function_leaves_its_neighbour_cached(project):
    """The reason this is priced per function and not per file. A PR that touches `sub` must not
    buy a re-profile of `add` — that difference is the entire diff-scoped CI argument."""
    profile_function_cached(".", "src/calc.py", "add")
    add_key_before = _keys(project)[0]

    src = project / "src" / "calc.py"
    src.write_text(src.read_text().replace("return a - b", "return a - b - 0"))
    profile_function_cached(".", "src/calc.py", "add")

    assert _keys(project)[0] == add_key_before, "an edit to sub() invalidated add()"


def test_editing_a_function_invalidates_it_and_the_new_result_is_honest(project):
    """THE ONE THAT MATTERS. Break `add` so its behaviour genuinely changes: a stale cache would
    keep reporting the old all-killed result. The new run must both re-key AND report the
    survivor the edit created."""
    before = profile_function_cached(".", "src/calc.py", "add")
    key_before = _keys(project)[0]

    (project / "src" / "calc.py").write_text("def add(a, b):\n    return a + b + 1\n")
    after = profile_function_cached(".", "src/calc.py", "add")
    key_after = _keys(project)[0]

    assert before is not None and after is not None
    assert key_after != key_before, "edited source served the cached hash"
    assert after["total_survived"] > before["total_survived"], (
        "the edit introduced a survivor the re-profile failed to see"
    )


def test_a_reprofiled_function_keeps_exactly_one_entry(project):
    """`single_valid_copy`: the cache is bounded by the number of functions, not by the number of
    times they were edited. Unbounded growth would make the cache a liability in CI, where it is
    restored and saved on every run."""
    profile_function_cached(".", "src/calc.py", "add")
    (project / "src" / "calc.py").write_text("def add(a, b):\n    return a + b + 1\n")
    profile_function_cached(".", "src/calc.py", "add")

    assert len(_keys(project)) == 1, "the stale entry for the old source survived"


@pytest.mark.usefixtures("project")
def test_an_unreadable_source_file_degrades_to_none_rather_than_raising():
    """A CI check must not abort the run over one unresolvable path. Detective's synthesis
    reached this same branch independently."""
    assert profile_function_cached(".", "src/nonexistent.py", "add") is None


@pytest.mark.usefixtures("project")
def test_a_function_absent_from_the_file_degrades_to_none():
    """Same contract as above, one step deeper: the file parses, the function is not in it."""
    assert profile_function_cached(".", "src/calc.py", "no_such_function") is None
