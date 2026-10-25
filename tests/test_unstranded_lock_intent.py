"""`interrupt.acquire_unstranded`: an abandoned worker can no longer strand the broker's lock (W#29).

THE DEFECT (measured 2026-10-25). Wesker's whole-codebase CI run printed `[1/22]
_isolated_worker.py` and then nothing for six hours, on 10 pushes of 10. Reproduced locally, the
faulthandler dump showed exactly two threads, both parked acquiring `monitoring._subscriptions_lock`
from `_dispatch_py_start`. An RLock never blocks its own owner, so neither held it: its owner was a
test's runaway that `bounded_join` had just abandoned, and that thread was dead. The runaway had
been parked in that same CONTENDED acquire when the injection was made. It got the lock, the acquire
returned, and the exception was raised at the check after that call. On 3.14 that check is outside
`with`'s protection (`LOAD_SPECIAL __enter__; CALL 0`, then the protected range), so it exited owning
the lock and every later PY_START in every thread waited for it forever. 3.11–3.13 compiled `with` to
one `BEFORE_WITH` opcode with no check in that spot, which is why the same code never hung there.

WHAT IS PINNED, AND HOW.
- The undo decision is control flow: it takes back exactly the acquire that the raise interrupted.
  It is pinned with FAKE locks whose `acquire` raises after taking the real RLock (where an
  injection lands) or before taking it (a signal during the wait). Each fake asserts the real depth
  afterwards, so no interpreter timing enters the claim. That includes the re-entrant case, where
  the thread already held the lock and only the depth can tell this acquire from the outer one.
- The defect itself runs through the REAL broker, in a SUBPROCESS: a live selector subscription, a
  worker parked in `_dispatch_py_start`'s contended acquire, a real `abandon`, then the release.
  The subprocess is the point. A stranded broker lock blocks the next PY_START of EVERY thread,
  this test's own included, so in-process the old code would wedge the suite rather than fail it.
  On 3.14 the old code hangs the subprocess, and its dump names the dead owner's waiters. On 3.12
  and 3.13 it passes with and without the fix, because their `with` never had the window. That pass
  is the interpreter, not a vacuous test.
- `_recursion_count` is a private C-RLock method; the canary fails loudly if CPython drops it.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest

from Wesker.interrupt import Abandoned, acquire_unstranded

REPO = Path(__file__).resolve().parents[1]


class _RaisesAfterTaking:
    """A lock whose `acquire` takes the real RLock and THEN raises: exactly where an injection lands
    when a contended acquire returns, at the check after the call."""

    def __init__(self, real: threading.RLock, exc: BaseException) -> None:
        self.real = real
        self.exc = exc

    def _recursion_count(self) -> int:
        return self.real._recursion_count()  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]

    def acquire(self, timeout: float = -1) -> bool:
        self.real.acquire()
        raise self.exc

    def release(self) -> None:
        self.real.release()


class _RaisesBeforeTaking(_RaisesAfterTaking):
    """A lock whose `acquire` raises WITHOUT taking it: a signal's KeyboardInterrupt delivered to a
    main thread parked in a blocking acquire."""

    def acquire(self, timeout: float = -1) -> bool:
        raise self.exc


def _depth(lock: threading.RLock) -> int:
    return lock._recursion_count()  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]


def test_rlock_recursion_count_still_reports_depth() -> None:
    """The undo reads the C RLock's private depth. If CPython drops or changes it, this fails here,
    loudly, instead of the undo silently mis-deciding."""
    lock = threading.RLock()
    assert _depth(lock) == 0
    lock.acquire()
    lock.acquire()
    assert _depth(lock) == 2
    seen_elsewhere: list[int] = []
    t = threading.Thread(target=lambda: seen_elsewhere.append(_depth(lock)))
    t.start()
    t.join()
    assert seen_elsewhere == [0], "depth is per owner: another thread must read 0"
    lock.release()
    lock.release()
    assert _depth(lock) == 0


def test_a_raise_after_taking_gives_the_lock_back() -> None:
    real = threading.RLock()
    with pytest.raises(Abandoned):
        acquire_unstranded(_RaisesAfterTaking(real, Abandoned()))
    assert _depth(real) == 0
    got: list[bool] = []
    t = threading.Thread(target=lambda: got.append(real.acquire(timeout=1)))
    t.start()
    t.join()
    assert got == [True], (
        "another thread must be able to take the lock: nothing was stranded"
    )


def test_a_reentrant_raise_after_taking_undoes_only_its_own_acquire() -> None:
    """The thread already holds the lock once. The interrupted re-entrant acquire is undone, and the
    outer hold survives intact. An `_is_owned()` test would read True either way and could not tell."""
    real = threading.RLock()
    real.acquire()
    try:
        with pytest.raises(Abandoned):
            acquire_unstranded(_RaisesAfterTaking(real, Abandoned()))
        assert _depth(real) == 1
    finally:
        real.release()
    assert _depth(real) == 0


def test_a_raise_before_taking_releases_nothing() -> None:
    """Nothing was taken, so nothing is given back: no RuntimeError from releasing an unowned lock,
    and a re-entrant caller's outer hold is not spent on an acquire that never happened."""
    real = threading.RLock()
    with pytest.raises(KeyboardInterrupt):
        acquire_unstranded(_RaisesBeforeTaking(real, KeyboardInterrupt()))
    assert _depth(real) == 0
    real.acquire()
    try:
        with pytest.raises(KeyboardInterrupt):
            acquire_unstranded(_RaisesBeforeTaking(real, KeyboardInterrupt()))
        assert _depth(real) == 1
    finally:
        real.release()


