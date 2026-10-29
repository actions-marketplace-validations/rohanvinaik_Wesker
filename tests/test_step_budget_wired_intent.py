"""Intent: Wesker #27 — a deterministic loop budget, not the wall clock, decides divergence.

Before this change `monitoring.step_budget` existed and was pinned but had no production caller, so
every mutant that never stops (D#80's `i += 1 -> pass`) ran until the wall clock fired and was filed
`undetermined`: a verdict that depends on how busy the machine is. The engine now counts the
ORIGINAL's loop iterations on each test, once per pass and under the same instrumentation, and
bounds every mutant observation of that test at `step_cap(count, factor, floor)`; exceeding it is
the named non-kill `diverged`. The budget is armed only where the original PASSED the test under
the count, so instrumentation can never become a verdict, and a stop is budget-relative: never a
kill, never a pass, never proof of nontermination.

The survivor-equivalence probes get the same treatment: they called both functions directly on
invented boundary inputs with no bound at all, and a function that loops on one hung the run.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import textwrap

from Wesker.engine import (
    SCORED_DISPOSITIONS,
    Mutant,
    MutationCategory,
    StepPlan,
    _run_test_with_timeout,
    evaluate_mutant,
    generate_mutants,
    mutant_disposition,
)
from Wesker.monitoring import (
    STEP_BUDGET_FACTOR,
    STEP_BUDGET_FLOOR,
    mutant_step_cap,
    original_step_observation,
    step_budget,
)

_FIRST_FALSE = """
def first_false(flags, start):
    i = max(start, 0)
    while i < len(flags) and flags[i]:
        i += 1
    return i
"""


def _load(node, filename: str):
    module = compile(ast.Module(body=[node], type_ignores=[]), filename, "exec")
    ns: dict = {}
    # S102: these tests compile their own fixture source and generated mutants; nothing else runs
    exec(module, ns)  # noqa: S102
    return ns[node.name]


def _compile(src: str):
    node = ast.parse(textwrap.dedent(src)).body[0]
    return node, _load(node, "<original>")


def _mutant(node, category, predicate):
    return next(
        m
        for m in generate_mutants(node, [category])
        if predicate(ast.unparse(m.mutated_node))
    )


# ── the pure decisions ──────────────────────────────────────────────────────────


def test_only_a_passing_counted_original_is_a_basis_for_a_cap():
    assert mutant_step_cap("passed", 10, 8, 100) == ("armed", 180)
    assert mutant_step_cap("passed", 0, 8, 100) == ("armed", 100)
    assert mutant_step_cap("failed", 10, 8, 100) == ("original_failed", None)
    assert mutant_step_cap("undetermined", 10, 8, 100) == (
        "original_undetermined",
        None,
    )
    assert mutant_step_cap("uncounted", 10, 8, 100) == ("original_uncounted", None)
    assert mutant_step_cap("unmeasured", 0, 8, 100) == ("unmeasured", None)


def test_what_the_originals_counted_run_established():
    assert original_step_observation("passed", True) == "passed"
    assert original_step_observation("passed", False) == "uncounted"
    assert original_step_observation("undetermined", True) == "undetermined"
    assert original_step_observation("uncontained", True) == "undetermined"
    for outcome in (
        "assertion",
        "exception",
        "crash",
        "nested_measurement",
        "diverged",
    ):
        assert original_step_observation(outcome, True) == "failed"


# ── the runner ──────────────────────────────────────────────────────────────────


def test_a_runaway_stops_at_the_cap_and_is_diverged_not_undetermined():
    node, _orig = _compile(_FIRST_FALSE)
    runaway = _mutant(node, MutationCategory.STMT, lambda s: "i += 1" not in s)
    fn = _load(runaway.mutated_node, "<m>")

    def test_case(f=fn):
        assert f([True, True, False], 0) == 2

    sink: list[int] = []
    # A generous wall bound: if the budget were not armed this would read "undetermined".
    result = _run_test_with_timeout(
        test_case,
        fn,
        False,
        10_000,
        step_codes=(fn.__code__,),
        step_cap=500,
        step_sink=sink,
    )
    assert result == "diverged"
    assert sink == [501]


def test_work_the_budget_cannot_count_is_still_bounded_by_the_wall():
    # The budget counts the target's OWN code. A runaway inside a helper it calls is not counted,
    # so the wall clock — the liveness bound — still ends it: `undetermined`, never a verdict.
    def helper():
        while True:
            pass

    def target():
        helper()

    def test_case(f=target):
        f()

    result = _run_test_with_timeout(
        test_case, target, False, 300, step_codes=(target.__code__,), step_cap=10
    )
    assert result == "undetermined"


def test_a_swallowed_stop_is_still_diverged():
    src = """
