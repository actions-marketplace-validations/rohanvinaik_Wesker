"""#28: a test that profiles code must not recursively replay its own live baseline.

Cross-function audit removal exposed the loop through the old bare failing-on-baseline pass.
Exercise both public entry points in a subprocess so a regression cannot hang the outer suite.
"""

import subprocess
import sys
import types

import pytest

from Wesker import engine
from Wesker.ci import callable_test_id
from Wesker.engine import measurement_entry_disposition


def test_an_active_owner_is_a_refusal_even_when_its_id_is_zero():
    assert measurement_entry_disposition(0) == "nested_measurement"


def test_a_new_measurement_may_begin():
    assert measurement_entry_disposition(None) == "begin"


@pytest.mark.parametrize(
    "outer,inner",
    [
        ("run_function_profiling", "run_function_converged"),
        ("run_function_converged", "run_function_profiling"),
    ],
)
def test_a_baseline_cannot_recursively_enter_either_public_runner(
    tmp_path, outer, inner
):
    source = "def f(n):\n    return n + 1\n"
    target = tmp_path / "boundary_target.py"
    target.write_text(source)
    script = """
import ast
import sys
import types
from pathlib import Path
from Wesker import engine

path, outer_name, inner_name = sys.argv[1:]
source = Path(path).read_text()
module = types.ModuleType("boundary_target")
module.__file__ = path
sys.modules[module.__name__] = module
exec(compile(source, path, "exec"), module.__dict__)
node = ast.parse(source).body[0]

def test_engine():
    getattr(engine, inner_name)(node, path + "::f", set(), [], module.f, scope_tests=False)

result = getattr(engine, outer_name)(
    node, path + "::f", {engine.MutationCategory.VALUE}, [test_engine], module.f,
    scope_tests=False, budget_ms=1500, trace_budget_s=0.1, trace_session_budget_s=0.2,
)
assert not result.failing_tests, result.failing_tests
assert result.unscored_records, result
assert all(r["disposition"] == "nested_measurement" for r in result.unscored_records)
assert result.total_mutants == 0
assert not result.is_gateable
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(target), outer, inner],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_bounded_probe_reports_assertions_without_accusing_crashes(tmp_path):
    source = "def f(n):\n    return n + 1\n"
    target = tmp_path / "probe_target.py"
    target.write_text(source)
    module = types.ModuleType("probe_target")
    module.__file__ = str(target)
    # S102: compile a fixed fixture with a real source filename for mutant binding.
    exec(compile(source, str(target), "exec"), module.__dict__)  # noqa: S102
    calls = []

    def wrong():
        calls.append("wrong")
        assert module.f(1) == 3

    def broken():
        calls.append("broken")
        raise RuntimeError("unavailable fixture")

    assertions = []
    inert, compromised = engine._baseline_failures(
        [wrong, broken], module.f, "f", assertions=assertions
    )
    assert not compromised
    assert inert == {id(wrong), id(broken)}
    assert assertions == [callable_test_id(wrong)]
    assert calls == ["wrong", "broken"]
