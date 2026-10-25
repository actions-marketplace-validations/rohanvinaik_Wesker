"""Intent: a stalled badge run leaves evidence of WHERE it stalled (W#29 follow-up, 2026-10-25).

Every push of 2026-10-24 ran the whole-codebase Specification measurement for six hours with no
output after "Whole codebase — 22 file(s)." and was cancelled by GitHub's job limit. A cancel
leaves no stack, so the stall could not be located. ``WESKER_STACK_DUMP_S`` arms a periodic
all-thread dump on a PRIVATE copy of stderr, because the live session captures (and hostile
mutants of the capture machinery can close) fd 2 for long stretches of the run.

The descriptor behaviour is process-global, so the wiring cases run in a subprocess. A dump is
counted by its thread header, "(most recent call first)": these scripts run one Python thread,
so one header is one dump. The first version counted faulthandler's "Timeout (" banner, which
only its own timer prints; that timer is gone (pytest cancels it on every failing test, W#29),
and the clock that replaced it signals a registered handler, which prints no banner.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

from Wesker.action import stack_dump_setting


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", ("off", 0)),
        ("   ", ("off", 0)),
        ("900", ("armed", 900)),
        (" 07 ", ("armed", 7)),
        ("1", ("armed", 1)),
        ("0", ("invalid", 0)),
        ("-5", ("invalid", 0)),
        ("+5", ("invalid", 0)),
        ("1.5", ("invalid", 0)),
        ("abc", ("invalid", 0)),
        ("²", ("invalid", 0)),
    ],
)
def test_the_setting_names_off_armed_and_invalid_apart(raw, expected):
    assert stack_dump_setting(raw) == expected


def _run(script: str, env_value: str | None, tmp_path) -> subprocess.CompletedProcess:
    import os

    env = {k: v for k, v in os.environ.items() if k != "WESKER_STACK_DUMP_S"}
    if env_value is not None:
        env["WESKER_STACK_DUMP_S"] = env_value
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        cwd=tmp_path,
        env=env,
    )


_ARM_THEN_LOSE_FD2 = """
    import os, time
    from Wesker.action import _arm_stack_dump

    cancel = _arm_stack_dump(1)
    # What the live session's descriptor capture does for the length of a test.
    os.dup2(os.open(os.devnull, os.O_WRONLY), 2)
    time.sleep(1.6)
    cancel()
    time.sleep(1.5)
    print("finished")
"""


def test_the_dump_reaches_the_real_stderr_after_fd2_is_captured(tmp_path):
    proc = _run(_ARM_THEN_LOSE_FD2, None, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "finished" in proc.stdout
    # One dump fired before the cancel, on the private descriptor, and none after it.
    assert proc.stderr.count("most recent call first") == 1, proc.stderr


_MAIN_WITH_A_SLOW_PROFILE = """
    import time
    import Wesker.self_profile as self_profile
    from Wesker import action

    def profiler(*args, **kwargs):
        time.sleep(1.6)
        return None  # the legacy-runner refusal: main reports it and returns 1

    self_profile.profiler_for_targets = lambda targets: profiler
    raise SystemExit(action.main(["--targets", "m.py"]))
"""


def test_main_arms_the_dump_around_profiling_when_asked(tmp_path):
    proc = _run(_MAIN_WITH_A_SLOW_PROFILE, "1", tmp_path)
    assert proc.returncode == 1, proc.stderr
    assert proc.stderr.count("most recent call first") == 1, proc.stderr
    assert "WESKER REFUSED TO REPORT" in proc.stderr


def test_main_arms_nothing_by_default(tmp_path):
    proc = _run(_MAIN_WITH_A_SLOW_PROFILE, None, tmp_path)
    assert proc.returncode == 1, proc.stderr
    assert "most recent call first" not in proc.stderr
    assert "WESKER_STACK_DUMP_S" not in proc.stderr


def test_a_malformed_setting_is_named_and_arms_nothing(tmp_path):
    proc = _run(_MAIN_WITH_A_SLOW_PROFILE, "fifteen minutes", tmp_path)
    assert proc.returncode == 1, proc.stderr
    assert "most recent call first" not in proc.stderr
    assert (
        "WESKER_STACK_DUMP_S must be a positive whole number of seconds" in proc.stderr
    )
