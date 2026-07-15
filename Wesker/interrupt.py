"""Stopping a runaway test thread — the one primitive both timed paths need.

Wesker bounds two things by wall-clock: a MUTANT's test run (`engine._run_test_with_timeout`) and
a test's TRACED baseline pass (`line_coverage._trace_one`). Both face the same problem, and it has
exactly one honest in-process answer, so it lives here once rather than being re-derived on each
side (`engine` imports `line_coverage`, so a shared home is also the only way both can use it).

THE PROBLEM: `thread.join(timeout)` bounds the WAIT, not the WORK. A daemon thread left running is
reclaimed at PROCESS exit — i.e. never, within a run — so each timeout leaks a live thread that
burns a core, and later timeouts are then CAUSED by earlier ones still running. The failure
compounds, and its writes can surface on stdout long after the caller moved on.

THE ANSWER: CPython's async-exception injection — the thread raises at its next BYTECODE boundary.
In-process and stdlib-only, so it costs Wesker neither its architecture nor its zero-dependency
promise. It is also the only mechanism that bounds work wherever it happens: a budget that rides a
trace callback can only fire while the traced code is executing, which in a real suite is a small
minority of the time (most tests never touch the one file under analysis, so they are not traced
at all — and therefore not bounded at all).

THE BOUNDARY, stated honestly and NOT fixable in-process: a thread blocked OUTSIDE the interpreter
— `subprocess.run`, a C extension, a socket — executes no bytecode, so the injection cannot land
until that call returns on its own. `abandon` returns False there rather than claiming a stop it
did not make. Bounding that for real needs process isolation, which is a different engine than an
in-process one.
"""

from __future__ import annotations

import ctypes
from typing import Any


class Abandoned(BaseException):
    """Injected into a timed-out thread to unwind it.

    A ``BaseException``, not an ``Exception``, deliberately: a test that wraps its body in a broad
    ``except Exception`` — an ordinary, innocent-looking thing for a test to do — would otherwise
    SWALLOW the injection and keep running, leaving the leak in place exactly where the code looks
    safest. The interrupt has to outrank the interrupted code's own error handling to be one.
    """


# How long to let an injected thread unwind before conceding it is blocked outside the interpreter.
# Only ever paid on a timeout (already the slow path), and only to keep the concession honest.
UNWIND_S = 0.1


def injection_landed(marked: int) -> bool:
    """Whether an async-exception injection took, given how many threads CPython says it marked.

    Exactly 1 is the good case. 0 means the thread already finished (a benign race against
    ``is_alive``). >1 must never happen — CPython documents it as "you're in trouble" — and the
    caller must UNDO it: we cannot know which other threads were poisoned, so it can never count
    as success.
    """
    return marked == 1


def abandon(thread: Any) -> bool:
    """Best-effort stop of a runaway thread. True when the thread is confirmed gone.

    Verified against all three cases that matter: it unwinds a pure-Python runaway, it survives a
    test's broad ``except Exception``, and it honestly reports False for a thread blocked outside
    the interpreter (see the module docstring's BOUNDARY).
    """
    tid = getattr(thread, "ident", None)
    if tid is None:
        return False
    marked = ctypes.pythonapi.PyThreadState_SetAsyncExc(
        ctypes.c_ulong(tid), ctypes.py_object(Abandoned)
    )
    if not injection_landed(marked):
        if (
            marked > 1
        ):  # pragma: no cover — CPython: "you're in trouble"; undo the over-broad set
            ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(tid), None)
        return False
    thread.join(timeout=UNWIND_S)
    return not thread.is_alive()
