"""Stopping a timed-out test's thread, instead of abandoning it.

WHY THIS EXISTS: `_run_test_with_timeout` bounded the WAIT, not the WORK — on timeout it returned
"timeout" and left the daemon thread running ("cleaned up on process exit", i.e. never, within a
run). Every timeout leaked a live thread burning a core, so later mutants timed out BECAUSE
earlier ones were still running: the failure compounded across a session. The abandoned thread's
writes also escaped to the real stdout once the redirect around start+join exited, corrupting the
engine's own report minutes later.

`_abandon` injects `_Abandoned` via CPython's async-exception API, unwinding the thread at its
next BYTECODE boundary — in-process and stdlib-only, so Wesker keeps both its architecture and its
zero-dependency promise. What it cannot reach is pinned here too: a thread blocked OUTSIDE the
interpreter executes no bytecode, so it survives, and `_abandon` says so rather than pretending.
"""

import subprocess
import threading
import time

from Wesker.interrupt import Abandoned as _Abandoned
from Wesker.interrupt import abandon as _abandon
from Wesker.interrupt import injection_landed as _unwind_dead_end


def _runaway(flag: dict) -> None:
    try:
        for i in range(10**9):
            flag["n"] = i
    except BaseException:  # noqa: BLE001 — the injection unwinds through here
        flag["unwound"] = True


def _spawn(target, *args) -> threading.Thread:
    t = threading.Thread(target=target, args=args, daemon=True)
    t.start()
    time.sleep(0.05)  # let it actually enter the loop before injecting
    return t


def test_abandon_stops_a_pure_python_runaway():
    """The leak this exists to remove: without the injection this thread runs until the process
    exits, competing with every mutant that follows it."""
    flag: dict = {}
    t = _spawn(_runaway, flag)
    assert _abandon(t) is True
    assert t.is_alive() is False


def test_abandon_outranks_the_test_s_own_broad_except():
    """`_Abandoned` is a BaseException ON PURPOSE — a test that swallows `Exception` (a real and
    ordinary thing for a test to do) would otherwise eat the injection and keep running, leaving
    the leak in place precisely where the code looks most innocent."""
    assert issubclass(_Abandoned, BaseException)
    assert not issubclass(_Abandoned, Exception)

    def _swallower() -> None:
        try:
            try:
                for _ in range(10**9):
                    pass
            except Exception:  # noqa: BLE001 — the point of the test: this must NOT stop it
                pass
        except BaseException:  # noqa: BLE001 — mirrors _target's own outer catch
            pass

    t = _spawn(_swallower)
    assert _abandon(t) is True
    assert t.is_alive() is False


def test_abandon_reports_false_for_a_thread_blocked_outside_the_interpreter():
    """THE HONEST BOUNDARY. A thread inside `subprocess.run` runs no bytecode, so the injection
    cannot land until that call returns on its own. `_abandon` returns False rather than claiming
    a stop it did not make — bounding this needs process isolation, a different engine."""

    def _blocked() -> None:
        try:
            subprocess.run(["sleep", "3"], check=False)
        except BaseException:  # noqa: BLE001
            pass

    t = _spawn(_blocked)
    assert _abandon(t) is False
    assert t.is_alive() is True


def test_abandon_is_false_for_a_thread_that_never_started():
    """No ident = nothing to inject into. Degrades to "not stopped", never an error."""
    assert _abandon(threading.Thread(target=lambda: None)) is False


def test_unwind_dead_end_only_accepts_exactly_one_marked_thread():
    """0 = a benign race (the thread finished between is_alive and the injection). >1 is CPython's
    documented "you're in trouble" case, and the caller must undo it — we cannot know which other
    threads were poisoned, so it can never count as success."""
    assert _unwind_dead_end(1) is True
    assert _unwind_dead_end(0) is False
    assert _unwind_dead_end(2) is False
