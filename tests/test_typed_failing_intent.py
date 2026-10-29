"""#17 — `failing_tests` names a wrong expectation by the TYPED baseline outcome, never the run code alone.

THE DEFECT (measured 2026-10-25 through `detective audit`). Both baselines put a test in
`failing_tests` when its run raised AssertionError — the run code ``"assertion"`` — one line after
computing the typed outcome (`trace_evidence.baseline_outcome`) from the same run. The run code cannot
see which pytest PHASE raised: a fixture that reaches the target and then asserts in its own setup is
pytest's ERROR, typed ``error`` in the ledger, and it was named a failed expectation anyway. Detective's
audit then printed ``⚠ FAILING NOW — test_errors_in_setup`` and asked "is the TEST's expectation wrong,
or is the CODE broken?" about a test that never reached its own assertions.

THE CONTRACT. A test is named in `failing_tests` only when it raised AssertionError AND pytest typed it
``failed`` (`baseline_failure_standing` → ``wrong_expectation``). An errored, skipped or expected-failure
test is still barred from attribution — inert, as before — and accused of nothing; a genuine wrong
expectation is still named.
"""

from __future__ import annotations

import ast
import os
import sys

import pytest

from Wesker.engine import baseline_failure_standing


@pytest.mark.parametrize(
    ("run_code", "outcome", "standing"),
    [
        ("assertion", "failed", "wrong_expectation"),
        (
            "assertion",
            "error",
            "not_an_expectation",
        ),  # the defect: a fixture's assertion
        ("assertion", "skipped", "not_an_expectation"),
        ("assertion", "xfailed", "not_an_expectation"),
        ("assertion", "a_future_category", "not_an_expectation"),
        ("exception", "failed", "not_failing"),  # barred without accusation, as before
        ("crash", "error", "not_failing"),
        ("timeout", "error", "not_failing"),
        (None, "passed", "not_failing"),
        (None, "skipped", "not_failing"),
    ],
)
def test_only_a_failed_assertion_of_the_test_itself_is_a_wrong_expectation(
    run_code, outcome, standing
):
    assert baseline_failure_standing(run_code, outcome) == standing


_TARGET = "def f(x):\n    if x > 0:\n        return x + 1\n    return x - 1\n"

_CONFTEST = """import pytest

from {mod} import f


@pytest.fixture
def broken_setup():
    f(1)
    assert False, "fixture setup is broken"
"""

_TESTS = """import pytest

from {mod} import f


def test_errors_in_setup(broken_setup):
    assert f(2) == 3


def test_wrong_expectation():
    assert f(2) == 99


@pytest.mark.xfail(reason="known", strict=False)
def test_expected_failure():
    assert f(-2) == 99


def test_passes():
    assert f(5) == 6
"""


def _live_profile(tmp_path, mod):
    from Wesker import engine
    from Wesker.ci import (
        discover_test_callables,
        resolve_original_func,
        run_with_live_suite,
        walk_functions,
    )
    from Wesker.filter import filter_categories

    (tmp_path / f"{mod}.py").write_text(_TARGET)
    (tmp_path / "conftest.py").write_text(_CONFTEST.format(mod=mod))
    (tmp_path / f"test_{mod}.py").write_text(_TESTS.format(mod=mod))
    for name in (mod, f"test_{mod}", "conftest"):
        sys.modules.pop(name, None)
    root = str(tmp_path)

    def body():
        src = os.path.join(root, f"{mod}.py")
        with open(src) as fh:
            node = dict(walk_functions(ast.parse(fh.read())))["f"]
        tests = discover_test_callables(root, f"{mod}.py", ["f"])
        return engine.run_function_profiling(
            node,
            f"{mod}.py::f",
            filter_categories(node),
            tests,
            resolve_original_func(src, "f"),
        )

    cwd = os.getcwd()
    try:
        os.chdir(root)
        return run_with_live_suite(root, body, target_files=[f"{mod}.py"])
    finally:
        os.chdir(cwd)


def test_an_errored_test_is_not_named_a_wrong_expectation_and_a_real_one_still_is(
    tmp_path,
):
    r = _live_profile(tmp_path, "typed_failing_mod")
    assert r is not None, "the live session did not run"
    typed = {
        ev.test_id.rsplit("::", 1)[-1]: ev.baseline_outcome for ev in r.trace_evidence
    }
    assert typed.get("test_errors_in_setup") == "error", typed
    assert typed.get("test_wrong_expectation") == "failed", typed
    named = [t.rsplit("::", 1)[-1] for t in r.failing_tests]
    assert "test_errors_in_setup" not in named, (
        "a fixture's setup assertion was named a wrong expectation"
    )
    assert "test_expected_failure" not in named
    assert named == ["test_wrong_expectation"], named
    # Still barred from attribution: no kill is credited to the errored test.
    assert not any(
        (k.get("test") or "").endswith("test_errors_in_setup") for k in r.killed_records
    )
