# Step-budget calibration — 2026-10-25 (W#27)

Every mutant observation of a test now runs under a deterministic loop budget:

    cap = STEP_BUDGET_FACTOR × N + STEP_BUDGET_FLOOR

`N` is the number of backward jumps the ORIGINAL made on that same test, counted under the same
`sys.monitoring` instrumentation the mutant runs under. A mutant that passes the cap is stopped and
filed `diverged`. That outcome is unscored and budget-relative, and it is never a kill. The budget
is armed only where the original passed the test under the count (`mutant_step_cap`); everywhere
else the observation is bounded by the wall clock alone, as it was before.

This document records how `STEP_BUDGET_FACTOR = 32` and `STEP_BUDGET_FLOOR = 10_000` were chosen.
It also records `STEP_PROBE_CAP` and `STEP_ITERATION_US`, and what the budget does not establish.

W#27 reserves the choice of `k` and the floor to the founder ("bring measured ratios on real
targets before choosing"). What follows is therefore the measured proposal and the rule that
produced it, and the founder may ratify or replace it. Either value is part of the mutation
policy's observation clause, so changing one moves the policy id.

## The objective, and the rule

The budget must never stop a mutant that terminates. A terminating mutant filed `diverged` loses a
verdict it would have earned, whether a kill or a survival. So the factor and floor are calibrated
against TERMINATING mutants only: the cap has to clear how far they go, with margin.

The calibration did not aim to complete more profiles. A smaller cap would turn more wall-bound
`undetermined` mutants into `diverged` sooner, but it would buy that by misfiling terminating ones.

**The rule.** Pick the smallest power-of-two factor, and the smallest floor on the 1-2-5 series,
that together leave at least 5× headroom over every terminating observation. "Headroom" here is
`cap / mutant count`. The 5× must hold at both ends:
- where `N` is large, the factor binds;
- where `N` is small, the floor binds.

## Corpus

Two sources, one synthetic and one real.

**Synthetic.** `docs/step_budget_calibration/` is committed, so the numbers below can be reproduced.
- `loops.py` holds 28 loop functions of common data-dependent shapes:
  - D#80's `first_false`;
  - both D#126 shapes, the seen-set walk `reachable` and `prune_fixed_point`;
  - `gcd`, `binary_search`, insertion and bubble sort, `sieve`, `collatz_steps`, `digit_sum`, `power`
    and `run_length`;
  - `levenshtein`, `merge_intervals`, `newton_sqrt`, `word_count`, `kmp_prefix` and `two_sum_sorted`;
  - `bisect_root`, `mat_mult`, `flatten`, `lcs_length`, `primes_below`, `chunk_sums`,
    `count_set_bits` and `bit_length`.
- `tests/test_loops.py` exercises each function at a realistic size: originals of up to 7,723
  iterations per test.
- `tests/test_loops_small.py` holds the 0–3-iteration originals, which are the floor's regime.

**Real code.** Five loop-bearing Detective functions, taken from a copy of Detective at `5723410`:
- `minimize.minimal_cover` and `minimize.coverage_by_test`;
- `kappa.reachable`, `kappa.components` and `kappa.marginal_coverage`.

Each was profiled through Wesker's profiling API against the plain zero-argument tests that call it.

**Measure mode.** Setting `WESKER_STEP_CALIBRATION_LOG=<file>` counts every original and every mutant
but enforces no cap. It writes one JSON row per (mutant, test) observation with these fields:
- the original's state and count;
- the mutant's count and result;
- both timings and the wall bound.

It is a calibration instrument, not a setting.

An observation is **terminating** when two things hold:
- the original passed under the count;
- the mutant then finished inside the wall: an assertion kill, a crash kill or a survival.

Wall-bound rows ended nothing, so they are reported separately.

Reproduce, from the repository root, with the project's own environment in `.venv`. The corpus
directory has its own `pyproject.toml`, so `uv run` from inside it would select the wrong project.
The log appends, so clear it first.

