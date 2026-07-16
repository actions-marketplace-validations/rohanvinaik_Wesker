"""`_reset_item` must invalidate fixtures the way pytest does — via `finish()`.

One collection serves every mutant, so each run resets the item. Assigning
`cached_result = None` instead of calling `finish()` looks equivalent and is not:
`finish()` is the only thing that empties `_finalizers`, and it early-returns when
`cached_result is None`. Nulling the cache therefore makes the fixture LOOK finished
while its finalizers stay queued, they accumulate across re-runs, and `FixtureDef.execute`
eventually trips `assert not self._finalizers` during SETUP — surfacing as a failing
assertion in a green suite.

ZERO-ARG ON PURPOSE — do not "clean these up" onto `tmp_path`. Wesker's own discovery
skips any test requiring a real fixture, so a fixture-taking test contributes NO kill
power against this very function: an earlier `tmp_path` version of this file pinned
0 of 19 behaviours while appearing to pass. The temp dir is therefore built in-body.
"""

from __future__ import annotations

import shutil
import tempfile
import textwrap
from pathlib import Path

from Wesker.pytest_runner import run_in_session

_FIXTURE_SUITE = """
    import pytest

    SETUPS = []
    TEARDOWNS = []

    @pytest.fixture
    def tracked():
        SETUPS.append(1)
        yield len(SETUPS)
        TEARDOWNS.append(1)

    def test_uses_fixture(tracked):
        assert tracked >= 1
"""

_BAD_TEARDOWN_SUITE = """
    import pytest

    @pytest.fixture
    def explodes():
        yield 1
        raise RuntimeError("teardown blew up")

    def test_with_bad_teardown(explodes):
        assert explodes == 1
"""


def _in_temp_suite(name, source, body):
    """Write `source` as a one-test suite in a fresh dir and run `body` in a live session.

    Unique module name per call: nested pytest.main imports test modules by name into
    sys.modules, so a shared filename would collide across cases.
    """
    root = Path(tempfile.mkdtemp(prefix=f"wesker_reset_{name}_"))
    try:
        (root / f"test_{name}.py").write_text(textwrap.dedent(source))
        return run_in_session(str(root), body)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_repeated_reruns_do_not_break_setup():
    """The regression: finalizers accumulated until pytest's own
    `assert not self._finalizers` fired in SETUP, so the item stopped reaching its CALL
    phase and a passing test was reported as a failing assertion."""

    def body(callables, session):
        for _ in range(25):
            callables[0]()  # raises if the item fails — including a setup failure
        return "ok"

    assert _in_temp_suite("rerun", _FIXTURE_SUITE, body) == "ok"


def test_finalizers_do_not_accumulate_across_reruns():
    """The mechanism, pinned directly: `_finalizers` must not grow run over run."""

    def body(callables, session):
        item = session.items[0]
        depths = []
        for _ in range(10):
            callables[0]()
            defs = [d for ds in item._fixtureinfo.name2fixturedefs.values() for d in ds]
            depths.append(max((len(d._finalizers) for d in defs), default=0))
        return depths

    depths = _in_temp_suite("accum", _FIXTURE_SUITE, body)
    assert max(depths) <= 2, f"finalizers accumulating across re-runs: {depths}"


def test_teardown_actually_runs_between_reruns():
    """The half that separates `finish()` from merely clearing `_finalizers`: real
    teardown must FIRE each run. Orphaning the finalizers would also stop the crash while
    silently skipping every teardown — a leak wearing a fix's clothes."""

    def body(callables, session):
        mod = session.items[0].module
        for _ in range(5):
            callables[0]()
        return len(mod.SETUPS), len(mod.TEARDOWNS)

    setups, teardowns = _in_temp_suite("teardown", _FIXTURE_SUITE, body)
    assert setups == 5, f"fixture should be set up once per run, got {setups}"
    assert teardowns == 5, f"fixture should be torn down once per run, got {teardowns}"


def test_the_cache_is_invalidated_between_runs():
    """`cached_result` must not survive a reset — a stale value hands the next run a
    finalized tmp_path / an undone monkeypatch."""

    def body(callables, session):
        item = session.items[0]
        callables[0]()
        from Wesker.pytest_runner import _reset_item

        _reset_item(item)
        defs = [d for ds in item._fixtureinfo.name2fixturedefs.values() for d in ds]
        return [d.cached_result for d in defs]

    cached = _in_temp_suite("cache", _FIXTURE_SUITE, body)
    assert cached, "no fixturedefs seen — the probe itself is wrong, not the reset"
    assert all(c is None for c in cached), (
        f"a fixture value survived the reset: {cached}"
    )


def test_a_raising_finalizer_does_not_escape_the_reset():
    """Stale teardown from a PREVIOUS run must not be attributed to this one: it would
    surface as a crash/kill for whatever mutant happens to be loaded."""

    def body(callables, session):
        results = []
        for _ in range(3):
            try:
                callables[0]()
                results.append("pass")
            except RuntimeError:
                results.append("runtime")
            except AssertionError:
                results.append("assertion")
        return results

    results = _in_temp_suite("badteardown", _BAD_TEARDOWN_SUITE, body)
    assert results[-1] != "assertion", (
        f"stale teardown leaked into a later run: {results}"
    )
