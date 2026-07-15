"""Live-session pytest execution — the runner that makes Wesker a real mutation tester.

WHY THIS EXISTS
---------------
``pytest_discovery`` collects with ``--collect-only``, which tears the session down
the moment collection finishes. The items it hands back are dead objects: no fixture
machinery, no conftest, no setup/teardown. That single fact is the root of Wesker's
execution-layer gap — its own docstring concedes it ("Tests requiring real runtime
fixtures ... are skipped for now"). Downstream, every fixture-taking test is silently
DROPPED from the callable set, so a mutant only those tests could kill is scored a
survivor, and the kill rate is a claim about the harness rather than the suite.

The fix is not to reconstruct fixtures ourselves — it is to never leave the session.
``pytest_runtestloop`` fires with the session LIVE and every item fully resolvable, so
running the whole mutation loop inside that hook buys the real runner for free:
fixtures, conftest, parametrize, setup/teardown, markers, and pytest's own pass/fail
verdict. One collection, no subprocess per mutant — Wesker's speed claims survive
intact, because the cost model is unchanged.

THE INTEGRATION IS ADDITIVE, BY DESIGN
--------------------------------------
``_run_test_with_timeout`` only ever calls ``test_fn()``. So an item is wrapped as a
zero-arg callable that runs it through the real protocol and RAISES on failure. The
existing engine then works unchanged — value precedence, greedy/DOF selection,
test-impact scoping, equivalence — and every symbol Detective imports keeps its exact
signature and semantics. This module adds a better source of callables; it replaces
nothing.

VALUE PRECEDENCE IS PRESERVED
-----------------------------
``runtestprotocol`` swallows the exception into a report, which would flatten every
kill to "crash" and destroy the assertion-vs-crash distinction the engine's
crash-as-spec precedence depends on. A ``pytest_runtest_makereport`` hookwrapper
captures the TRUE exception type per item, and the wrapper re-raises a matching
exception, so ``killed_by`` stays honest.
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
from typing import Any, Callable

__all__ = ["session_callables", "run_in_session"]

try:  # pytest is an OPTIONAL dependency — this module degrades to a no-op without it.
    import pytest as _pytest

    _hookwrapper = _pytest.hookimpl(hookwrapper=True)
except Exception:  # pragma: no cover — no pytest: run_in_session returns None anyway

    def _hookwrapper(fn):  # type: ignore[misc]
        return fn


class _ExcCapture:
    """Records each item's real exception — ``runtestprotocol`` would otherwise bury it
    in a report and every kill would read as "crash", destroying value precedence.

    The ``hookimpl(hookwrapper=True)`` marker is REQUIRED, not decoration: pluggy
    decides a hook is a wrapper from the marker, not from the presence of ``yield``.
    Unmarked, this generator is called as a plain hook, returns a generator OBJECT
    instead of a report, and the makereport chain breaks — every item then "fails",
    including the unmutated baseline, and the guard bars the entire suite.
    """

    def __init__(self) -> None:
        self.last: dict[str, BaseException | None] = {}

    @_hookwrapper
    def pytest_runtest_makereport(self, item, call):  # type: ignore[no-untyped-def]
        outcome = yield
        rep = outcome.get_result()
        if rep.when == "call" or (rep.failed and rep.when in ("setup", "teardown")):
            exc = getattr(call, "excinfo", None)
            if exc is not None:
                self.last[item.nodeid] = exc.value
            elif rep.when == "call" and not rep.failed:
                self.last[item.nodeid] = None


def _reset_item(item: Any) -> None:
    """Return a already-run item to a runnable state, so one collection serves every
    mutant.

    BOTH steps are required. ``_initrequest()`` rebuilds the ``FixtureRequest``, but
    pytest caches each fixture's VALUE on its ``FixtureDef`` (``cached_result``), and
    that cache outlives the request. After ``runtestprotocol(..., nextitem=None)`` the
    teardown for those values has already fired, so reusing them hands the next run a
    finalized ``tmp_path`` / an undone ``monkeypatch`` — the test then fails for reasons
    unrelated to any mutant, and those failures are attributed as kills.

    This mirrors ``pytest-rerunfailures``' reset, which does the same two steps for the
    same reason. Failing quietly is the danger: run 1 is perfect, so a small smoke test
    (few items, trivial fixtures) never reveals it.
    """
    init = getattr(item, "_initrequest", None)
    if init is not None:
        init()
    info = getattr(item, "_fixtureinfo", None)
    name2defs = getattr(info, "name2fixturedefs", None) or {}
    for defs in name2defs.values():
        for fixturedef in defs:
            if getattr(fixturedef, "cached_result", None) is not None:
                fixturedef.cached_result = None


def _make_item_callable(item: Any, capture: _ExcCapture) -> Callable[[], None]:
    """Wrap a LIVE pytest item as a zero-arg callable that raises on failure.

    THE PARAMETERS ARE KEYWORD-ONLY ON PURPOSE — this callable must accept NO
    positional argument. ``evaluate_mutant``'s unpatched path calls
    ``test_fn(mutated_func)``, injecting the function as a positional arg (a contract
    only Wesker's own inline tests observe), and falls back to ``test_fn()`` on
    ``TypeError``. With plain defaults, that injection silently BINDS over the first
    parameter — the wrapper then operates on the mutant instead of its item and dies in
    its own body, which is attributed as a kill. Measured on Prism: 362 of 445 tests
    (exactly those whose module lacks the target name, i.e. ``patched=False``) failed
    this way. Keyword-only makes the positional call a clean ``TypeError``, so the
    engine's existing fallback runs the item correctly. This is the same
    fixture-injection defect this runner exists to fix, reintroduced one layer up.

    RE-RUNNABILITY: one collection must serve every mutant, so each run resets the item
    via :func:`_reset_item` — both the request AND pytest's cached fixture values.

    THE GLOBALS REBIND IS LOAD-BEARING — do not "simplify" it away.
    ``_patch_mutant_into_test`` installs the mutant by looking up the target name in
    ``test_fn.__globals__``. A plain closure defined here carries THIS module's globals,
    so the engine would patch the mutant into ``Wesker.pytest_runner`` — the test never
    sees it, every mutant survives, and the run reports a confident 0%. Rebinding the
    wrapper's globals to the test module's ``__dict__`` makes the callable live where it
    semantically belongs, so the engine's existing (unmodified) patch logic resolves the
    same namespace it would for a directly-collected test function.

    It also closes a collision hazard: with this module's globals, profiling a function
    named ``os``/``io``/``sys``/``contextlib`` would overwrite the runner's OWN imports
    mid-run. Every free name below is bound as a keyword-only default rather than a
    global, so the rebound function needs nothing but builtins.
    """
    import types

    from _pytest.runner import runtestprotocol

    def run(  # type: ignore[no-untyped-def]
        *, _item=item, _cap=capture, _rtp=runtestprotocol, _reset=_reset_item
    ) -> None:
        _cap.last.pop(_item.nodeid, None)
        _reset(_item)
        reports = _rtp(_item, nextitem=None, log=False)
        if not any(r.failed for r in reports):
            return
        exc = _cap.last.get(_item.nodeid)
        if exc is not None:
            # Re-raise the ORIGINAL exception so the engine's assertion-vs-crash
            # precedence sees what actually happened, not a generic failure.
            raise exc
        raise AssertionError(f"pytest reported failure for {_item.nodeid}")

    name = str(getattr(item, "name", "test")).split("[")[0]
    mod = getattr(item, "module", None)
    mod_globals = getattr(mod, "__dict__", None)
    if isinstance(mod_globals, dict):
        rebound = types.FunctionType(
            run.__code__, mod_globals, name, run.__defaults__, run.__closure__
        )
        # FunctionType's argdefs carries __defaults__ only; keyword-only defaults live
        # in __kwdefaults__ and must be copied across or every binding above is lost.
        rebound.__kwdefaults__ = dict(run.__kwdefaults__ or {})
        run = rebound
    run.__name__ = name
    run.__qualname__ = str(getattr(item, "nodeid", name))
    if mod is not None:
        # inspect.getmodule() fallback in _patch_mutant_into_test keys off __module__.
        run.__module__ = getattr(mod, "__name__", run.__module__)
    fn = getattr(item, "function", None)
    if fn is not None:
        # __wrapped__ makes introspection tell the TRUTH about which test this is.
        # inspect.getsource() follows it (via inspect.unwrap); without it, every wrapper
        # reports THIS module's `run` source — identical for every item in the suite.
        # Consumers content-hash test sources to decide whether a cached verdict is
        # still valid (Detective's verdict_cache.tests_fingerprint does exactly this),
        # so a constant source collapses the fingerprint: editing a test would no longer
        # invalidate its cache and stale verdicts would be served as fresh ones — the
        # false-survivor bug that cache exists to prevent.
        run.__wrapped__ = fn
    return run


def session_callables(session: Any, capture: _ExcCapture) -> list[Callable[[], None]]:
    """Every collected item, as engine-ready zero-arg callables. Fixture-taking tests
    included — that is the entire point."""
    return [_make_item_callable(it, capture) for it in session.items]


def run_in_session(
    project_root: str,
    body: Callable[[list[Callable[[], None]], Any], Any],
    paths: list[str] | None = None,
    quiet: bool = True,
) -> Any:
    """Run ``body(callables, session)`` inside a LIVE pytest session.

    ``body`` receives the full collected suite as engine-ready callables and the live
    session, and returns whatever the caller needs; that value is returned here.

    ``quiet`` suppresses PYTEST's own chatter (collection banners, the progress line) —
    NOT the caller's output. ``body`` runs inside ``pytest.main``, so a blanket redirect
    would swallow everything the caller prints: a CLI wrapped in this seam would emit its
    entire report into a StringIO and appear to do nothing at all. The caller's real
    streams are therefore captured before the redirect and restored around ``body``.

    ``body``'s exceptions PROPAGATE — they are never converted to a ``None`` return.
    ``None`` means exactly one thing: no live session could be started. Conflating that
    with "the body raised" is a real defect, not a nicety: ``pytest.main`` swallows a
    ``SystemExit`` raised inside the loop hook, so a caller's argument-validation error
    surfaced here as "no live pytest session", which sent the caller down its LOUD
    fallback path — printing a false warning, silently re-running the whole command with
    weaker discovery, and only then reporting the real error. An exception from the body
    is the body's business; this seam's only verdict is session-or-no-session.

    Returns ``None`` when pytest is unavailable, collection fails, or nothing is
    collected — so a caller can fall back to the legacy path exactly as before. The
    fallback must be LOUD at the call site: silently degrading to a different, weaker
    test set is what let a fixture-driven repo report a fabricated 100%.
    """
    try:
        import pytest
    except ImportError:
        return None

    box: dict[str, Any] = {}
    capture = _ExcCapture()
    # Bound BEFORE any redirect is entered, so `body` can be handed the caller's own
    # streams rather than the suppression sink.
    real_stdout, real_stderr = sys.stdout, sys.stderr

    class _Driver:
        def pytest_runtestloop(self, session):  # type: ignore[no-untyped-def]
            if session.testsfailed and not session.config.option.continue_on_collection_errors:
                return None  # let pytest handle collection errors normally
            box["ran"] = True
            calls = session_callables(session, capture)
            try:
                if quiet:
                    with (
                        contextlib.redirect_stdout(real_stdout),
                        contextlib.redirect_stderr(real_stderr),
                    ):
                        box["result"] = body(calls, session)
                else:
                    box["result"] = body(calls, session)
            except BaseException as exc:  # noqa: BLE001 — captured to re-raise below
                # pytest.main would otherwise absorb this (SystemExit especially) and the
                # caller would see an indistinguishable None. Stash and re-raise outside.
                box["exc"] = exc
            return True  # the loop is ours; pytest must not also run the suite

    args = ["-q", "-p", "no:cacheprovider", "--no-header"]
    args += paths or ["."]
    cwd = os.getcwd()
    prev_path = list(sys.path)
    try:
        os.chdir(project_root)
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        if quiet:
            with (
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                pytest.main(args, plugins=[_Driver(), capture])
        else:
            pytest.main(args, plugins=[_Driver(), capture])
    except Exception:
        return None
    finally:
        sys.path[:] = prev_path
        with contextlib.suppress(Exception):
            os.chdir(cwd)

    if "exc" in box:
        raise box["exc"]  # the body's failure is the caller's, not a missing session
    if not box.get("ran"):
        return None
    return box.get("result")


# NOTE: there is deliberately no `with live_session(root) as callables:` helper.
# The callables are only valid while the session is alive, i.e. INSIDE the
# `pytest_runtestloop` hook. Yielding them out of a context manager would hand the
# caller items whose fixtures have already been torn down — reintroducing the exact
# dead-item bug this module exists to fix, but harder to see. Callers must do their
# work inside `body`; the inversion of control is the point, not an inconvenience.
