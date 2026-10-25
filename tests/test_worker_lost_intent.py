"""Intent: a worker whose bootstrap dies before it signals its start is named, never waited on forever
(W#29).

THE DEFECT, measured on Wesker's whole-codebase CI run (6ba533d, 2026-10-25). The job timed out at
180 minutes. Every all-thread dump from 14:57 to 17:27 showed the main thread here and no other
thread alive:

    threading.py:1011 in start  ->  self._started.wait()
    engine.py:8058 in _run_test_with_timeout  <- _measure_original_step_in_place <- evaluate_mutant

It reproduced on Linux CPython 3.14.9 under a diagnostic that bounds the wait (7e61cd3, the same two
files, twice): the worker's OS thread had already ended, `ident=None`, before `_set_ident()`, its
bootstrap's first line. `Thread.start()` waits on `_started` with no timeout. A bootstrap that ends
before setting it leaves that wait unbounded, and a pending `SystemExit` ends it with no trace at all,
because CPython's thread runner swallows it silently.

THE RULING. `JoinedWorker.start()` observes the end instead of timing it. The entry callable
CPython's bootstate holds is released only when the thread's run is over, and a weakref records the
release through a C-level callback. A start whose thread ended unsignalled raises `WorkerLost`
(named, a BaseException), and the dead thread is taken out of `threading._limbo`. A healthy start
returns exactly as `Thread.start()` does.
"""

from __future__ import annotations

import contextlib
import ctypes
import io
import sys
import threading
import time

import pytest

from Wesker.interrupt import JoinedWorker, WorkerLost

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="sys.monitoring")


class _Stop(BaseException):
    pass


@contextlib.contextmanager
def _in_every_new_bootstrap(action):
    """Run ``action(tid)`` at the PY_START of the next thread's ``_bootstrap_inner``, before
    ``_started`` is set: the window W#29's worker died in."""
    mon = sys.monitoring
    tool = next((i for i in range(6) if mon.get_tool(i) is None), None)
    if tool is None:
        pytest.skip("no free sys.monitoring tool id")
    starter = threading.get_ident()

    def on_start(code, offset):
        tid = threading.get_ident()
        if code.co_name == "_bootstrap_inner" and tid != starter:
            action(tid)

    mon.use_tool_id(tool, "w29-intent")
    mon.register_callback(tool, mon.events.PY_START, on_start)
    mon.set_events(tool, mon.events.PY_START)
    try:
        with contextlib.redirect_stderr(
            io.StringIO()
        ):  # CPython reports the bootstrap's exception
            yield
    finally:
        mon.set_events(tool, 0)
        mon.register_callback(tool, mon.events.PY_START, None)
        mon.free_tool_id(tool)


def _raise(exc):
    def action(tid):
        raise exc

    return action


def _inject(exc_type):
    def action(tid):
        ctypes.pythonapi.PyThreadState_SetAsyncExc(
            ctypes.c_ulong(tid), ctypes.py_object(exc_type)
        )

    return action


# CPython reports a bootstrap's exception as unraisable; pytest turns that into a warning, which is
# the death this test provokes on purpose (the SystemExit case raises none: CPython swallows it).
@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
@pytest.mark.parametrize(
    "action",
    [
        pytest.param(
            _raise(_Stop("raised into the bootstrap")), id="raised-baseexception"
        ),
        pytest.param(_inject(_Stop), id="pending-async-exception"),
        pytest.param(_raise(SystemExit(3)), id="systemexit-swallowed-by-cpython"),
    ],
)
def test_a_bootstrap_that_dies_unsignalled_is_named_never_waited_on(action):
    worker = JoinedWorker(target=lambda: None, daemon=True)
    t0 = time.monotonic()
    with _in_every_new_bootstrap(action), pytest.raises(WorkerLost) as lost:
        worker.start()
    assert time.monotonic() - t0 < 10, (
        "the start must return promptly, not after a long timeout"
    )
    assert lost.value.code == "worker_lost"
    assert worker.name in str(lost.value)
    assert worker not in threading.enumerate(), (
        "a dead thread left in _limbo is listed forever"
    )
    assert not worker.is_alive()


def test_a_healthy_start_is_exactly_thread_start():
    ran = threading.Event()
    worker = JoinedWorker(target=ran.set, daemon=True)
    worker.start()
    worker.join(5)
    assert ran.is_set() and not worker.is_alive()
    assert "wait" not in vars(worker._started), (
        "the start's shadow on _started.wait must be removed"
    )
    assert "_bootstrap" not in vars(worker), (
        "the start's entry on the instance must be removed"
    )
    with pytest.raises(RuntimeError, match="started once"):
        worker.start()


def test_a_start_that_cannot_launch_raises_what_thread_start_raises(monkeypatch):
    def refuse(*args, **kwargs):
        raise RuntimeError("can't start new thread")

    worker = JoinedWorker(target=lambda: None, daemon=True)
    monkeypatch.setattr(threading, "_start_joinable_thread", refuse, raising=False)
    monkeypatch.setattr(threading, "_start_new_thread", refuse, raising=False)
    with pytest.raises(RuntimeError, match="can't start new thread"):
        worker.start()
    assert "wait" not in vars(worker._started)


def test_a_lost_worker_is_the_actions_named_refusal_never_a_traceback(
    tmp_path, monkeypatch, capfd
):
    """The Action reports it as WESKER REFUSED TO REPORT (exit 1), whichever copy of Wesker raised it.

    The refusal is written after the streams are re-entered, like every protocol line of the report, so
    it is read from the descriptor rather than from `sys.stderr`'s capture.
    """
    from Wesker import action, self_profile

    (tmp_path / "m.py").write_text("def f(x):\n    return x\n")
    monkeypatch.chdir(tmp_path)

    def profiler(*args, **kwargs):
        raise WorkerLost(threading.Thread(name="Thread-lost (_target)"))

    monkeypatch.setattr(self_profile, "profiler_for_targets", lambda targets: profiler)
    assert action.main(["--targets", "m.py"]) == 1
    err = capfd.readouterr().err
    assert (
        "WESKER REFUSED TO REPORT: worker_lost: Thread-lost (_target) ended before it signalled"
        in err
    )
    assert "Traceback" not in err
