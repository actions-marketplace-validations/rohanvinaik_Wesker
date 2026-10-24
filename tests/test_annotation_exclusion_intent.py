"""Intent test: Option A (Wesker#30) — exclude annotation subtrees from mutant universe.

Pins:
1. Annotations in parameters, returns, and variable annotations are skipped.
2. Behavioral elements on definition lines (defaults, decorators) are preserved.
3. Total over AST: count_targets and generated mutants stay 100% aligned.
4. step_budget_verdict generates zero ARITHMETIC mutants.
"""

from __future__ import annotations

import ast
import inspect

from Wesker.engine import (
    MutationCategory,
    _count_targets,
    generate_mutants,
)
from Wesker.monitoring import step_budget_verdict


def test_step_budget_verdict_has_no_annotation_mutants() -> None:
    """step_budget_verdict's cap: int | None must not generate ARITHMETIC mutants (#30)."""
    func_node = ast.parse(inspect.getsource(step_budget_verdict)).body[0]
    assert isinstance(func_node, ast.FunctionDef)

    arith_mutants = list(generate_mutants(func_node, [MutationCategory.ARITHMETIC]))
    assert len(arith_mutants) == 0

    arith_targets = _count_targets(func_node, MutationCategory.ARITHMETIC)
    assert arith_targets == 0


def test_annotations_excluded_future_annotations() -> None:
    """Under `from __future__ import annotations`, annotations are not mutated but defaults are."""
    code = """
from __future__ import annotations

def calculate(x: int | None, factor: float = 1.0 + 2.0) -> int | None:
    limit: int | None = 100 + 50
    return limit
"""
    mod = ast.parse(code)
    func_node = next(n for n in mod.body if isinstance(n, ast.FunctionDef))

    # Arithmetic mutants should fire on default (1.0 + 2.0) and value assignment (100 + 50),
    # but NEVER on `int | None`.
    mutants = list(generate_mutants(func_node, [MutationCategory.ARITHMETIC]))
    dims = [m.dimension for m in mutants]
    assert "ARITHMETIC:BitOr" not in dims
    assert len(mutants) == 2  # 1.0 + 2.0 and 100 + 50

    targets = _count_targets(func_node, MutationCategory.ARITHMETIC)
    assert targets == len(mutants)


def test_annotations_excluded_lazy_annotations_and_decorators() -> None:
    """Plain 3.14 function with decorators, type aliases, and return annotations."""
    code = """
@decorator(10 + 20)
def process[T: int | str](item: T, step: int = 5) -> tuple[T, int]:
    val: int | str = item
    return (val, step)
"""
    mod = ast.parse(code)
    func_node = next(n for n in mod.body if isinstance(n, ast.FunctionDef))

    # Decorator expression `10 + 20` must be mutated
    mutants = list(generate_mutants(func_node, [MutationCategory.ARITHMETIC]))
    assert len(mutants) == 1
    assert mutants[0].dimension == "ARITHMETIC:Add"

    targets = _count_targets(func_node, MutationCategory.ARITHMETIC)
    assert targets == 1
