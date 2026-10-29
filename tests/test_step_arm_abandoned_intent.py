"""An abandonment that lands as a step budget opens leaves no budget open behind it (W#29, W#27).

THE WINDOW. `_StepArm.__enter__` opens `monitoring.step_budget`, a generator context manager. When
`next()` returns inside its `__enter__`, the budget is open (`_active` set, an exclusive JUMP
subscription live), and the check after that call is one an `interrupt.abandon` injection can land
on. `Abandoned` is a `BaseException`, so the arm's `except Exception` (meant for a budget that cannot
open) let it through. No `__exit__` was ever going to run for a `with arm:` that never entered. An
open budget refuses every later one as "nested", and `_StepArm` turns that refusal into an uncounted,
wall-only run, so every later measurement silently lost its deterministic budget. CPython usually
closed the orphaned generator when its frame died, but only once nothing held the exception: a
traceback kept by pytest, a log record or a frame cycle keeps it open. The arm now closes what it
opened before re-raising, whoever holds the traceback.

PINNED with the REAL budget: the injection is played by a wrapper that opens the real
`step_budget` and then raises `Abandoned`, exactly where the injection lands. A real thread would
make where it lands depend on the interpreter (the house rule in test_bounded_join_intent).
"""

from __future__ import annotations

import sys

import pytest

from Wesker import engine, monitoring
from Wesker.interrupt import Abandoned


def _looping(n: int) -> int:
    total = 0
    for i in range(n):
        total += i
    return total


@pytest.fixture(autouse=True)
def _cleanup_monitoring():
    yield
    sys.monitoring.set_events(monitoring.tool_id(), 0)
    monitoring.release_monitoring_tool()


def test_an_abandonment_as_the_budget_opens_closes_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_step_budget = monitoring.step_budget

    class _OpensThenAbandoned:
        def __init__(self, codes, cap):
            self._cm = real_step_budget(codes, cap)

        def __enter__(self):
            self._cm.__enter__()
            raise Abandoned

        def __exit__(self, *exc):
            return self._cm.__exit__(*exc)

    monkeypatch.setattr(monitoring, "step_budget", _OpensThenAbandoned)
    arm = engine._StepArm((_looping.__code__,), 10)
    # Hold the exception, as pytest's own record, a logged error or a frame cycle would: its
    # traceback keeps the opened budget's generator alive, so refcounting cannot quietly close
    # it, and only the arm's own close can.
    with pytest.raises(Abandoned) as held:
        arm.__enter__()
    assert not monitoring.is_budget_active(), (
        "the budget the abandonment interrupted is closed"
    )
    assert not arm.counted
    del held

    monkeypatch.setattr(monitoring, "step_budget", real_step_budget)
    with real_step_budget((_looping.__code__,), 1_000) as count:
        _looping(5)
    assert count.iterations > 0, (
        "a later budget opens and counts: nothing was left nested"
    )


def test_a_budget_that_cannot_open_still_degrades_to_an_uncounted_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ordinary refusal keeps its meaning: an Exception while opening is not a verdict."""

    class _Refuses:
        """Refuses where the real one does: on entry, like `step_budget`'s nesting check."""

        def __init__(self, codes, cap):
            pass

        def __enter__(self):
            raise RuntimeError("step budgets do not nest: one is already open")

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(monitoring, "step_budget", _Refuses)
    with engine._StepArm((_looping.__code__,), 10) as arm:
        _looping(3)
    assert not arm.counted
    assert not arm.stopped