def test_the_ordinary_paths_keep_their_meaning() -> None:
    real = threading.RLock()
    assert acquire_unstranded(real) is True
    assert _depth(real) == 1
    assert acquire_unstranded(real) is True, "re-entrant, like the RLock it wraps"
    assert _depth(real) == 2
    real.release()
    real.release()

    holder_has_it = threading.Event()
    done = threading.Event()

    def hold() -> None:
        real.acquire()
        holder_has_it.set()
        done.wait()
        real.release()

    t = threading.Thread(target=hold)
    t.start()
    holder_has_it.wait()
    try:
        assert acquire_unstranded(real, timeout=0.05) is False
        assert _depth(real) == 0
    finally:
        done.set()
        t.join()


def test_the_old_shape_strands_where_this_does_not() -> None:
    """The control, with no interpreter in it: when `__enter__` raises after taking the lock,
    `__exit__` never runs. On 3.14 that happens to every `with lock:` whose acquire waited. This
    function's handler is what the `with` form does not have."""

    class _EnterTakesThenRaises:
        def __init__(self, real: threading.RLock) -> None:
            self.real = real

        def __enter__(self) -> None:
            self.real.acquire()
            raise Abandoned

        def __exit__(self, *exc: object) -> None:
            self.real.release()

    real = threading.RLock()
    with pytest.raises(Abandoned), _EnterTakesThenRaises(real):
        pass
    assert _depth(real) == 1, (
        "the old shape leaves the lock held by the unwinding thread"
    )
    real.release()


_BROKER_SCENARIO = textwrap.dedent(
    """
    import faulthandler, sys, threading, time
    faulthandler.dump_traceback_later(15, exit=True)
    from Wesker import interrupt, monitoring

    selected = sys.argv[1]
    ns = {}
    exec(compile("def selected():\\n    return 1\\n", selected + "/selected.py", "exec"), ns)
    fn = ns["selected"]
    handle = monitoring.subscribe(
        [], sys.monitoring.events.LINE, lambda *a, **k: None, selectors=[selected]
    )
    ready, caught = threading.Event(), threading.Event()
    go = [False]

    def worker():
        try:
            ready.set()
            # Spin on a plain flag, not an Event: a loop that calls nothing starts no function, so
            # the first PY_START after the lock is taken is `selected`'s, inside this `try`.
            while not go[0]:
                pass
            while True:
                fn()
        except interrupt.Abandoned:
            caught.set()

    def parked(t):
        codes = set()
        f = sys._current_frames().get(t.ident)
        while f is not None:
            codes.add(f.f_code)
            f = f.f_back
        return monitoring._dispatch_py_start.__code__ in codes and fn.__code__ in codes

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    ready.wait()
    lock = monitoring._subscriptions_lock
    lock.acquire()
    go[0] = True
    deadline = time.monotonic() + 5
    while not parked(t) and time.monotonic() < deadline:
        time.sleep(0.001)
    if not parked(t):
        print("NEVER_PARKED", flush=True)
        sys.exit(3)
    time.sleep(0.02)
    print("PARKED", flush=True)
    contained = interrupt.abandon(t)
    print(f"ABANDON_RETURNED {contained}", flush=True)
    lock.release()
    t.join(5)
    print(f"WORKER_ALIVE {t.is_alive()} CAUGHT {caught.is_set()}", flush=True)
    got = lock.acquire(timeout=1)
    print("UNSTRANDED" if got else "STRANDED", flush=True)
    if got:
        lock.release()
    handle.close()
    print("CLOSED", flush=True)
    """
)


def test_an_abandoned_worker_parked_in_discovery_leaves_the_broker_lock_free(
    tmp_path: Path,
) -> None:
    env = dict(
        os.environ,
        PYTHONPATH=os.pathsep.join([str(REPO), os.environ.get("PYTHONPATH", "")]),
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _BROKER_SCENARIO, str(tmp_path)],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
            check=False,
        )
    except (
        subprocess.TimeoutExpired
    ) as exc:  # pragma: no cover - the defect's own symptom
        pytest.fail(
            f"the scenario hung (stranded broker lock, W#29): {exc.stdout!r} {exc.stderr!r}"
        )
    transcript = proc.stdout + proc.stderr
    assert "PARKED" in proc.stdout, transcript
    assert "ABANDON_RETURNED False" in proc.stdout, (
        "a worker parked in a C-level acquire cannot unwind until the lock is released: "
        "abandon must report it not yet contained\n" + transcript
    )
    assert "WORKER_ALIVE False CAUGHT True" in proc.stdout, transcript
    assert "UNSTRANDED" in proc.stdout, transcript
    assert "CLOSED" in proc.stdout, transcript
    assert proc.returncode == 0, transcript