def stubborn(n):
    total = 0
    try:
        while True:
            total += 1
    except BaseException:
        return total
"""
    _node, fn = _compile(src)

    def test_case(f=fn):
        assert f(3) >= 0

    result = _run_test_with_timeout(
        test_case, fn, False, 10_000, step_codes=(fn.__code__,), step_cap=50
    )
    assert result == "diverged", (
        "a stop the target swallowed perturbed the run; it is no pass"
    )


# ── evaluate_mutant under a plan ─────────────────────────────────────────────────


def _first_false_tests(fn):
    def test_runs_the_loop(f=fn):
        assert f([True, True, False], 0) == 2

    return [test_runs_the_loop]


def test_the_engine_arms_the_budget_and_the_runaway_is_diverged_deterministically():
    node, original = _compile(_FIRST_FALSE)
    runaway = _mutant(node, MutationCategory.STMT, lambda s: "i += 1" not in s)
    verdicts = []
    for _ in range(3):
        plan = StepPlan(STEP_BUDGET_FACTOR, STEP_BUDGET_FLOOR)
        res = evaluate_mutant(
            runaway,
            _first_false_tests(original),
            original,
            timeout_ms=30_000,
            qualname="first_false",
            step_plan=plan,
        )
        verdicts.append((res.killed, res.killed_by))
        assert plan.originals and next(iter(plan.originals.values()))[0] == "passed"
    assert verdicts == [(False, "diverged")] * 3
    disposition = mutant_disposition(
        True, True, True, True, False, killed_by="diverged"
    )
    assert disposition == "diverged" and disposition not in SCORED_DISPOSITIONS


def test_a_terminating_mutant_one_iteration_over_the_original_is_never_misfiled():
    src = """
def count_up(n):
    i = 0
    while i < n:
        i += 1
    return i
"""
    node, original = _compile(src)
    one_more = _mutant(node, MutationCategory.BOUNDARY, lambda s: "i <= n" in s)

    def test_count(f=original):
        assert f(10) == 10

    plan = StepPlan(STEP_BUDGET_FACTOR, STEP_BUDGET_FLOOR)
    res = evaluate_mutant(
        one_more,
        [test_count],
        original,
        timeout_ms=30_000,
        qualname="count_up",
        step_plan=plan,
    )
    assert (res.killed, res.killed_by) == (True, "assertion")


def test_the_floor_covers_a_halving_loops_float_underflow_tail():
    # The floor's measured reason (docs/STEP_BUDGET_CALIBRATION_2026-10-25.md): `n //= 2 -> n /= 2`
    # turns a few-iteration halving loop into ~1,075 float halvings before underflow reaches 0.0.
    # That mutant TERMINATES, so it must be a kill, never a budget stop.
    src = """
def bit_length(n):
    count = 0
    while n > 0:
        n //= 2
        count += 1
    return count
"""
    node, original = _compile(src)
    halving = _mutant(node, MutationCategory.ARITHMETIC, lambda s: "n /= 2" in s)

    def test_bits(f=original):
        assert f(1) == 1

    plan = StepPlan(STEP_BUDGET_FACTOR, STEP_BUDGET_FLOOR)
    res = evaluate_mutant(
        halving,
        [test_bits],
        original,
        timeout_ms=30_000,
        qualname="bit_length",
        step_plan=plan,
    )
    state, count = next(iter(plan.originals.values()))
    assert state == "passed" and count <= 2
    assert (res.killed, res.killed_by) == (True, "assertion")


# ── a budgeted observation's time is not the mutant's to spend ─────────────────

_ADVANCE = """
def advance(flags, start):
    i = max(start, 0)
    while i < len(flags) and flags[i]:
        i += 1
    return i