```bash
R="$PWD"; PY="$R/.venv/bin/python"
rm -rf /tmp/cal_full.jsonl /tmp/cal_small.jsonl /tmp/cal_small
cd docs/step_budget_calibration
WESKER_STEP_CALIBRATION_LOG=/tmp/cal_full.jsonl PYTHONPATH="$R" \
  "$PY" -m Wesker.cli loops.py --json --max-per-category 0 > /dev/null
# The floor's regime, unshadowed: only the small-original tests. With both files present, a
# realistic-size test kills most mutants first, and the small one is never observed.
mkdir -p /tmp/cal_small/tests && cp loops.py pyproject.toml /tmp/cal_small/ \
  && cp tests/test_loops_small.py /tmp/cal_small/tests/
(cd /tmp/cal_small && WESKER_STEP_CALIBRATION_LOG=/tmp/cal_small.jsonl PYTHONPATH="$R" \
  "$PY" -m Wesker.cli loops.py --json --max-per-category 0 > /dev/null)
"$PY" analyze.py /tmp/cal_full.jsonl /tmp/cal_small.jsonl
```

The efficiency-core rows come from the first command again, prefixed with `taskpolicy -b`.

## How far terminating mutants go

The canonical runs are the two commands above, about 60 s each on an M1 Max: 1,730 rows, of which
1,523 are terminating, across 26 functions. The table adds two earlier exploratory runs, made with
different sampling, and the 83 real-code rows. Together that is 3,606 rows and 3,176 terminating
observations across 31 functions. Neither addition moves any maximum.

| original count `N` | terminating obs | max mutant count | max ratio | binding observation |
|---|---|---|---|---|
| 0 | 54 | 2 | 2.00 | `two_sum_sorted` 0 → 2 (off-by-one) |
| 1–10 | 1,170 | 1,075 | 358 | `bit_length` 3 → 1,075 (`//=` → `/=`) |
| 11–100 | 999 | 1,085 | 21.3 | `bit_length` 51 → 1,085 (`//=` → `/=`) |
| 101–1,000 | 598 | 953 | 1.91 | `two_sum_sorted` 500 → 953 (off-by-one) |
| 1,001–10,000 | 355 | 14,523 | 4.44 | `primes_below` 3,272 → 14,523 |
| > 10,000 | 0 | — | — | — |

The real-code rows alone peak at a ratio of 1.40 (`kappa.reachable`, 5 → 7) and at a count of 28.

The small-`N` frontier is a generic shape, not a corpus accident. `n //= 2` → `n /= 2` turns a
halving loop into float halvings that reach `0.0` only after the subnormal range runs out. That is
about 1,075 + log₂ n iterations, whatever the original did. `//= 10` → `/= 10` gives the shorter
tail, about 325 iterations, that `digit_sum` showed.

| factor `k` | floor `F` | terminating misfiled | tightest headroom | binding observation |
|---|---|---|---|---|
| 16 | 5,000 | 0 | 3.95× | `primes_below` 3,272 → 14,523 |
| 32 | 2,000 | 0 | 1.95× | `bit_length` 3 → 1,075 |
| 32 | 5,000 | 0 | 4.74× | `bit_length` 3 → 1,075 |
| **32** | **10,000** | **0** | **7.90×** | `primes_below` 3,272 → 14,523 |
| 64 | 10,000 | 0 | 9.48× | `bit_length` 3 → 1,075 |

**Chosen: `k = 32`, `F = 10,000`.**
- **The factor.** At the large end it needs `k ≥ (5 × 14,523 − F) / 3,272`, which is 19.1 at
  `F = 10,000`, so 32 is the smallest power of two that qualifies. `k = 16` tops out at 4.29×, even
  with this floor.
- **The floor.** At the small end it needs `F ≥ 5 × 1,075 − 32 × 3 = 5,279`, so 10,000 is the next
  1-2-5 step. `F = 5,000` reaches only 4.74×.
