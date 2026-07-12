"""Survivor records carry a concrete diff of the mutated node, so downstream
oracle synthesis knows the specific change (e.g. ``n >= 5`` -> ``n > 5``), not
just the generic category description.
"""

from __future__ import annotations

import ast

from Wesker.engine import _mutant_diff, generate_mutants, run_function_profiling
from Wesker.filter import filter_categories

_SRC = """
def in_range(n):
    return n >= 5

def test_runs():
    assert in_range(7) is not None
"""


def test_mutant_diff_shows_the_change():
    node = ast.parse("def f(n):\n return n >= 5").body[0]
    diffs = [_mutant_diff(m) for m in generate_mutants(node, filter_categories(node))]
    assert any(d.startswith("- ") and "\n+ " in d for d in diffs)
    assert any(">=" in d for d in diffs)


def test_survivor_records_include_diff_summary():
    ns: dict = {}
    exec(_SRC, ns)  # noqa: S102
    node = next(n for n in ast.parse(_SRC).body if isinstance(n, ast.FunctionDef) and n.name == "in_range")
    pr = run_function_profiling(
        node, "m::in_range", filter_categories(node), [ns["test_runs"]], ns["in_range"]
    )
    diffs = [r.get("diff_summary", "") for r in pr.survivor_records]
    assert any(">=" in d for d in diffs), f"no boundary diff in survivors: {diffs}"
