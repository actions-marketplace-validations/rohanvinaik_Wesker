"""Tests for owned sys.monitoring subscriptions in Wesker.monitoring (W#32).

Verifies:
1. Bitmask derivation as active subscription union.
2. Direct target frame injection without stack distortion.
3. Run-token enforcement and evidence freezing after token retirement.
4. Multiplexing of passive observers and rejection of exclusive overlaps.
5. Both cleanup orders preserving remaining subscriptions.
6. Transactional subscription rollback on partial failure.
7. Version-aware release_monitoring_tool teardown.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from types import CodeType, SimpleNamespace
from typing import Any

import pytest

from Wesker import monitoring
from Wesker.monitoring import (
    ActiveSubscriptionsError,
    MonitoringUnavailable,
    SubscriptionOverlapRefused,
    allocate_run_token,
    is_run_token_active,
    release_monitoring_tool,
    retire_run_token,
    subscribe,
    tool_id,
)


def _target_fn(a: int, b: str) -> str:
    return f"{b}:{a * 2}"


def _target_loop(n: int) -> int:
    total = 0
    for i in range(n):
        total += i
    return total


def test_bitmask_derived_as_union_and_cleaned_accurately() -> None:
    code = _target_fn.__code__
    tool = tool_id()

    h1 = subscribe([code], sys.monitoring.events.PY_START, lambda *a, **k: None)
    assert sys.monitoring.get_local_events(tool, code) == sys.monitoring.events.PY_START

    h2 = subscribe([code], sys.monitoring.events.PY_RETURN, lambda *a, **k: None)
    assert sys.monitoring.get_local_events(tool, code) == (
        sys.monitoring.events.PY_START | sys.monitoring.events.PY_RETURN
    )

    # Order 1: close h1 first, h2 remains active
    h1.close()
    assert (
        sys.monitoring.get_local_events(tool, code) == sys.monitoring.events.PY_RETURN
    )

    # Close h2: mask resets to 0
    h2.close()
    assert sys.monitoring.get_local_events(tool, code) == 0


def test_cleanup_order_reverse_preserves_remaining_subscription() -> None:
    code = _target_fn.__code__
    tool = tool_id()

    h1 = subscribe([code], sys.monitoring.events.PY_START, lambda *a, **k: None)
    h2 = subscribe([code], sys.monitoring.events.PY_RETURN, lambda *a, **k: None)

    # Order 2: close h2 first, h1 remains active
    h2.close()
    assert sys.monitoring.get_local_events(tool, code) == sys.monitoring.events.PY_START

    h1.close()
    assert sys.monitoring.get_local_events(tool, code) == 0


def test_target_frame_injected_authentically_without_dispatcher_distortion() -> None:
    code = _target_fn.__code__
    observed_locals: list[dict[str, Any]] = []

    def on_start(
        frame_code: CodeType,
        offset: int,
        frame: Any = None,
        run_token: int | None = None,
    ) -> None:
        assert frame_code is code
        assert frame is not None
        assert frame.f_code is code
        observed_locals.append(dict(frame.f_locals))

    with subscribe([code], sys.monitoring.events.PY_START, on_start):
        result = _target_fn(7, "val")
        assert result == "val:14"

    assert len(observed_locals) == 1
    assert observed_locals[0] == {"a": 7, "b": "val"}


def test_run_token_enforcement_and_evidence_freezing() -> None:
    code = _target_fn.__code__
    calls: list[int] = []
    token = allocate_run_token()

    def on_start(
        frame_code: CodeType,
        offset: int,
        frame: Any = None,
        run_token: int | None = None,
    ) -> None:
        calls.append(frame.f_locals["a"])

    with subscribe([code], sys.monitoring.events.PY_START, on_start, run_token=token):
        _target_fn(1, "x")
        assert calls == [1]

        # Retire token (simulating timeout or completion)
        retire_run_token(token)
        assert not is_run_token_active(token)

        # Subsequent call with retired token is dropped immediately
        _target_fn(2, "x")
        assert calls == [1]


def test_passive_observers_multiplex_deterministically() -> None:
    code = _target_fn.__code__
    events_seen: list[str] = []

    def cb1(*a, **k):
        events_seen.append("cb1")

    def cb2(*a, **k):
        events_seen.append("cb2")

    with (
        subscribe([code], sys.monitoring.events.PY_START, cb1),
        subscribe([code], sys.monitoring.events.PY_START, cb2),
    ):
        _target_fn(3, "test")

    assert events_seen == ["cb1", "cb2"]


def test_exclusive_overlap_refused() -> None:
    code = _target_loop.__code__

    with (
        subscribe([code], sys.monitoring.events.JUMP, lambda *a: None, exclusive=True),
        pytest.raises(SubscriptionOverlapRefused, match="conflicting exclusive"),
    ):
        subscribe(
            [code],
            sys.monitoring.events.JUMP,
            lambda *a: None,
            exclusive=True,
        )


def test_teardown_requires_zero_active_subscriptions() -> None:
    code = _target_fn.__code__
    h = subscribe([code], sys.monitoring.events.PY_START, lambda *a, **k: None)
    with pytest.raises(ActiveSubscriptionsError, match="active subscriptions"):
        release_monitoring_tool()
    h.close()

    # With zero active subscriptions, release succeeds
    release_monitoring_tool()
    assert monitoring._tool is None


def test_broker_token_lifecycle_can_be_observed_without_deadlocking() -> None:
    """W#32: observing the broker must not reacquire a non-reentrant token lock.

    Keep the hostile subscription in a subprocess: a regression must fail with a
    bounded timeout instead of hanging the test runner and every following gate.
    """
    program = """
