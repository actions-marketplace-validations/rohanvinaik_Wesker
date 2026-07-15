"""A mutant must be able to resolve the source module's globals — sibling
helpers, module constants, imports. Otherwise a function that calls a helper
raises NameError under every mutant, producing a false all-crash 100% that hides
whether the mutation's behavior was actually caught.
"""

from __future__ import annotations

import ast

from Wesker.engine import run_function_profiling
from Wesker.filter import filter_categories

# `target` calls the module-level helper `_double`. Under an empty mutant
# namespace, every mutant of `target` raises NameError('_double'); with the
# module globals seeded in, mutations change the value and are caught by the
# assertion instead.
_MODULE_SRC = """
def _double(x):
    return x * 2

def target(n):
    return _double(n) + 1

def test_target():
    assert target(3) == 7
"""


def test_mutant_resolves_module_level_helper():
    ns: dict = {}
    exec(_MODULE_SRC, ns)  # noqa: S102
    target = ns["target"]  # live func; __globals__ has _double
    test_target = ns[
        "test_target"
    ]  # its __globals__ is `ns`, so patching ns["target"] works

    tree = ast.parse(_MODULE_SRC)
    node = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "target"
    )
    cats = filter_categories(node)

    pr = run_function_profiling(node, "m.py::target", cats, [test_target], target)

    assert pr.total_mutants > 0
    # The load-bearing guarantee: kills are real assertion kills, not NameError
    # crashes from a missing helper.
    assertion_kills = [
        r for r in pr.killed_records if r.get("killed_by") == "assertion"
    ]
    assert assertion_kills, (
        "expected assertion kills once the mutant can resolve the module helper; "
        f"got killed_by counts {[r.get('killed_by') for r in pr.killed_records]}"
    )
