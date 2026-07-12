"""Tests for the pytest discovery backend — in particular that @parametrize
cases are bound into runnable in-process callables (not skipped), which is what
lets Wesker consume idiomatic parametrized suites.
"""

from __future__ import annotations

import textwrap

from Wesker.pytest_discovery import collect_pytest_callables


def _write(tmp_path, name: str, body: str) -> None:
    # Unique module name per test: nested pytest.main imports test modules by
    # name into sys.modules, so a shared filename would collide across cases.
    (tmp_path / f"test_{name}.py").write_text(textwrap.dedent(body))


def test_parametrized_test_binds_one_callable_per_case(tmp_path):
    _write(
        tmp_path,
        "param",
        """
        import pytest

        @pytest.mark.parametrize("x, expected", [(1, 1), (2, 2), (3, 99)])
        def test_identity(x, expected):
            assert x == expected
        """,
    )
    callables = collect_pytest_callables(str(tmp_path))
    assert callables is not None
    assert len(callables) == 3  # one bound callable per parametrize case

    # Each runs in-process; a value mismatch raises AssertionError (an
    # "assertion" kill for Wesker), NOT a TypeError (a false "crash" kill).
    outcomes = []
    for c in callables:
        try:
            c()
            outcomes.append("pass")
        except AssertionError:
            outcomes.append("assertion")
    assert outcomes == ["pass", "pass", "assertion"]


def test_fixture_requiring_test_is_skipped_plain_kept(tmp_path):
    _write(
        tmp_path,
        "fixture",
        """
        def test_needs_fixture(tmp_path):
            assert tmp_path.exists()

        def test_plain():
            assert True
        """,
    )
    callables = collect_pytest_callables(str(tmp_path))
    assert callables is not None
    names = [getattr(c, "__name__", "") for c in callables]
    assert any("test_plain" in n for n in names)
    assert not any("needs_fixture" in n for n in names)


def test_zero_arg_test_runs_directly(tmp_path):
    _write(
        tmp_path,
        "plain",
        """
        def test_truth():
            assert 1 + 1 == 2
        """,
    )
    callables = collect_pytest_callables(str(tmp_path))
    assert callables is not None
    assert len(callables) == 1
    callables[0]()  # runs without raising