"""


def _hand_mutant(original_src: str, old: str, new: str) -> Mutant:
    onode = ast.parse(textwrap.dedent(original_src)).body[0]
    mnode = ast.parse(textwrap.dedent(original_src).replace(old, new)).body[0]
    return Mutant(MutationCategory.ARITHMETIC, onode, mnode, f"{old} -> {new}")


def _evaluate_with_a_tight_allowance(mutant, tests, original, floor):
    # A 50 ms allowance and a slow budgeted observation stand in for a slow core: the corpus run
    # under `taskpolicy -b` flipped exactly these shapes before the allowance stopped paying.
    return evaluate_mutant(
        mutant,
        tests,
        original,
        timeout_ms=50,
        qualname="advance",
        step_plan=StepPlan(STEP_BUDGET_FACTOR, floor),
        liveness_ceiling_ms=60_000,
    )


def test_a_budget_stop_does_not_spend_a_later_tests_allowance():
    # `i *= 2` never leaves 0, so the first test runs away and is stopped at the cap; the second
    # starts at 1 and the mutant returns 4 for 3. The stop is slow here (a 400,000 floor), as
    # every stop is on a slow core: charged to the allowance, it left no time for the second test
    # and the mutant read `diverged` where a faster machine reads a kill.
    _node, original = _compile(_ADVANCE)
    mutant = _hand_mutant(_ADVANCE, "i += 1", "i *= 2")

    def test_runs_away_on_the_mutant(f=original):
        assert f([True, True, False], 0) == 2

    def test_kills_the_mutant_outright(f=original):
        assert f([True, True, True, False], 1) == 3

    res = _evaluate_with_a_tight_allowance(
        mutant,
        [test_runs_away_on_the_mutant, test_kills_the_mutant_outright],
        original,
        floor=400_000,
    )
    assert (res.killed, res.killed_by, res.tests_run) == (True, "assertion", 2)
    assert res.test_name.endswith("test_kills_the_mutant_outright")


def test_a_slow_terminating_observation_does_not_spend_a_later_tests_allowance():
    # `max(start, 1)` agrees with the original on a long run of True from 0 — slowly, 300,000
    # iterations under the count — and disagrees on [False]. Charged to the allowance, the first
    # test's time left the mutant `undetermined` before the second could kill it.
    _node, original = _compile(_ADVANCE)
    mutant = _hand_mutant(_ADVANCE, "max(start, 0)", "max(start, 1)")
    long_run = [True] * 300_000 + [False]

    def test_agrees_slowly(f=original):
        assert f(long_run, 0) == 300_000

    def test_kills_the_mutant_outright(f=original):
        assert f([False], 0) == 0

    res = _evaluate_with_a_tight_allowance(
        mutant,
        [test_agrees_slowly, test_kills_the_mutant_outright],
        original,
        floor=STEP_BUDGET_FLOOR,
    )
    assert (res.killed, res.killed_by, res.tests_run) == (True, "assertion", 2)


def test_no_budget_where_the_original_fails_the_test():
    node, original = _compile(_FIRST_FALSE)
    runaway = _mutant(node, MutationCategory.STMT, lambda s: "i += 1" not in s)

    def test_red_on_the_original(f=original):
        assert f([True, True, False], 0) == 99

    plan = StepPlan(STEP_BUDGET_FACTOR, STEP_BUDGET_FLOOR)
    res = evaluate_mutant(
        runaway,
        [test_red_on_the_original],
        original,
        timeout_ms=300,
        qualname="first_false",
        step_plan=plan,
    )
    assert next(iter(plan.originals.values()))[0] == "failed"
    # Unbudgeted, exactly as before: the wall clock bounds it.
    assert res.killed_by == "undetermined"


def test_a_test_that_opens_its_own_budget_keeps_working_under_a_plan():
    node, original = _compile(_FIRST_FALSE)
    runaway = _mutant(node, MutationCategory.STMT, lambda s: "i += 1" not in s)

    def test_with_its_own_budget(f=original):
        from inspect import unwrap

        with step_budget([unwrap(f).__code__], cap=100):
            assert f([True, True, False], 0) == 2

    plan = StepPlan(STEP_BUDGET_FACTOR, STEP_BUDGET_FLOOR)
    res = evaluate_mutant(
        runaway,
        [test_with_its_own_budget],
        original,
        timeout_ms=30_000,
        qualname="first_false",
        step_plan=plan,
    )
    # Our count could not nest inside the test's own budget, so the original "failed" under it and
    # no engine budget was armed; the test's own budget then stopped the mutant.
    assert next(iter(plan.originals.values()))[0] == "failed"
    assert (res.killed, res.killed_by) == (False, "diverged")


# ── both execution modes, end to end ───────────────────────────────────────────


def _loop_project(tmp_path):
    import importlib

    (tmp_path / "m.py").write_text(textwrap.dedent(_FIRST_FALSE))
    (tmp_path / "test_m.py").write_text(
        "from m import first_false\n\n\n"
        "def test_runs_the_loop():\n    assert first_false([True, True, False], 0) == 2\n"
    )
    node = ast.parse((tmp_path / "m.py").read_text()).body[0]
    sys.path.insert(0, str(tmp_path))
    m = importlib.import_module("m")
    tm = importlib.import_module("test_m")
    tm.test_runs_the_loop.__qualname__ = "test_m.py::test_runs_the_loop"
    return node, m.first_false, [tm.test_runs_the_loop]


def _drop_project(tmp_path):
    sys.path[:] = [p for p in sys.path if p != str(tmp_path)]
    sys.modules.pop("m", None)
    sys.modules.pop("test_m", None)


def _diverged_and_undetermined(result):
    dispositions = {r["mutant_id"]: r["disposition"] for r in result.unscored_records}
    diverged = sorted(k for k, v in dispositions.items() if v == "diverged")
    undetermined = sorted(k for k, v in dispositions.items() if v == "undetermined")
    return diverged, undetermined


def test_both_modes_stop_the_runaways_deterministically(tmp_path):
    from Wesker.ci import _PROJECT_ROOT
    from Wesker.engine import run_function_profiling
    from Wesker.filter import filter_categories

    node, func, tests = _loop_project(tmp_path)
    try:
        token = _PROJECT_ROOT.set(str(tmp_path))
        try:
            runs = [
                run_function_profiling(
                    node, "m.py::first_false", filter_categories(node), tests, func
                )
                for _ in range(2)
            ]
            iso = run_function_profiling(
                node,
                "m.py::first_false",
                filter_categories(node),
                tests,
                func,
                isolated=True,
            )
        finally:
            _PROJECT_ROOT.reset(token)
    finally:
        _drop_project(tmp_path)

    first, second = (_diverged_and_undetermined(r) for r in runs)
    assert first == second, "the same pass twice must name the same runaways"
    diverged, undetermined = first
    assert diverged, "D#80's `i += 1 -> pass` must be stopped by the budget"
    assert undetermined == [], "no runaway may be left to the wall clock"
    iso_diverged, iso_undetermined = _diverged_and_undetermined(iso)
    assert (iso_diverged, iso_undetermined) == (diverged, [])


# ── the equivalence probes ───────────────────────────────────────────────────────


def test_the_equivalence_probe_terminates_on_a_function_that_loops_on_a_boundary_input():
    # collatz(0) never terminates on the ORIGINAL; the probe invents 0. Run in a subprocess so a
    # regression is a failed test, not a hung suite.
    script = textwrap.dedent(
        """
        import ast
        from Wesker.engine import MutationCategory, check_equivalent, generate_mutants
        SRC = '''
        def collatz_steps(n):
            steps = 0
            while n != 1:
                n = n // 2 if n % 2 == 0 else 3 * n + 1
                steps += 1
            return steps
        '''
        import textwrap
        node = ast.parse(textwrap.dedent(SRC)).body[0]
        for m in generate_mutants(node, list(MutationCategory)):
            check_equivalent(node, m)
        print("TERMINATED")
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-800:]
    assert "TERMINATED" in proc.stdout
