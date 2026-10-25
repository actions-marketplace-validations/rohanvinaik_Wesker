"""The engine's execution and measurement-registry locks cannot be stranded by an abandoned worker (W#29).

THE DEFECT, the same as the monitoring broker's (test_unstranded_lock_intent). A worker parked in
a CONTENDED acquire is abandoned while it waits. The lock is then handed to it, the acquire
returns, and the injection lands at the check after that call, with the lock held. It landed:
- in `_acquire_execution_lock`'s bare `acquire()`, before `_note_lock_entry`, on every version.
  That was the window its docstring called unclosable from Python;
- in `_execution_guard`'s unbounded `with _EXECUTION_LOCK:` on 3.14, whose `with` begins its
  protected range only after `__enter__`'s own check;
- in `_measurement_boundary`'s `with _MEASUREMENT_REGISTRY_LOCK:` on 3.14.
The execution lock's orphan channels would later REFUSE every measurement by name ("orphaned").
The registry lock had no such channel, so every later `run_function_profiling` waited forever.
This is the dogfood path: the engine running inside a test that a traced baseline abandons.

MEASURED (standalone, the same harness): before this fix `_serialized` strands on 3.12, 3.13 and
3.14; the guard and the boundary strand on 3.14 only. After it, all three are free on all three.
So on 3.12 and 3.13 the two `with` cases pass with and without the fix: that is the interpreter.

PINNED through the real entry points, each against fresh lock objects swapped in for the test,
so a regression strands only the test's own lock, never the suite's: a worker parks in the
entry's acquire while this thread holds the lock, is abandoned, and the lock is then released.
Afterwards the lock is free, and the execution lock's owner record is clear.
"""

from __future__ import annotations

import contextlib
import sys
import threading
import time
from collections.abc import Callable

import pytest

from Wesker import engine, interrupt
from Wesker.interrupt import Abandoned


def _serialized_entry() -> None:
    engine._serialized(lambda: None)()


def _guard_entry() -> None:
    with engine._execution_guard():
        pass


def _boundary_entry() -> None:
    engine._measurement_boundary(lambda: None)()


# Where a worker blocks in the C-level acquire, by entry point: `acquire_unstranded` now; before
# W#29, `_acquire_execution_lock`'s bare acquire, the guard's `with`, and the boundary's `with`.
_ACQUIRING = {
    "acquire_unstranded",
    "_acquire_execution_lock",
    "_execution_guard",
    "_wrapped",
}


def _parked_in_acquire(t: threading.Thread) -> bool:
    f = sys._current_frames().get(t.ident or -1)
    return f is not None and f.f_code.co_name in _ACQUIRING


@pytest.mark.parametrize(
    ("entry", "lock_name"),
    [
        (_serialized_entry, "_EXECUTION_LOCK"),
        (_guard_entry, "_EXECUTION_LOCK"),
        (_boundary_entry, "_MEASUREMENT_REGISTRY_LOCK"),
    ],
    ids=["serialized", "execution_guard", "measurement_boundary"],
)
def test_an_abandoned_worker_parked_in_the_acquire_leaves_the_lock_free(
    monkeypatch: pytest.MonkeyPatch, entry: Callable[[], None], lock_name: str
) -> None:
    monkeypatch.setattr(engine, "_EXECUTION_LOCK", threading.RLock())
    monkeypatch.setattr(engine, "_MEASUREMENT_REGISTRY_LOCK", threading.RLock())
    monkeypatch.setattr(engine, "_LOCK_OWNER_TID", 0)
    monkeypatch.setattr(engine, "_LOCK_DEPTH", 0)
    lock = getattr(engine, lock_name)
    caught = threading.Event()

    def worker() -> None:
        with contextlib.suppress(Abandoned):
            entry()
            return
        caught.set()

    lock.acquire()
    held = True
    try:
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        deadline = time.monotonic() + 5
        while not _parked_in_acquire(t) and time.monotonic() < deadline:
            time.sleep(0.001)
        assert _parked_in_acquire(t), "the worker never reached the contended acquire"
        time.sleep(0.02)
        assert interrupt.abandon(t) is False, (
            "parked in a C-level acquire, the worker cannot unwind before the lock is released"
        )
        lock.release()
        held = False
        t.join(5)
    finally:
        if held:
            lock.release()

    assert not t.is_alive()
    assert caught.is_set(), (
        "the injection lands as the acquire returns and unwinds the worker"
    )
    # Probe without trusting thread identity. A NEW probe thread can be handed the dead owner's
    # ident (macOS reuses pthread addresses), and an RLock lets its "owner" straight back in,
    # which made an earlier version of this test pass on the stranded code. The repr reports
    # locked/unlocked whoever asks; the acquire comes from this thread, which never owned it.
    assert repr(lock).startswith("<unlocked"), (
        f"{lock_name} is owned by a thread that no longer exists: {lock!r}"
    )
    assert lock.acquire(timeout=1)
    lock.release()
    assert engine._LOCK_OWNER_TID == 0
    assert engine._LOCK_DEPTH == 0
