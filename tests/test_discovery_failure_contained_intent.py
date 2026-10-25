"""A failure inside PY_START discovery is the observer's, never the observed code's (W#29).

THE DEFECT (measured 2026-10-25). With the deadlock fixed, Wesker's local whole-codebase
self-measurement ran on and died 27 minutes in:

    File ".../Wesker/engine.py", in _patch_mutant_into_test
    File ".../inspect.py", line 903, in getmodule
    File ".../Wesker/monitoring.py", in _dispatch_py_start
    File ".../Wesker/monitoring.py", in _discovery_pending
    File ".../Wesker/monitoring.py", line 242, in _matches_selectors
        real, dev_ino = _file_info(filename)
    ValueError: too many values to unpack (expected 2)

Discovery runs in a PY_START callback on EVERY thread while a selector subscription is live, so an
exception it lets escape is raised into whatever function just started. Here that function was the
measuring engine's own, and the run ended. In a test, it would have read as a crash kill. The module
already holds the rule for observers (`_notify`, `_dispatch_instruction`): an observer failure is
never the observed code's failure. Discovery was the path that did not apply it. What made
`_file_info` return a non-pair is not established here; this pins that, whatever the cause, it cannot
escape.

PINNED with the failure played by a replaced `_file_info` that returns what the measured one did (a
string), and an `Abandoned` played the same way, through the real dispatcher:
- the observed call returns normally;
- every live selector subscription is marked `discovery_failed:ValueError`, and the owning boundary
  refuses its evidence by that name;
- an `Abandoned` raised inside discovery still unwinds the caller, because abandonment must reach
  the thread.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from Wesker import monitoring
from Wesker.interrupt import Abandoned
from Wesker.monitoring import (
    MonitoringObservationFailed,
    release_monitoring_tool,
    subscribe,
    tool_id,
)


@pytest.fixture(autouse=True)
def _cleanup_monitoring():
    yield
    sys.monitoring.set_events(tool_id(), 0)
    release_monitoring_tool()


def _function_in(directory: Path, name: str):
    filename = str(directory / f"{name}.py")
    ns: dict = {}
    source = f"def {name}(x):\n    return x + 1\n"
    # S102: the test needs code objects whose co_filename lies under a selector's directory
    exec(compile(source, filename, "exec"), ns)  # noqa: S102
    return ns[name]


def test_a_failing_discovery_never_raises_into_the_observed_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fn = _function_in(tmp_path, "observed")
    handle = subscribe(
        [], sys.monitoring.events.LINE, lambda *a, **k: None, selectors=[str(tmp_path)]
    )
    monkeypatch.setattr(monitoring, "_file_info", lambda filename: filename)
    monkeypatch.setattr(monitoring, "_selector_match_cache", {})
    try:
        assert fn(1) == 2, "the observed code runs as if nothing were watching it"
        assert handle.sub.observation.failure == "discovery_failed:ValueError"
    finally:
        monkeypatch.undo()
        handle.close()
    with pytest.raises(MonitoringObservationFailed) as refused:
        handle.check()
    assert refused.value.code == "discovery_failed"


def test_an_abandonment_inside_discovery_still_unwinds_the_caller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fn = _function_in(tmp_path, "abandoned")
    handle = subscribe(
        [], sys.monitoring.events.LINE, lambda *a, **k: None, selectors=[str(tmp_path)]
    )

    # Only for the observed function: PY_START is global while a selector subscription is live, so
    # an unconditional fake would fire at the start of `pytest.raises` itself.
    def _abandoned(code, thread_id):
        if code is fn.__code__:
            raise Abandoned
        return []

    monkeypatch.setattr(monitoring, "_discovery_pending", _abandoned)
    try:
        with pytest.raises(Abandoned):
            fn(1)
        assert handle.sub.observation.failure == "", (
            "an abandonment is not an observer failure"
        )
    finally:
        monkeypatch.undo()
        handle.close()