- **Headroom at the chosen point:**
  - 7.90× at the large-end binding observation (cap 114,704);
  - 9.39× at the small-end binding observation (cap 10,096).

`tests/test_step_budget_wired_intent.py::test_the_floor_covers_a_halving_loops_float_underflow_tail`
pins the floor's reason. Its halving mutant is an assertion kill under `F = 10,000`. Under
`F = 500` or `F = 1,000` it is `diverged`; that was measured, and is the test's teeth.

**What a runaway costs** before it is stopped. Run times are at the measured p90 per counted
iteration: 0.92 µs on performance cores and 3.81 µs on efficiency cores. The wall allowance is at
`STEP_ITERATION_US`.

| `N` | cap | run time, P-core | run time, E-core | wall allowance |
|---|---|---|---|---|
| 0 | 10,000 | 9 ms | 38 ms | 160 ms |
| 1,000 | 42,000 | 39 ms | 160 ms | 672 ms |
| 10,000 | 330,000 | 0.30 s | 1.3 s | 5.3 s |
| 100,000 | 3,210,000 | 3.0 s | 12 s | 51 s |
| 1,000,000 | 32,010,000 | 29 s | 122 s | 512 s, capped by the aggregate deadline |

## The two auxiliary constants

**`STEP_ITERATION_US = 16.0`** sizes the wall that a budgeted observation gets (`armed_wall_ms`).
That wall is the original's own run plus `cap × 16 µs`, never below the wall the observation already
had, and never past the aggregate deadline. The wall therefore bounds liveness while the count
decides.

