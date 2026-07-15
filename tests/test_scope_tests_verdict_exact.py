"""Test-impact scoping must be verdict-EXACT, not merely fast.

Regression cover for a scoping defect that silently reported ~27% of Wesker's own
mutants (28.6% of Prism's) as survivors regardless of suite quality:

``executable_lines`` emitted only statement-START lines, while a mutator records its
fire site as the mutated NODE's line — a sub-expression line for any multi-line
statement. ``_trace_one`` intersects traced hits with that denominator, so those
lines never appeared in the coverage map; ``_tests_for`` then found no covering test
and evaluated the mutant against NOTHING, scoring it a survivor. The safe fallback
only fired for ``mutated_line is None``, never for "line the data cannot describe".
"""

import ast

from Wesker.line_coverage import executable_lines


def _fn(src: str) -> ast.FunctionDef:
    node = ast.parse(src).body[0]
    assert isinstance(node, ast.FunctionDef)
    return node


MULTILINE_SRC = '''
def f(items, flag):
    """doc"""
    if flag:
        return sum(
            x * 2
            for x in ("a", "b")
        )
    return max(
        len(items), 1
    )
'''


def test_executable_lines_span_multiline_statements():
    """The denominator must include EVERY line a statement occupies.

    A statement-start-only denominator drops the sub-expression lines CPython
    actually reports "line" events for, which is what orphaned mutants.
    """
    node = _fn(MULTILINE_SRC.strip())
    lines = executable_lines(node)
    # The genexp body/`for` clause and the continuation of the final return all
    # carry code, and a mutant can land on any of them.
    assert len(lines) >= 6
    assert max(lines) - min(lines) >= 5, f"denominator collapsed to {sorted(lines)}"


def test_every_mutant_line_is_in_the_denominator():
    """No mutant may sit on a line the coverage denominator cannot describe.

    This is the invariant that keeps scoping sound: if a mutated line is absent
    from ``executable_lines``, no coverage entry can ever mention it, so scoping
    would select zero tests and manufacture a false survivor.
    """
    from Wesker.engine import generate_mutants
    from Wesker.filter import filter_categories

    node = _fn(MULTILINE_SRC.strip())
    cats = filter_categories(node)
    lines = executable_lines(node)
    mutants = generate_mutants(node, cats, max_per_category=0)
    assert mutants, "expected mutants for this function"
    orphans = [
        (m.category.value, m.mutated_line)
        for m in mutants
        if m.mutated_line not in lines
    ]
    assert not orphans, f"mutants on lines outside the denominator: {orphans}"


def test_docstring_line_excluded_from_denominator():
    node = _fn(MULTILINE_SRC.strip())
    lines = executable_lines(node)
    assert node.lineno not in lines, "the def line is not reachable behavior"


def test_converged_scoping_default_is_pinned():
    """Pin the converged path's scoping default so it cannot flip unnoticed.

    This asserts the STATUS QUO (off = this path's historical behaviour), not that
    off is correct. On prism/economics.py::analyze the two settings disagree 130 vs 2
    kills, and the unscoped number is inflated: 107 "assertion kills" are credited to
    a test in another module that never references the function and fails the same way
    on the UNMUTATED original. Neither setting is trustworthy until a test that fails
    on the original is barred from being credited with a kill. Whoever fixes that
    should revisit this default deliberately — hence the pin.
    """
    import inspect

    from Wesker.engine import run_function_converged

    sig = inspect.signature(run_function_converged)
    assert sig.parameters["scope_tests"].default is False, (
        "the converged path's scope_tests default changed — revisit the "
        "baseline-failure kill-attribution defect before trusting either setting"
    )


def test_scoped_and_unscoped_verdicts_agree():
    """The whole justification for scoping: identical verdicts, less work.

    Profiles a real function against a suite that kills every mutant, both scoped
    and unscoped. Any divergence means scoping invented survivors.
    """
    from Wesker.engine import MutationCategory, run_function_profiling

    src = (
        "def scoreit(a, b, flag):\n"
        '    """doc"""\n'
        "    if flag:\n"
        "        return sum(\n"
        "            v * 2\n"
        "            for v in (a, b)\n"
        "        )\n"
        "    return max(\n"
        "        a, b\n"
        "    )\n"
    )
    node = _fn(src)
    ns: dict = {}
    exec(compile(ast.parse(src), "<scoretest>", "exec"), ns)
    original = ns["scoreit"]

    def test_flag_true():
        assert scoreit(1, 2, True) == 6  # noqa: F821

    def test_flag_false():
        assert scoreit(1, 2, False) == 2  # noqa: F821

    def test_flag_true_other():
        assert scoreit(3, 4, True) == 14  # noqa: F821

    tests = [test_flag_true, test_flag_false, test_flag_true_other]
    for t in tests:
        t.__globals__["scoreit"] = original

    cats = {MutationCategory.VALUE, MutationCategory.ARITHMETIC, MutationCategory.SWAP}
    unscoped = run_function_profiling(
        node,
        "<scoretest>::scoreit",
        cats,
        tests,
        original,
        max_per_category=0,
        scope_tests=False,
    )
    scoped = run_function_profiling(
        node,
        "<scoretest>::scoreit",
        cats,
        tests,
        original,
        max_per_category=0,
        scope_tests=True,
    )
    assert scoped.total_mutants == unscoped.total_mutants
    assert scoped.total_killed == unscoped.total_killed, (
        f"scoping changed the verdict: {unscoped.total_killed} killed unscoped vs "
        f"{scoped.total_killed} scoped — scoping is not verdict-exact"
    )
