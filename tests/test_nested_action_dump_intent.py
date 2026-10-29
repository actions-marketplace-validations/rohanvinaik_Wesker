"""A test that calls the Action inside the measuring process never silences the run's stall dump (W#52).

THE DEFECT, measured 2026-10-25. Spec-full run 40237240506 on f99281c dumped every thread's stack at
22:04 (`WESKER_STACK_DUMP_S=900`) and never again. It then went silent for two and a half hours
after `[2/24] action.py` began. Self-measuring `action.py` runs its tests in the measuring process,
and eight test files call `action.main` there. With the job-level variable inherited, each call:
1. armed its own dump, registering faulthandler's SIGURG handler with `chain=False` over the run's
   own handler;
2. on the way out, unregistered it.
Registration is process-global, so the run's clock kept signalling a process with no handler, and
SIGURG is ignored by default. A Linux reproduction on the same tree, with a 60 s clock, dumped once
in twelve minutes.

THE RULING, pinned through the real code in a SUBPROCESS, as `test_stack_dump_clock_intent.py`
pins the clock:
- an armed owner sets `WESKER_STACK_DUMP_OWNER` to its pid (`stack_dump_owner`). A nested Action in
  the same process neither arms nor cancels, and the owner's dump still fires after the nested call
  returns.
- the owner re-asserts its registration every `_REASSERT_S`, so a mutant of this code that
  unregisters it does not silence the rest of the run.
- the release removes the marker.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from Wesker.action import stack_dump_owner

REPO = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    not hasattr(__import__("signal"), "SIGURG"),
    reason="the dump clock needs POSIX signals",
)


@pytest.mark.parametrize(
    ("marker", "pid", "owner"),
    [("", 41, "owner"), ("41", 41, "nested"), ("7", 41, "owner"), ("041", 41, "owner")],
)
def test_only_this_processs_own_marker_makes_an_action_nested(marker, pid, owner):
    assert stack_dump_owner(marker, pid) == owner


def _run(script: str, tmp_path: Path) -> tuple[int, str, str]:
    err = tmp_path / "err.txt"
    env = dict(
        os.environ,
        PYTHONPATH=os.pathsep.join([str(REPO), os.environ.get("PYTHONPATH", "")]),
        WESKER_STACK_DUMP_S="3600",  # a clock that never ticks inside the test: only our own signals dump
    )
    env.pop("WESKER_STACK_DUMP_OWNER", None)
    with open(err, "w") as fh:
        proc = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(script)],
            env=env,
            stderr=fh,
            stdout=subprocess.PIPE,
            text=True,
            timeout=60,
            check=False,
        )
    return proc.returncode, proc.stdout, err.read_text()


_NESTED = """
    import os, signal, sys, time
    from Wesker import action

    release = action._stack_dump_from_env()
    print("owner", os.environ.get("WESKER_STACK_DUMP_OWNER") == str(os.getpid()))
    nested = action._stack_dump_from_env()  # what a test calling `main` in this process does
    nested()
    print("still owned", os.environ.get("WESKER_STACK_DUMP_OWNER") == str(os.getpid()))
    os.kill(os.getpid(), signal.SIGURG)
    time.sleep(0.3)
    release()
    print("released", "WESKER_STACK_DUMP_OWNER" not in os.environ)
"""


def test_a_nested_action_leaves_the_owners_dump_armed(tmp_path):
    code, out, err = _run(_NESTED, tmp_path)
    assert code == 0, out + err
    assert out.split("\n")[:3] == ["owner True", "still owned True", "released True"], (
        out
    )
    assert "Current thread" in err or "Thread 0x" in err, (
        "the nested call silenced the owner's dump"
    )


_REASSERTED = """
    import faulthandler, os, signal, sys, time
    from Wesker import action

    action._REASSERT_S = 0.1
    release = action._stack_dump_from_env()
    faulthandler.unregister(signal.SIGURG)  # what a mutant of the arming code can do
    time.sleep(0.5)
    os.kill(os.getpid(), signal.SIGURG)
    time.sleep(0.3)
    release()
    print("done")
"""


def test_the_owner_restores_a_handler_something_else_removed(tmp_path):
    code, out, err = _run(_REASSERTED, tmp_path)
    assert code == 0 and out.strip() == "done", out + err
    assert "Current thread" in err or "Thread 0x" in err, (
        "the removed handler stayed removed"
    )
