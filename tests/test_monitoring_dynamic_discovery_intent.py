from __future__ import annotations

import os
import sys
import tempfile
import textwrap
from types import CodeType

import pytest

from Wesker.monitoring import (
    allocate_run_token,
    release_monitoring_tool,
    retire_run_token,
    subscribe,
    tool_id,
)


@pytest.fixture(autouse=True)
def _cleanup_monitoring():
    yield
    sys.monitoring.set_events(tool_id(), 0)
    release_monitoring_tool()


def test_dynamic_discovery_nested_closure_runtime():
    """Requirement: Bounded discovery of code objects loaded later.

    Scenario: Nested function or closure created at runtime.
    The broker identifies the inner closure via canonical target filename matching
    and enables the required local events (LINE).
    """
    lines_hit: list[tuple[CodeType, int]] = []
    token = allocate_run_token()

    # Create a target script in a temp file
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(
            textwrap.dedent("""
            def make_adder(x):
                def adder(y):
                    return x + y
                return adder
        """)
        )
        target_path = f.name

    try:

        def _on_line(
            code: CodeType,
            lineno: int,
            frame=None,
            run_token: int | None = None,
        ) -> None:
            lines_hit.append((code, lineno))

        handle = subscribe(
            [],
            sys.monitoring.events.LINE,
            _on_line,
            run_token=token,
            selectors=[target_path],
        )

        # Import and execute the module
        import importlib.util

        spec = importlib.util.spec_from_file_location("dyn_target_mod", target_path)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # Call outer function which creates the closure, then call closure
        add5 = mod.make_adder(5)
        res = add5(10)
        assert res == 15

        # Lines in both outer and inner functions should have been traced
        assert len(lines_hit) > 0
        # Check adder return line was recorded
        adder_code = add5.__code__
        adder_first_line = adder_code.co_firstlineno
        assert (adder_code, adder_first_line + 1) in lines_hit

        handle.close()
        retire_run_token(token)
    finally:
        if os.path.exists(target_path):
            os.unlink(target_path)


def test_dynamic_discovery_dynamically_imported_module_in_dir_selector():
    """Scenario: Module imported dynamically during test execution.

    When a module is imported in a directory covered by a directory selector,
    its functions are discovered and bound to the active subscription.
    """
    calls_observed: list[str] = []
    token = allocate_run_token()

    with tempfile.TemporaryDirectory() as tmpdir:
        pkg_file = os.path.join(tmpdir, "worker_pkg.py")
        with open(pkg_file, "w") as f:
            f.write(
                textwrap.dedent("""
                def compute_square(n):
                    return n * n

                def compute_cube(n):
                    return n * n * n
            """)
            )

        def _on_start(
            code: CodeType,
            offset: int,
            frame=None,
            run_token: int | None = None,
        ) -> None:
            calls_observed.append(code.co_name)

        handle = subscribe(
            [],
            sys.monitoring.events.PY_START,
            _on_start,
            run_token=token,
            selectors=[tmpdir],  # Directory prefix selector
        )

        import importlib.util

        spec = importlib.util.spec_from_file_location("worker_pkg", pkg_file)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        assert mod.compute_square(4) == 16
        assert mod.compute_cube(3) == 27

        assert "compute_square" in calls_observed
        assert "compute_cube" in calls_observed

        # An unrelated function outside tmpdir must not be observed
        def outside_func():
            return 42

        assert outside_func() == 42
        assert "outside_func" not in calls_observed

        handle.close()
        retire_run_token(token)


def test_dynamic_discovery_teardown_clears_global_events():
    """Closing all subscriptions with selectors resets global events to 0."""
    tid = tool_id()
    token = allocate_run_token()

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write("def foo(): return 1\n")
        path = f.name

    try:
        handle = subscribe(
            [],
            sys.monitoring.events.PY_START,
            lambda *args, **kw: None,
            run_token=token,
            selectors=[path],
        )

        # Global PY_START should be active
        events = sys.monitoring.get_events(tid)
        assert events & sys.monitoring.events.PY_START

        handle.close()
        retire_run_token(token)

        # Global events should now be 0
        events_after = sys.monitoring.get_events(tid)
        assert events_after == 0
    finally:
        if os.path.exists(path):
            os.unlink(path)
