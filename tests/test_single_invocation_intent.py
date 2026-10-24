"""W#47: choose call arguments before entry; a body TypeError must never retry.

The bounded runner accepts patched pytest calls and unpatched inline injection.
These live-callable/worker boundaries cannot be literal-pinned. Distinct obligations
are body failure, mutant failure, zero-argument compatibility, callable binding,
unavailable signatures, wrapper signatures and original-control attribution.
"""

from __future__ import annotations

import ast
import functools

import pytest

from Wesker import engine


def test_body_type_error_is_not_swallowed_by_an_empty_retry():
    calls = []
    mutant = object()

    def case(fn=None):
        calls.append(fn)
        if fn is not None:
            raise TypeError("raised after entering the test body")

    outcome = engine._run_test_with_timeout(case, mutant, False, 1000)

    assert calls == [mutant]
    assert outcome == "crash"


def test_mutant_type_error_cannot_be_retried_without_the_mutant():
    calls = []
    mutant_calls = []

    def mutant():
        mutant_calls.append("entered")
        raise TypeError("raised by the injected mutant")

    def case(fn=None):
        calls.append(fn)
        if fn is not None:
            fn()

    outcome = engine._run_test_with_timeout(case, mutant, False, 1000)

    assert calls == [mutant]
    assert mutant_calls == ["entered"]
    assert outcome == "crash"


def test_unpatched_zero_argument_test_still_runs_once():
    calls = []

    def case():
        calls.append("entered")

    assert engine._run_test_with_timeout(case, object(), False, 1000) is None
    assert calls == ["entered"]


@pytest.mark.parametrize("shape", ["bound_method", "callable_object", "partial"])
def test_injected_argument_binding_handles_supported_callable_shapes(shape):
    calls = []
    mutant = object()

    class Case:
        def run(self, fn=None):
            calls.append(fn)

        __call__ = run

    def with_prefix(prefix, fn=None):
        assert prefix == "bound"
        calls.append(fn)

    case = {
        "bound_method": Case().run,
        "callable_object": Case(),
        "partial": functools.partial(with_prefix, "bound"),
    }[shape]

    assert engine._run_test_with_timeout(case, mutant, False, 1000) is None
    assert calls == [mutant]


@pytest.mark.parametrize("signature_error", [TypeError, ValueError])
def test_unavailable_signature_does_not_authorize_an_empty_retry(signature_error):
    calls = []
    mutant = object()

    class Opaque:
        @property
        def __signature__(self):
            raise signature_error("signature unavailable")

        def __call__(self, fn=None):
            calls.append(fn)
            if fn is not None:
                raise TypeError("body failure")

    assert engine._run_test_with_timeout(Opaque(), mutant, False, 1000) == "crash"
    assert calls == [mutant]


def test_wrapper_uses_its_actual_call_signature():
    calls = []

    def fixture_taking_test(first, second):
        raise AssertionError("the original fixture signature is not invoked")

    @functools.wraps(fixture_taking_test)
    def fixture_bound_wrapper():
        calls.append("entered")

    assert (
        engine._run_test_with_timeout(fixture_bound_wrapper, object(), False, 1000)
        is None
    )
    assert calls == ["entered"]


@pytest.mark.parametrize("patched", [False, True])
def test_zero_argument_body_type_error_is_a_single_crash(patched):
    calls = []

    def case():
        calls.append("entered")
        raise TypeError("body failure")

    assert engine._run_test_with_timeout(case, object(), patched, 1000) == "crash"
    assert calls == ["entered"]


def test_neither_call_form_binding_cannot_enter_the_body():
    calls = []

    def case(first, second):
        calls.append("entered")

    assert engine._run_test_with_timeout(case, object(), False, 1000) == "crash"
    assert calls == []


@pytest.mark.parametrize("full_matrix", [False, True])
def test_evaluate_mutant_retains_the_crash_and_its_separate_original_control(
    full_matrix,
):
    source = "def single_invocation_subject():\n    return 7\n"
    changed = "def single_invocation_subject():\n    raise TypeError('mutant')\n"
    namespace = {}
    # S102: construct an original outside live module bindings so injection is real.
    exec(compile(source, "<single-invocation-original>", "exec"), namespace)  # noqa: S102
    original = namespace["single_invocation_subject"]
    mutant = engine.Mutant(
        category=engine.MutationCategory.VALUE,
        original_node=ast.parse(source).body[0],
        mutated_node=ast.parse(changed).body[0],
        description="TypeError from the injected mutant",
    )
    calls = []

    def case(fn=None):
        calls.append(fn)
        if fn is not None:
            fn()

    result = engine.evaluate_mutant(
        mutant,
        [case],
        original,
        qualname="single_invocation_subject",
        record_all_killers=full_matrix,
    )

    assert result.killed
    assert result.killed_by == "crash"
    assert result.entered is True
    assert result.tests_run == 1
    # One mutant observation and one explicit original control, never an empty retry.
    assert len(calls) == 2
    assert callable(calls[0]) and calls[0] is not original
    assert calls[1] is original
