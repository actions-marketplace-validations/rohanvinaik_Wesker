"""Discovery decides without the broker lock, and remembers a file no selector names (W#29).

THE DEFECT. Before this, `_dispatch_py_start` took the broker lock for every code no selector
subscription had attached. A code whose file no selector names is never attached, so while a
baseline trace was live, every PY_START of every unselected function in the process took the lock
and re-ran the selector checks. Measured with line_coverage's three subscriptions, that cost about
2.4 us per function call, against about 60 ns bare. It was also the contention that parked an
abandoned runaway in the lock's wait, where 3.14 stranded it (test_unstranded_lock_intent). Now
the decision reads the registry without the lock, a file no live selector names is recorded once
per selector generation, and only an actual attachment takes the lock. The overhead is about
94 ns per call.

WHAT MUST NOT BREAK, pinned here. A cache that skips work is only correct if it never skips
discovery that should happen:
- a file recorded as unselected is discovered after a NEW selector names it (the generation moves);
- an entry carrying an old generation never suppresses a decision, however it got there;
- thread ownership is never cached: a selected file first started on a thread the subscription
  does not own is still discovered on the owner's later start;
- a subscription closed after the decision is never re-attached by it.
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable
from pathlib import Path
from types import CodeType

import pytest

from Wesker import monitoring
from Wesker.monitoring import (
    Subscription,
    release_monitoring_tool,
    subscribe,
    tool_id,
)


@pytest.fixture(autouse=True)
def _cleanup_monitoring():
    yield
    sys.monitoring.set_events(tool_id(), 0)
    release_monitoring_tool()


def _function_in(directory: Path, name: str) -> tuple:
    """A function whose code objects report a file under ``directory``. The file need not exist;
    the directory must, because a directory selector matches by path prefix only when `isdir`."""
    filename = str(directory / f"{name}.py")
    ns: dict = {}
    source = f"def {name}(x):\n    y = x + 1\n    return y\n"
    # S102: the test needs code objects whose co_filename lies under a selector's directory
    exec(compile(source, filename, "exec"), ns)  # noqa: S102
    return ns[name], filename


def _recorder() -> tuple[list[tuple[str, int]], Callable[..., None]]:
    seen: list[tuple[str, int]] = []

    def _on_line(code: CodeType, lineno: int, frame=None, run_token=None) -> None:
        seen.append((code.co_filename, lineno))

    return seen, _on_line


def test_a_file_cached_as_unselected_is_discovered_once_a_new_selector_names_it(
    tmp_path: Path,
) -> None:
    traced_dir = tmp_path / "traced"
    other_dir = tmp_path / "other"
    # A directory selector is a directory only if it exists (`subscribe` asks `isdir`).
    traced_dir.mkdir()
    other_dir.mkdir()
    fn, filename = _function_in(other_dir, "late")

    first_seen, first_cb = _recorder()
    first = subscribe(
        [], sys.monitoring.events.LINE, first_cb, selectors=[str(traced_dir)]
    )
    try:
        fn(1)
        assert (
            monitoring._unselected_files.get(filename)
            == monitoring._selector_generation
        ), "the unselected file is recorded under the live generation"
        assert first_seen == []

        second_seen, second_cb = _recorder()
        second = subscribe(
            [], sys.monitoring.events.LINE, second_cb, selectors=[str(other_dir)]
        )
        try:
            fn(2)
            assert {line for f, line in second_seen if f == filename} == {2, 3}, (
                "the new selector names the file: discovery must run despite the old entry"
            )
            assert first_seen == [], "the first subscription still does not name it"
        finally:
            second.close()
    finally:
        first.close()


def test_an_entry_with_an_old_generation_never_suppresses_discovery(
    tmp_path: Path,
) -> None:
    """However a stale entry got written (a decision that raced a subscribe writes the generation it
    read before deciding), only an entry equal to the live generation skips the decision."""
    fn, filename = _function_in(tmp_path, "stale")
    seen, cb = _recorder()
    handle = subscribe([], sys.monitoring.events.LINE, cb, selectors=[str(tmp_path)])
    try:
        monitoring._unselected_files[filename] = monitoring._selector_generation - 1
        fn(1)
        assert {line for f, line in seen if f == filename} == {2, 3}
    finally:
        handle.close()


def test_thread_ownership_is_decided_again_on_every_start(tmp_path: Path) -> None:
    fn, filename = _function_in(tmp_path, "owned")
    owner = threading.Thread(target=lambda: None)
    seen, cb = _recorder()
    owner_ident: list[int] = []
    handle = subscribe(
        [],
        sys.monitoring.events.LINE,
        cb,
        selectors=[str(tmp_path)],
        thread_filter=lambda tid: bool(owner_ident) and tid == owner_ident[0],
    )
    try:
        fn(
            1
        )  # started on a thread the subscription does not own: not attached, not cached
        assert seen == []
        assert filename not in monitoring._unselected_files

        def _run() -> None:
            owner_ident.append(threading.get_ident())
            fn(2)

        owner = threading.Thread(target=_run)
        owner.start()
        owner.join()
        assert {line for f, line in seen if f == filename} == {2, 3}
    finally:
        handle.close()


def test_a_subscription_closed_after_the_decision_is_not_reattached(
    tmp_path: Path,
) -> None:
    fn, _ = _function_in(tmp_path, "closed")
    _seen, cb = _recorder()
    handle = subscribe([], sys.monitoring.events.LINE, cb, selectors=[str(tmp_path)])
    retired: Subscription = handle.sub
    handle.close()

    monitoring._attach_discovered(fn.__code__, [retired])
    assert retired not in monitoring._subscriptions_by_code.get(fn.__code__, [])
    assert fn.__code__ not in monitoring._discovered_codes_by_sub.get(
        retired.sub_id, set()
    )