import sys
from Wesker import monitoring as m

token = m.allocate_run_token()
lines = []
handle = m.subscribe(
    [], sys.monitoring.events.LINE,
    lambda code, line, **kw: lines.append(line),
    run_token=token, selectors=[m.__file__],
)
try:
    assert m.is_run_token_active(token)
    m.retire_run_token(token)
    assert not m.is_run_token_active(token)
finally:
    handle.close()
assert lines
assert sys.monitoring.get_events(m.tool_id()) == 0
m.release_monitoring_tool()
print('observed-and-released')
"""
    result = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "observed-and-released\n"


def test_retirement_during_dispatch_prevents_later_delivery() -> None:
    """W#32: admission is checked at delivery, not only when the callback list is built."""
    token = allocate_run_token()
    calls: list[str] = []

    def retire(*args, **kwargs):
        retire_run_token(token)

    with (
        subscribe([_target_fn.__code__], sys.monitoring.events.PY_START, retire),
        subscribe(
            [_target_fn.__code__],
            sys.monitoring.events.PY_START,
            lambda *a, **k: calls.append("late"),
            run_token=token,
        ),
    ):
        assert _target_fn(7, "x") == "x:14"
    assert calls == []


def test_observer_failure_is_reported_by_owner_without_crashing_target() -> None:
    """W#32: failed observation is neither a target failure nor a successful empty trace."""

    def broken(*args, **kwargs):
        raise ValueError("observer failed")

    with (
        pytest.raises(MonitoringUnavailable, match="observer_failed"),
        subscribe([_target_fn.__code__], sys.monitoring.events.PY_START, broken),
    ):
        assert _target_fn(7, "x") == "x:14"
    assert sys.monitoring.get_local_events(tool_id(), _target_fn.__code__) == 0


def test_retirement_refuses_evidence_with_an_observer_still_inflight() -> None:
    """W#32: retiring a token cannot cancel an observer already inside user code."""
    entered = threading.Event()
    release = threading.Event()
    token = allocate_run_token()

    def held(*args, **kwargs):
        entered.set()
        release.wait(2)

    handle = subscribe(
        [_target_fn.__code__], sys.monitoring.events.PY_START, held, run_token=token
    )
    worker = threading.Thread(target=_target_fn, args=(1, "x"))
    try:
        worker.start()
        assert entered.wait(2)
        retire_run_token(token)
        handle.close()
        with pytest.raises(MonitoringUnavailable, match="observation_inflight"):
            handle.check()
    finally:
        retire_run_token(token)
        release.set()
        worker.join(2)
        handle.close()
    assert not worker.is_alive()
    with pytest.raises(MonitoringUnavailable, match="observation_inflight"):
        handle.check()


def test_cancellation_during_delivery_admission_cleans_its_reservation() -> None:
    """An interrupt after reservation must enter cleanup, before any observer runs."""
    from Wesker.interrupt import Abandoned

    class InterruptedAdmission(set):
        def add(self, value):
            super().add(value)
            raise Abandoned

    calls = []
    handle = subscribe(
        [_target_fn.__code__],
        sys.monitoring.events.PY_START,
        lambda *a, **k: calls.append(True),
    )
    handle.sub.observation.inflight = InterruptedAdmission()
    try:
        with pytest.raises(Abandoned):
            _target_fn(1, "x")
        assert not handle.sub.observation.inflight
        assert calls == []
    finally:
        handle.close()
    handle.check()


@pytest.mark.parametrize(
    ("event", "dispatch", "args"),
    [
        (sys.monitoring.events.PY_START, monitoring._dispatch_py_start, (0,)),
        (sys.monitoring.events.PY_RETURN, monitoring._dispatch_py_return, (0, None)),
        (sys.monitoring.events.LINE, monitoring._dispatch_line, (1,)),
        (
            sys.monitoring.events.PY_UNWIND,
            monitoring._dispatch_py_unwind,
            (0, ValueError()),
        ),
    ],
)
def test_rejected_threads_do_not_materialize_target_frames(
    monkeypatch, event, dispatch, args
) -> None:
    """Ambient runaway threads must be rejected before frame allocation or observer work."""

    def forbidden_frame(*args):
        pytest.fail("a rejected thread requested a target frame")

    monkeypatch.setattr(
        monitoring,
        "sys",
        SimpleNamespace(monitoring=sys.monitoring, _getframe=forbidden_frame),
    )
    with subscribe(
        [_target_fn.__code__],
        event,
        lambda *a, **k: pytest.fail("a rejected thread reached the observer"),
        thread_filter=lambda tid: False,
    ):
        dispatch(_target_fn.__code__, *args)
