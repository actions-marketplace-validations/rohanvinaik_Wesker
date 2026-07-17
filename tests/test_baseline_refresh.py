"""Tests for the INCREMENTAL session-baseline refresh (`SessionBaseline.replaced`,
`LazySessionBaseline.refresh`, and the splice `refresh_live_suite` drives).

Writing one test file used to invalidate the whole baseline, so the next read re-traced the
entire suite to learn what one file changed — `O(passes x suite)` for a consumer that writes
tests in a loop. These pin the two properties that make replacing that with a splice safe:

  * it produces the SAME baseline a full rebuild would (else the speedup buys a wrong verdict);
  * a name the written file SHARES with another module does not take that module's coverage
    with it — the failure that matters, because a test whose coverage is absent is one the
    mutation loop never runs, so every mutant it kills reads as a surviving behavioral gap.
"""

from __future__ import annotations

import os
import textwrap

import Wesker.ci as ci
from Wesker.engine import (
    _SESSION_BASELINE,
    LazySessionBaseline,
    SessionBaseline,
)


def _bl(traced, failing=(), inert=(), n_tests=0, truncated=()):
    return SessionBaseline(
        dict(traced), list(failing), set(inert), n_tests, set(truncated)
    )


# ── SessionBaseline.replaced: the splice itself ──────────────────


def test_replaced_keeps_unaffected_tests_and_takes_the_partial_for_affected():
    base = _bl({"test_a": {"f.py": {1}}, "test_b": {"f.py": {2}}}, n_tests=2)
    partial = _bl({"test_b": {"f.py": {9}}}, n_tests=1)

    out = base.replaced({"test_b"}, set(), partial, n_tests=2)

    assert out.traced["test_a"] == {"f.py": {1}}  # untouched test survives verbatim
    assert out.traced["test_b"] == {
        "f.py": {9}
    }  # affected test takes the NEW measurement
    assert out.n_tests == 2


def test_replaced_drops_an_affected_test_the_partial_no_longer_reports():
    # The file was rewritten and no longer defines test_b: its entry must GO, not linger.
    # A lingering entry claims coverage for a test that does not exist, which reads as
    # specified behaviour that nothing pins.
    base = _bl({"test_a": {"f.py": {1}}, "test_b": {"f.py": {2}}}, n_tests=2)
    out = base.replaced({"test_b"}, set(), _bl({}, n_tests=0), n_tests=1)
    assert "test_b" not in out.traced
    assert out.traced["test_a"] == {"f.py": {1}}


def test_replaced_purges_removed_ids_from_inert_but_keeps_live_ones():
    # `inert` is keyed by id(); an id whose object was freed can be REUSED by a later
    # allocation, and a stale entry would bar an unrelated test from kill attribution.
    base = _bl({}, inert={111, 222}, n_tests=2)
    out = base.replaced(set(), {111}, _bl({}, inert={333}), n_tests=2)
    assert out.inert == {222, 333}  # 111 removed, 222 (still live) kept, 333 added


def test_replaced_splices_failing_and_truncated_by_name():
    base = _bl(
        {}, failing=["test_a", "test_b"], truncated={"test_a", "test_b"}, n_tests=2
    )
    partial = _bl({}, failing=["test_b"], truncated={"test_b"})
    out = base.replaced({"test_b"}, set(), partial, n_tests=2)
    assert out.failing == ["test_a", "test_b"]  # a kept, b re-derived (not duplicated)
    assert out.truncated == {"test_a", "test_b"}


def test_replaced_clears_a_stale_failing_flag_the_rewrite_fixed():
    # The written file's earlier version assert-failed; the new one passes. If the name were
    # not dropped first, converge would keep reporting a wrong-expectation it already fixed.
    base = _bl({}, failing=["test_b"], truncated={"test_b"}, n_tests=1)
    out = base.replaced(
        {"test_b"}, set(), _bl({}, failing=[], truncated=set()), n_tests=1
    )
    assert out.failing == []
    assert out.truncated == set()


# ── LazySessionBaseline.refresh: laziness and the safe degrade ───


def test_refresh_does_not_force_a_build_that_never_happened():
    # An unbuilt baseline is not stale: the lazy build already reads the CURRENT suite.
    # Forcing a trace to service a write is the eager cost the laziness exists to defer.
    calls = []
    holder = LazySessionBaseline(lambda subset=None: calls.append(subset) or _bl({}))
    assert holder.refresh({"test_b"}, set(), [], 0) is False
    assert calls == []
    assert holder.built is False


def test_refresh_splices_into_a_built_baseline():
    def build(subset=None):
        return (
            _bl({"test_b": {"f.py": {9}}}, n_tests=1)
            if subset
            else _bl({"test_a": {"f.py": {1}}, "test_b": {"f.py": {2}}}, n_tests=2)
        )

    holder = LazySessionBaseline(build)
    holder.get()  # force the full build
    assert holder.refresh({"test_b"}, set(), [lambda: None], 2) is True
    assert holder.get().traced == {"test_a": {"f.py": {1}}, "test_b": {"f.py": {9}}}