Wall-bound runaways measured these costs per counted iteration:
- on performance cores, 0.57 µs at p50 and 0.92 µs at p90, across 406 rows;
- under `taskpolicy -b` (efficiency cores, the slow-machine simulation W#27's acceptance names),
  3.15 µs at p50 and 3.81 µs at p90, across 90 rows.

16 µs is about four times the slower p90. A first draft used 4 µs, sized from the performance cores
alone. That is 1.05 times the efficiency-core p90, so on a slow core the wall, not the count, would
have decided.

The exception is a runaway whose operands grow exponentially. The `gcd` and `power` mutants that
square a bignum each iteration measured up to 11 µs per iteration (33 µs on efficiency cores) and
stalled at 20–30 counted iterations. A count cannot catch these, and they still end `undetermined`
at the wall.

**Why the wall had to widen.** Before this change, Detective's path gave each mutant
`max(50 ms, 50 × baseline)` and Wesker's CLI path gave it 500 ms. Neither leaves room for a cap of
`32 × N + 10,000` to fire before the wall does.

**`STEP_PROBE_CAP = 200_000`** is the original's budget on a synthesized equivalence-probe input,
where no test fixes a reference count. It is about 26 times the largest count any calibration
original made on a whole test: `sieve`, 7,723.

Before this change, committed Wesker `9362bc5` hung `check_equivalent` on `collatz_steps`. Its probe
inputs include `0`, `-1`, `-2` and `0.5`, and on each of them the original itself never terminates.
Under the budget, all 34 mutants finish in 9.4 s.

The probe rules:
- An input the original cannot finish inside 200,000 iterations is skipped as no evidence.
- A mutant stopped where the original finished is never "equivalent".

## Determinism

The count is a function of the code and the test's inputs, not of the machine's load. Two
comparisons bear this out, and every value in both agrees exactly:
- **Different sampling, different processes.** Two measure-mode runs of the same corpus shared 563
  (function, mutant, test) observations. Their original counts, terminating mutants' counts and
  results all agree.
- **Different cores.** The committed corpus under `taskpolicy -b`, about 4× slower per iteration,
  shares 908 observations with the performance-core run. All 908 original counts and results
  agree, and so do all 814 terminating mutants' counts.

  The two runs did not observe the same set (998 rows against 908). Two wall bounds of the CLI run
  account for the difference, both separate from the step budget:
  - On the performance cores, 20 functions were cut as `uncontained` when a measure-mode runaway's
    worker outlived its wall.
  - On the efficiency cores, 5 functions hit the CLI's 10 s per-function `--budget`.

## Enforce mode against measure mode

To check the wiring against the measurement, every corpus function was profiled through the engine
twice with the same tests: once in measure mode and once enforced. Joined per mutant, the 764
mutants moved as follows:
- 583 killed → killed, and 66 survived → survived. These are every mutant whose observations all
  terminated, and none of them moved.
- 100 undetermined → diverged: the runaways the count caught.
- 9 undetermined → killed. In each case the budget stopped a runaway on the first test in a few
  milliseconds, and a later small-original test then killed it on a terminating observation. Under
  measure mode the wall on the first test had used the mutant's whole allowance.
- 6 undetermined → undetermined: the exponential-bignum `gcd` and `power` runaways that a count
  cannot catch.

Zero mutants that terminate everywhere were filed `diverged`.

The same enforced pass was also run under `taskpolicy -b` and compared per mutant. On the first
wiring, 7 of the 764 differed:
- 3 kills read `diverged`;
- 3 survivors read `undetermined`;
- 1 kill was credited to a different test.

The cause was the mutant's shared allowance, a fixed wall. It was charged for each budgeted
observation's time, so a slower core ran out of it before the later tests could run. A budgeted
observation is already bounded by its own count and its widened liveness wall, so its time is no
longer charged. With that change, the performance-core and efficiency-core passes agree on all 764
dispositions, including which test is credited with each kill. The performance-core pass did not
change.

## What the budget does NOT establish

- **Nontermination.** Exceeding `k·N + F` is relative to the declared bound. Two kinds of
  terminating mutant can exceed it, and either is filed `diverged`:
  - one that deletes an early exit from a search over a long input, whose ratio to the original is
    input-dependent and unbounded;
  - one whose iteration count grows exponentially.

  Either costs a verdict. Neither produces a false one.
- **A kill or a survival.** `diverged` is unscored in both directions. It never raises the kill
  rate and never counts as a survivor. While any mutant has no verdict, a profile is not gateable.
- **Equivalence.** In the probes a budget stop only ever withholds the "equivalent" label.
- **Work outside the counted code.** The count is the backward jumps of the target's own code
  objects, and of the code nested in them, on the observing thread. Three kinds of loop are
  uncounted, so a runaway in them is still bounded only by the wall and ends `undetermined`:
  - a loop in a helper the target calls;
  - a loop in a C builtin;
  - a loop on another thread.
- **Anything about time.** The wall allowance is a machine-dependent liveness bound and decides no
  verdict. A slow loop body can still meet it first, and then the observation ends `undetermined`.
- **Coverage beyond the calibrated range.** No calibration original exceeded about 10⁴ iterations
  per test, so the factor is extrapolated above that. For a test whose original makes 10⁶
  iterations, a runaway's cap costs about 30 s, and the aggregate deadline may end it first.
- **A cap where there is no basis.** No cap is armed in these cases, and the wall alone bounds the
  observation, as before W#27:
  - the original failed under the count;
  - the original was not counted, because every monitoring tool id was held or a budget was
    already open, for example a test that opens its own `step_budget`;
  - the original was not observed at all.

## Routes that produced no calibration rows

- **Wesker self-profiling.** Through the Action this deadlocks on committed `9362bc5` as well, so
  the deadlock predates this change. A native sample shows the main thread and the worker both
  blocked in `rlock_acquire` inside `sys.monitoring` PY_START dispatch. It is reported to the lead
  separately (W#29/W#32), not fixed here.
- **Detective CLI audits.** Detective's live session runs with a sanitized environment, so
  `WESKER_STEP_CALIBRATION_LOG` never reaches the engine. Enforce mode is unaffected: the budgets
  are armed on that path, which the D#80 run shows.
- **Wesker's CLI on a Detective package module** logged no rows, and the run was stopped. The
  direct-API route above replaced it.
