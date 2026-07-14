"""Per-test line coverage of a target function — the second completeness axis.

Mutation testing answers "does a test *distinguish* a behavioral change?"; line
coverage answers the orthogonal "does any test *reach* this line at all?". A suite
can kill every killable mutant yet leave a line no test ever executes (a line no
mutant happened to touch), so a suite is only *complete* when it is both
mutant-complete AND line-complete, and only *minimal* when set-cover runs over the
union of both matrices.

This is measured in a single traced baseline pass over the UNMUTATED function —
the mutation loop stays untraced (and fast). ``executable_lines`` is the static
denominator (which lines *could* run); ``trace_line_coverage`` is the dynamic
numerator (which lines each test *did* run), keyed identically to the kill matrix
so the two feed the same set-cover.
"""

from __future__ import annotations

import ast
import contextlib
import io
import sys
from typing import Any, Callable


def executable_lines(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[int]:
    """The statement lines of a function body — the line-coverage denominator.

    A line is *executable* when a statement begins on it; that is exactly the
    granularity ``sys.settrace`` reports a "line" event for, so the covered set
    (from tracing) and this set are keyed the same way. The ``def`` line itself and
    a leading docstring are excluded: neither is behavior a test can meaningfully
    "reach".
    """
    body = list(func_node.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]  # drop a leading docstring
    lines: set[int] = set()
    for stmt in body:
        for descendant in ast.walk(stmt):
            if isinstance(descendant, ast.stmt):
                lines.add(descendant.lineno)
    return lines


def _trace_one(
    test_fn: Callable[..., None], target_file: str, exec_lines: set[int]
) -> set[int]:
    """Lines within ``exec_lines`` that ``test_fn()`` executes in ``target_file``.

    A local trace function is returned only for frames whose code lives in the
    target file, so unrelated library frames are never traced. A test that raises
    on the original still contributes the lines it reached before raising — partial
    coverage is real coverage.
    """
    hits: set[int] = set()

    def local(frame, event, _arg):
        if event == "line":
            hits.add(frame.f_lineno)
        return local

    def dispatch(frame, event, _arg):
        if event == "call" and frame.f_code.co_filename == target_file:
            return local
        return None

    previous = sys.gettrace()
    sys.settrace(dispatch)
    try:
        test_fn()
    except BaseException:  # noqa: BLE001 — a failing/raising test still reached lines
        pass
    finally:
        sys.settrace(previous)
    return hits & exec_lines


def failing_on_baseline(
    test_functions: list[Callable[..., None]], original_func: Callable[..., Any]
) -> list[str]:
    """Test names whose assertion FAILS on the UNMUTATED function — a test that does
    not hold on correct code.

    Only an ``AssertionError`` counts: it means the test's own expectation is wrong
    for the current code (a stale golden, or a real regression the test is catching).
    Other exceptions (a missing fixture arg, an import error) are ambiguous under the
    direct-call contract and are NOT flagged, to avoid false accusations. Such a test
    is surfaced for a human to investigate — never proposed for automatic deletion,
    since it may be the only thing catching a genuine bug."""
    if getattr(original_func, "__code__", None) is None:
        return []
    failing: list[str] = []
    # Isolate each discovered test's own stdout/stderr (argparse usage banners from
    # a `pytest.raises(SystemExit)` CLI test, prints, logging) so consumer-test
    # side-effects never pollute the engine's machine-readable output — the same
    # isolation evaluate_mutant's runner applies.
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        for test_fn in test_functions:
            try:
                test_fn()
            except AssertionError:
                failing.append(getattr(test_fn, "__name__", "unknown"))
            except BaseException:  # noqa: BLE001,S110 — ambiguous (fixtures/imports); not a wrong assertion
                pass
    return failing


def trace_line_coverage(
    test_functions: list[Callable[..., None]],
    original_func: Callable[..., Any],
    exec_lines: set[int],
) -> dict[str, list[int]]:
    """Map each test name to the target lines it covers, over the UNMUTATED function.

    Keyed by ``test_fn.__name__`` to match the kill matrix, so a caller can run
    set-cover over ``kill_matrix`` and this together. The target file is taken from
    the original function's own code object — authoritative and absolute, the same
    identity ``evaluate_mutant`` patches against — so coverage attributes to the
    real function under test, not a same-named sibling. Empty when the function's
    code object is unavailable (degrades to "no line data", never an error).
    """
    code = getattr(original_func, "__code__", None)
    target_file = getattr(code, "co_filename", None)
    if not target_file or not exec_lines:
        return {}
    coverage: dict[str, list[int]] = {}
    # Isolate consumer-test stdout/stderr during the traced baseline pass (see
    # failing_on_baseline) so a test's prints/argparse banners never leak into the
    # engine's output.
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        for test_fn in test_functions:
            name = getattr(test_fn, "__name__", "unknown")
            covered = _trace_one(test_fn, target_file, exec_lines)
            # Union across duplicate test names (parametrized cases share a __name__).
            merged = set(coverage.get(name, ())) | covered
            coverage[name] = sorted(merged)
    return coverage
