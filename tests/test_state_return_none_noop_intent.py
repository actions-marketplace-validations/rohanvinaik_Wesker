"""Intent: STATE's return_none never emits the original program as a mutant (2026-10-25).

`_StateMutator.visit_Return` targeted every return with a value, and `return None` has one in the
AST (`Constant(None)`), so it rewrote `return None` to `return None` — a mutant byte-identical to
the original. It surfaced in Detective as a survivor with an EMPTY diff (`STATE_bde50f1f [STATE]:`)
that no test can kill and no reader can act on; TCE runs at one site only, so nothing pruned it.
An existing `return None` is not a behavioural question for this operator, so it is not a target:
neither a recorded dimension nor a generated mutant.
"""

from __future__ import annotations

import ast

from Wesker.engine import (
    MutationCategory,
    _record_state_dimensions,
    generate_mutants,
)


def _state_mutants(src: str):
    fn = ast.parse(src).body[0]
    return fn, list(generate_mutants(fn, {MutationCategory.STATE}))


def test_an_existing_return_none_is_not_rewritten_to_itself():
    fn, mutants = _state_mutants(
        "def f(x):\n    if x:\n        return None\n    return x + 1\n"
    )
    original = ast.dump(fn)
    assert len(mutants) == 1
    assert all(ast.dump(m.mutated_node) != original for m in mutants)


def test_a_function_whose_only_return_is_none_has_no_return_none_target():
    fn, mutants = _state_mutants("def f(x):\n    print(x)\n    return None\n")
    assert mutants == []
    assert _record_state_dimensions(fn, "return_none") == []


def test_a_parenthesised_none_is_the_same_constant():
    _, mutants = _state_mutants("def f(x):\n    return (None)\n")
    assert mutants == []


def test_a_bare_return_stays_excluded():
    _, mutants = _state_mutants("def f(x):\n    if x:\n        return\n    return 1\n")
    assert len(mutants) == 1


def test_dimensions_and_mutants_agree_one_to_one():
    src = (
        "def f(x):\n"
        "    if x is None:\n"
        "        return None\n"
        "    if x < 0:\n"
        "        return -x\n"
        "    return x\n"
    )
    fn, mutants = _state_mutants(src)
    assert len(_record_state_dimensions(fn, "return_none")) == len(mutants) == 2
