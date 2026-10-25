"""`WESKER_STACK_DUMP_S` dumps on a clock pytest cannot cancel (W#29).

THE DEFECT. The periodic dump armed `faulthandler.dump_traceback_later`, which is one
process-wide timer. pytest's own faulthandler plugin cancels that timer in
`pytest_exception_interact`, unconditionally, on every failing test. A self-measurement fails tests
within seconds, so the dump armed before profiling was gone long before the stall. The 636 s local
reproduction of the six-hour CI hang printed nothing, and sampling the process showed no watchdog
thread. Measured directly: a 1 s timer stops the moment pytest.main runs one failing test, and keeps
going across a passing one.

THE FIX, pinned here through the real `_arm_stack_dump` in a SUBPROCESS: faulthandler dumps from
a SIGURG handler, and a separate child process sends the signal.
- dumps keep coming after a failing test has run under pytest.main in the same process;
- `cancel` stops them;
- the clock dies with its parent when the run ends without cancelling;
- a platform without the signal is told so and gets a cancel that does nothing.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from Wesker import action

REPO = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    not hasattr(__import__("signal"), "SIGURG"),
    reason="the dump clock needs POSIX signals",
)


def _env() -> dict[str, str]:
    return dict(
        os.environ,
        PYTHONPATH=os.pathsep.join([str(REPO), os.environ.get("PYTHONPATH", "")]),
        WESKER_STACK_DUMP_S="",
    )


_SURVIVES_A_FAILING_TEST = textwrap.dedent(
    """
    import sys, time
    import pytest
    from Wesker.action import _arm_stack_dump

    err_path, failing = sys.argv[1], sys.argv[2]

    def count(marker):
        sys.stderr.flush()
        with open(err_path) as f:
            return f.read().count(marker)

    cancel = _arm_stack_dump(1)

    def _before_pytest():
        time.sleep(1.6)

    def _after_failing_test():
        time.sleep(2.6)

    def _after_cancel():
        time.sleep(2.6)

    _before_pytest()
    pytest.main(["-q", "-p", "no:cacheprovider", failing])
    _after_failing_test()
    cancel()
    _after_cancel()
    print("BEFORE", count("in _before_pytest"))
    print("AFTER_FAILING", count("in _after_failing_test"))
    print("AFTER_CANCEL", count("in _after_cancel"))
    """
)


def test_dumps_survive_a_failing_test_and_stop_when_cancelled(tmp_path: Path) -> None:
    failing = tmp_path / "suite" / "test_fails.py"
    failing.parent.mkdir()
    failing.write_text("def test_fails():\n    assert 1 == 2\n")
    err = tmp_path / "stderr.txt"
    with err.open("w") as err_file:
        proc = subprocess.run(
            [sys.executable, "-c", _SURVIVES_A_FAILING_TEST, str(err), str(failing)],
            stdout=subprocess.PIPE,
            stderr=err_file,
            text=True,
            timeout=60,
            env=_env(),
            cwd=tmp_path,
            check=False,
        )
    counts = dict(
        line.split()
        for line in proc.stdout.splitlines()
        if line.startswith(("BEFORE", "AFTER"))
    )
    transcript = proc.stdout + err.read_text()
    assert int(counts.get("BEFORE", 0)) >= 1, transcript
    assert int(counts.get("AFTER_FAILING", 0)) >= 1, (
        "a failing test under pytest.main must not cancel the dump clock\n" + transcript
    )
    assert int(counts.get("AFTER_CANCEL", -1)) == 0, transcript
    assert proc.returncode == 0, transcript


_EXITS_WITHOUT_CANCEL = textwrap.dedent(
    """
    import os, subprocess
    from Wesker.action import _arm_stack_dump

    _arm_stack_dump(1)
    children = subprocess.run(
        ["pgrep", "-P", str(os.getpid())], capture_output=True, text=True, check=False
    ).stdout.split()
    print("CLOCK", " ".join(children), flush=True)
    os._exit(0)
    """
)


def test_the_clock_dies_with_its_parent(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-c", _EXITS_WITHOUT_CANCEL],
        capture_output=True,
        text=True,
        timeout=30,
        env=_env(),
        cwd=tmp_path,
        check=False,
    )
    clocks = [
        int(pid)
        for line in proc.stdout.splitlines()
        if line.startswith("CLOCK")
        for pid in line.split()[1:]
    ]
    assert clocks, proc.stdout + proc.stderr
    deadline = time.monotonic() + 6
    alive = list(clocks)
    while alive and time.monotonic() < deadline:
        time.sleep(0.2)
        still = []
        for pid in alive:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                continue
            still.append(pid)
        alive = still
    assert not alive, f"the dump clock outlived its parent: {alive}"


def test_a_platform_without_the_signal_is_told_and_gets_a_no_op(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(action, "_DUMP_SIGNAL", "SIGNOTONTHISPLATFORM")
    cancel = action._arm_stack_dump(5)
    assert "needs POSIX signals" in capsys.readouterr().err
    cancel()