def test_refresh_degrades_to_invalidate_when_the_partial_build_raises():
    # A partial build RUNS the consumer's test code and can fail in ways this module cannot
    # enumerate. A half-spliced baseline would under-report coverage -> false survivors, so
    # the fast path must be skippable, never wrong: drop the value and let the next read
    # re-trace, which is exactly what invalidation did unconditionally.
    state = {"full": 0}

    def build(subset=None):
        if subset is not None:
            raise RuntimeError("the consumer's test blew up mid-trace")
        state["full"] += 1
        return _bl({"test_a": {"f.py": {1}}}, n_tests=1)

    holder = LazySessionBaseline(build)
    holder.get()
    assert holder.refresh({"test_a"}, set(), [lambda: None], 1) is False
    assert holder.built is False  # value dropped, not left half-spliced
    holder.get()
    assert (
        state["full"] == 2
    )  # the next read paid a full rebuild — correct, just slower


# ── The property the whole change rests on: same answer as a rebuild ──


def test_refresh_equals_a_full_rebuild():
    suite = {
        "test_a": {"f.py": {1}},
        "test_b": {"f.py": {2}},
        "test_new": {"f.py": {3}},
    }

    def build(subset=None):
        names = subset if subset is not None else list(suite)
        return _bl({n: suite[n] for n in names if n in suite}, n_tests=len(names))

    holder = LazySessionBaseline(build)
    holder.get()
    holder.refresh({"test_new"}, set(), ["test_new"], len(suite))
    spliced = holder.get()

    fresh = LazySessionBaseline(build)
    rebuilt = fresh.get()

    assert spliced.traced == rebuilt.traced
    assert spliced.n_tests == rebuilt.n_tests


# ── The collision, end to end through refresh_live_suite ─────────


def _write(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(textwrap.dedent(body))
    return str(p)


def test_refreshing_one_file_keeps_a_same_named_test_in_another_module(
    tmp_path, monkeypatch
):
    """`traced` is keyed by __name__ and UNIONS duplicates across files.

    So a name the written file merely SHARES cannot be dropped on its own — the other
    owner's coverage would vanish with it, and every mutant that test kills would then
    read as a survivor. The splice must re-trace every CURRENT owner of an affected name.
    """
    target = _write(tmp_path, "test_written.py", "def test_shared():\n    pass\n")

    # A live callable from a DIFFERENT module that happens to share the name.
    def test_shared():  # noqa: D103 — stands in for the other module's test
        pass

    other = _write(tmp_path, "test_other.py", "def test_shared():\n    pass\n")
    test_shared.__wesker_origin__ = other

    traced_with: list[list[str]] = []

    def build(subset=None):
        names = [getattr(c, "__name__", "?") for c in (subset or [])]
        traced_with.append(names)
        return _bl({n: {"f.py": {1}} for n in names}, n_tests=len(names))

    holder = LazySessionBaseline(build)
    holder._value = _bl({"test_shared": {"f.py": {1}}}, n_tests=2)
    holder._built = True

    suite_token = ci._LIVE_SUITE.set([test_shared])
    base_token = _SESSION_BASELINE.set(holder)
    try:
        ci.refresh_live_suite(str(tmp_path), target)
    finally:
        ci._LIVE_SUITE.reset(suite_token)
        _SESSION_BASELINE.reset(base_token)

    assert traced_with, "the splice never ran"
    # The other module's same-named test is re-traced ALONGSIDE the written file's, so the
    # union under that key still accounts for it. Dropping the key and re-adding only the
    # written file's test would silently delete it.
    assert "test_shared" in holder.get().traced
    assert sum(n == "test_shared" for n in traced_with[-1]) >= 2, (
        f"both owners of the shared name must be re-traced, got {traced_with[-1]}"
    )


def test_refresh_live_suite_is_a_noop_with_no_live_session(tmp_path):
    # The non-live path re-collects on every call and has nothing to invalidate.
    assert ci.refresh_live_suite(str(tmp_path), str(tmp_path / "test_x.py")) == 0


def test_refresh_live_suite_replaces_only_the_written_files_callables(tmp_path):
    target = _write(tmp_path, "test_w.py", "def test_one():\n    pass\n")

    def kept_test():
        pass

    kept_test.__wesker_origin__ = os.path.join(str(tmp_path), "test_kept.py")

    suite_token = ci._LIVE_SUITE.set([kept_test])
    try:
        ci.refresh_live_suite(str(tmp_path), target)
        live = ci._LIVE_SUITE.get()
    finally:
        ci._LIVE_SUITE.reset(suite_token)

    assert kept_test in live  # the other file's callable is untouched
