# Wesker

**One mutant per behavioral dimension — provably optimal, and measured at exactly 1.00 on a real repository.**

<p align="center">
  <a href="https://github.com/rohanvinaik/Wesker/actions/workflows/ci.yml"><img src="https://github.com/rohanvinaik/Wesker/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://sonarcloud.io/summary/new_code?id=rohanvinaik_Wesker"><img src="https://sonarcloud.io/api/project_badges/measure?project=rohanvinaik_Wesker&amp;metric=alert_status" alt="Quality Gate"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-3367d6.svg" alt="License: MIT"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10+-3367d6.svg" alt="Python 3.10+"></a>
  <br>
  <a href="https://github.com/rohanvinaik/Wesker/actions/workflows/spec-badges.yml"><img src="https://raw.githubusercontent.com/rohanvinaik/Wesker/badges/.github/badges/sigma.svg" alt="Mean σ"></a>
  <a href="https://github.com/rohanvinaik/Wesker/actions/workflows/spec-badges.yml"><img src="https://raw.githubusercontent.com/rohanvinaik/Wesker/badges/.github/badges/mutation-kill-rate.svg" alt="Mutation Kill Rate"></a>
  <a href="https://github.com/rohanvinaik/Wesker/actions/workflows/spec-badges.yml"><img src="https://raw.githubusercontent.com/rohanvinaik/Wesker/badges/.github/badges/mcdc.svg" alt="MC/DC"></a>
</p>

`8 semantic categories · 1.00 mutants per behavioral dimension · Fully deterministic`

<div align="center">

$$\mathrm{SC}(f)=1 \quad\Longleftrightarrow\quad \underbrace{\log_2\bigl\lvert\,\{f\}\cup\mathrm{survivors}\,\bigr\rvert}_{\displaystyle H(f \,\mid\, \mathrm{tests})}=0$$

*Every surviving mutant is one bit of behavior your tests never asked for.*
*A function is fully specified exactly when that set collapses to the function itself — when its conditional entropy hits zero.*

</div>

Mutation testing measures what your tests actually pin down: change the code, see whether a
test complains. Every mutation that slips through silently is a behavior your suite never
constrained — a gap line coverage cannot see. DeMillo, Lipton and Sayward formalized it in 1978.

Cost was always the objection, and the tools got fast. mutmut 3 pools workers and clears
thousands of mutants a minute. But speed was only half the problem.

**The other half: the denominator is an artifact.** Enumerate every change an operator can
express and you count the same gap many times over. What comes out is weighted by the
operator's enumeration — not by your code.

**Wesker counts the questions instead of the phrasings.**

```
Detective · 25 files · 271 functions

  the questions            2,795
  ─────────────────────────────────
                   mutants  per dim
  mutmut 3           8,657     3.10
  Wesker exhaustive  5,693     2.04
  Wesker DOF         2,795     1.00
```

**2,795 questions. mutmut asks them 8,657 times.**

Some changes ask the same question. An unconstrained return value can be phrased forty
ways — forty survivors, one fact. The score is weighted by the operator's enumeration,
not by your code.

**Half of mutmut's universe is a single fact.** 4,212 of its 8,657 mutants are in code
with no test at all — *"this is untested,"* reported four thousand times.

Exhaustive mode is the ceiling: every mutant, 2.04 per question. **DOF mode is the claim —
2,795 mutants, 2,795 questions, 1.00.** One mutant per question, on a real repository.

That 1.00 was not tuned toward. Cover sets here are singletons, so greedy is **exactly**
optimal — not the (1−1/e) that bounds general submodular covers. The theorem says
one-per-dimension is achievable. The run says achieved.

And it costs nothing: DOF reproduces the exhaustive verdict with **98.26% agreement and
zero false "specified" claims**. Where it differs it *under*-claims. Run `--complete` and
the ceiling comes back unchanged — it isn't a fallback, it's the receipt.

---

## What mutation testing actually measures

Line coverage tells you which code *executed*. Mutation testing tells you which *behaviors* your tests constrain. These are different questions.

A function with 99% line coverage can still have a 40% kill rate — meaning 60% of its behavioral dimensions (its outputs, its boundaries, its branch logic) could change without a single test noticing. The tests prove the code runs. They do not prove what it computes.

Each surviving mutant is a specific alteration that changes behavior and goes unnoticed. Taken together, the survivors are a constructive map of everything the tests *don't* require the function to do — its **negative space**. The kill rate measures how much of that behavior is actually pinned down: **specification completeness**, the degree to which the suite determines what the code does.

---

## Eight categories tell you *what kind* of gap you have

Not just "a mutant survived," but *which behavioral dimension* the tests leave unconstrained:

| Category | What it mutates | What survival means |
|----------|----------------|-------------------|
| **VALUE** | Constants (`0`→`1`, `True`→`False`, `"x"`→`""`) | Tests don't pin exact outputs |
| **BOUNDARY** | Comparisons (`<`↔`<=`, `>`↔`>=`, `==`↔`!=`) | Tests don't exercise boundary conditions |
| **ARITHMETIC** | Operators (`+`↔`-`, `*`↔`/`, `//`→`/`, unary `-`) | Tests don't verify computations |
| **LOGICAL** | Boolean logic (`and`↔`or`, drop `not`) | Tests don't exercise conditional composition |
| **SWAP** | Argument order in calls | Tests can't distinguish argument positions |
| **STATE** | `self.x = …`→dropped, `return x`→`return None` | Tests don't verify side effects or return values |
| **TYPE** | `isinstance(x, T)`→`True` | Tests don't exercise type guards |
| **STMT** | Deletes a statement: `items.append(y)`, `cfg[k] = v`, `total = abs(total)` | Tests don't notice the statement's effect at all |
| **EXCEPTION** | Raised type, handler body→`pass`, caught type→`BaseException` | Tests don't pin what raises, what's caught, or what a handler does |

The category **is** the diagnosis. A VALUE survivor says *assert the exact value, not just the shape*. A BOUNDARY survivor says *test at the boundary, not near it*. An ARITHMETIC survivor says *verify the computation, not just that it returns a number*. The fix is always specific — never "write more tests."

Together these cover the standard operator set from the literature — AOR, ROR (complete: boundary shift, direction reversal, equality collapse, and both predicate constants), COR, UOI — plus **SDL**, which the deletion-operator literature (Delamaro & Offutt) ranks among the highest-value operators precisely because it catches what operator-*replacement* structurally cannot, and domain operators for state, type guards and exception behavior.

STMT and EXCEPTION exist because the gaps they cover all fail in the same direction — **the refactor passes and the behavior changed**:

- `total = abs(total)` — no operator deleted a *rebinding*, so that mutant was not a survivor; it was outside the universe, uncounted.
- `def f(cfg): cfg[k] = v` — mutating a caller's object had no operator at all (STATE only ever targeted `self.x`), so a refactor that copies instead of aliasing passed every return-value assertion a suite had.
- Extraction across a `try` boundary changes what raises where — and nothing pinned it.

---

## How it gets fast without losing soundness

The cost drops multiplicatively across three layers. Each is provably safe: no information is lost at any one of them.

### Layer 1 · In-process AST mutation — 10–50×

Traditional tools spawn a subprocess per mutant, rewrite source files on disk, and invoke the test runner externally — roughly 400 ms of overhead per mutant before a single test executes. For 200 mutants, that is 80 seconds of pure startup cost.

Wesker compiles mutant ASTs in memory, patches them into a sandboxed namespace through the test's `__globals__`, and evaluates in-process. No subprocess, no disk I/O, no file rewrites.

This is a real reduction against a *subprocess-per-mutant* tool, and a modest one against a modern pooled runner: mutmut 3 forks a worker pool and reaches ~9 ms/mutant, so the honest gain here is single-digit, not the ~400× a subprocess cost model would imply. The layer that carries the result is not this one — it is Layer 4.

This follows the **meta-mutant dispatch** pattern validated by mutest-rs (Lévai & McMinn, ICST 2023) and mu2's `MutationClassLoader` (Vikram & Padhye, ISSTA 2023). The soundness argument is direct: the mutated function is compiled from the same AST a file-rewriting tool would produce, and evaluated by the same assertion. The execution path differs; the observable semantics are identical.

### Layer 2 · Categorical exclusion, the Monty Hall filter — 2–5×

Before generating a single mutant, Wesker walks the AST and asks which categories even *have* a syntactic target:

- No comparison operators → **BOUNDARY** mutants cannot exist. Skip.
- No `self.x = …` assignments → **STATE** cannot exist. Skip.
- No arithmetic operators → **ARITHMETIC** cannot exist. Skip.
- Fewer than two call arguments → **SWAP** cannot exist. Skip.

This is not sampling — it is elimination of structural impossibilities. If the target for a category is absent from the AST, no mutant in that category can be generated, and skipping it loses exactly nothing. A typical function has 3–4 applicable categories out of 7, cutting the space 40–60% before any test runs. The game-show host opens the doors with no prize behind them; the AST tells you which doors those are.

### Layer 3 · Targeted test discovery — 5–20×

Traditional tools run the entire suite against every mutant. For 300 tests, that is 300 invocations per mutant — and almost none of those tests can touch the mutated function.

Wesker resolves covering tests in three tiers: **convention** (`src/query.py` → `tests/test_query.py`), then **static AST impact** (scan test files for references to the mutated name), then **full fallback** only if the first two find nothing. Most functions resolve at tier 1, and each mutant runs against 3–15 tests rather than the full suite. The argument, again, is exact: a test that neither imports, references, nor transitively calls the mutated function cannot detect the mutation. Running it is pure waste.

This layer is the one place the comparison can be made cleanly, because it is a single flag on
the same engine: `scope_tests=False` **is** classical mutation testing — every test against
every mutant — so the two arms share an implementation, a mutant set, a runner, and a machine.
Nothing is confounded but the thing under test.

| Repo | Tests | Every test × every mutant | Covering tests only | Ratio |
|------|-------|---------------------------|---------------------|-------|
| ModelAtlas | 1,000 | 1,625 s | **348 s** | **4.7×** |
| Detective | 306 | 966 s | **141 s** | **6.9×** |
| Prism · `economics.py::analyze` | 421 | 33.6 s | **1.8 s** | **18.7×** |

The ratio is the smaller half of the result. At the same per-file budget the classical arm did
not merely cost more — **it did not finish**, truncating 9 functions on Detective and 7 on
ModelAtlas, so what it reports is a sample of whatever was cheap to reach. The scoped arm
truncated 0 and 2 respectively. A cost model that only bites when the budget runs out is not a
performance footnote; it is the reason the resulting percentage cannot be trusted.

(Single run per repo, one machine, no variance bars — an effect this size does not need them,
but it is a measurement, not a benchmark suite. `scope_tests` was Wesker's own default until
these numbers were taken, so the slow arm is not a straw man: it is what this tool shipped.)

### The combined cost model

Traditional mutation testing costs

$$O\big(\text{functions} \times \text{mutants/fn} \times \text{subprocess startup} \times \text{full suite}\big).$$

Wesker costs

$$O\big(\text{functions} \times \text{applicable mutants} \times \text{in-process toggle} \times \text{covering tests}\big).$$

Measured on Detective, mutmut 3.6 against Wesker over a BYTE-IDENTICAL target set — the
same 25 files, 271 functions. (An earlier draft of this table read 3.92, because mutmut had
been pointed at `Detective/` recursively and Wesker at `Detective/*.py`. Same story, wrong
number; the mismatch inflated it by a quarter.)

| Factor | mutmut 3 | Wesker | Ratio |
|--------|----------|--------|-------|
| Behavioral dimensions (the questions) | — | **2,795** | — |
| Mutants written | 8,657 | 5,693 exhaustive · **2,795 DOF** | — |
| **Mutants per dimension** | **3.10** | 2.04 exhaustive · **1.00 DOF** | **3.1×** |
| Mutants in untested code | **4,212 (49%)** | — | one fact, 4,212 times |
| Dimension-verdict agreement vs exhaustive | — | **98.26%**, zero false "specified" | — |

**The reduction is in redundancy, not in rigour.** Wesker does not test fewer things — it
tests each thing once. Half of mutmut's universe is a single fact ("this code has no
tests") restated four thousand times; most of the rest is one gap phrased several ways.
Neither is a property of your code.

The honest ledger, since the numbers above are the ones that matter and these are not:

- **We are not faster per mutant.** mutmut 3 runs a forking worker pool and did all 8,657
  in 81s on this repo — about 9 ms/mutant. In-process evaluation removes subprocess
  overhead, but a modern pooled runner has largely removed it too. Any claim of a ~400×
  per-mutant advantage would be measured against a tool that no longer exists.
- **Suite time is the real variable.** Detective's suite runs in 0.3s, the best case for
  a per-mutant runner. The covering-tests reduction (Layer 3) compounds as suite time
  grows, so the gap widens on slow suites and narrows to nothing on fast ones.
- **The claim is knowledge per mutant, not mutants per second.** 1.00 is not a speed
  record; it is the proof that no mutant was spent twice on the same question.

---

## Provably the least work a sound profiler can do

The speedup is not a bag of heuristics that happen to work. Every layer is either **lossless** or **optimal within computational hardness** — so the pipeline is the minimal-work sound mutation profiler, up to an NP-hardness ceiling.

**The three reductions change no verdict.** In-process evaluation runs the *same* AST and the *same* assertion a file-rewriting tool would (Layer 1). Categorical exclusion skips only mutants that *cannot be generated* (Layer 2). Targeted discovery skips only tests that *cannot kill* (Layer 3). None can flip a single kill/survive result; each is a soundness-preserving reduction to the cost floor of exhaustive mutation testing.

**The selection layer spends the remaining budget optimally.** Choosing which `max_per_category` mutants to test is a maximum-coverage problem over behavioral dimensions — and greedy selection solves it provably near-optimally.

Give each mutant $v$ a cover set $\mathrm{cover}(v) \subseteq \mathcal{D}$, the behavioral dimensions it pins. The coverage of a selected set $S$, and the marginal coverage of adding one more mutant, are

$$f(S) \;=\; \Bigl|\bigcup_{v \in S} \mathrm{cover}(v)\Bigr|, \qquad \kappa(v \mid S) \;=\; f\big(S \cup \{v\}\big) - f(S).$$

Wesker picks greedily, $v_{i+1} \in \arg\max_{v}\, \kappa(v \mid S_i)$. Three facts — each **machine-checked in Lean** against `Mathlib`, axiom-clean — make that the right thing to do.

Coverage is **submodular** — [`coverage_submodular`] — for all $S \subseteq T$ and every $v$:

$$f\big(T \cup \{v\}\big) + f(S) \;\le\; f\big(S \cup \{v\}\big) + f(T).$$

Equivalently, marginal coverage is **antitone** — [`marginal_antitone`] — so a dimension already covered is never worth re-covering:

$$S \subseteq T \;\implies\; \kappa(v \mid T) \;\le\; \kappa(v \mid S).$$

And greedy attains $1 - 1/e$ — [`greedy_coverage_bound`] — with optimality gap $g_i$ after $i$ picks and budget $k$, the submodular contraction $g_{i+1} \le \big(1 - \tfrac{1}{k}\big)\, g_i$ gives

$$\mathrm{opt} - g_k \;\ge\; \big(1 - e^{-1}\big)\,\mathrm{opt}.$$

That number is not a convenient bound — it is the **ceiling**. Maximum coverage is NP-hard, and $1 - 1/e \approx 0.632$ is the best ratio *any* polynomial-time algorithm can guarantee unless $\mathrm{P} = \mathrm{NP}$ (Feige, 1998). Greedy attains it.

So Wesker does no work that provably cannot produce a result, and spends what remains on the provably most-informative mutants achievable in polynomial time — minimal-work by construction, with the soundness of an exhaustive run intact. Set `max_per_category=0` and the budget disappears: the classical result comes back unchanged. The selection layer decides only *which* mutants a bounded run tests — never *what a mutant means*.

---

## Bounded runs, in practice

By default Wesker samples: for 20 VALUE targets and `max_per_category=5`, it tests 5 per pass. Three things keep that honest.

**The universe is always computable.** `estimate_universe_size()` counts every possible target by walking the AST — no generation, no execution. Output always reports both numbers, `killed/tested [tested/universe]`: a line reading `82/82 [82/173]` means 82 tested, all 82 killed, out of a 173-mutant universe. You always know how much of the space you covered.

**Multi-pass convergence extends coverage.** Each pass takes the next window of the greedy order — pass 0 the five highest-marginal-coverage targets, pass 1 the next five — so after $N$ passes exactly $N \times$ `max_per_category` unique mutants per category, deepening coverage rather than re-rolling a random subset. Even under the legacy random fallback (`greedy=False`), the chance of missing a real survivor after $K$ passes is bounded:

$$P(\text{miss}) \;=\; \left(\frac{n - k}{n}\right)^{\!K}, \qquad n = \text{targets in category}, \quad k = \texttt{max\_per\_category}.$$

| Targets $n$ | $k{=}5$, 1 pass | $k{=}5$, 3 passes | $k{=}5$, 5 passes |
|-------------|-------------|---------------|---------------|
| 5 | 0% (exhaustive) | 0% | 0% |
| 10 | 50% | 12.5% | 3.1% |
| 20 | 75% | 42% | 24% |
| 50 | 90% | 73% | 59% |

For ≤5 targets per category — the common case in well-decomposed code — a single pass is already exhaustive. Greedy selection (the default) replaces this probabilistic bound with the coverage *guarantee* proved above; the table is the worst case it improves on.

**Category order comes from predictive priors.** Each run writes per-category survival rates to `.wesker/mutation_report.json`; the next run tests historically weak categories first, spending budget where gaps actually live. Priors choose *which category*; greedy coverage chooses *which mutants within it*.

### When to use exhaustive mode

For published libraries, safety-critical code, or a badge that says *every mutant tested*:

```toml
[tool.wesker]
max_per_category = 0       # unlimited — test every mutant
convergence_passes = 1     # one pass suffices when unlimited
```

This is identical to traditional mutation testing — same mutants, same evaluation, same kill rate. Only the execution architecture differs (in-process vs. subprocess, covering tests vs. full suite), which changes the speed and nothing else.

---

## Equivalent mutant detection

Some mutants are *semantically equivalent* — no input can distinguish them from the original. They inflate the denominator and make a score look worse than it is.

When a mutant survives, Wesker compiles both versions, runs them on synthesized boundary inputs (`0, 1, -1, 0.5, boundary ± 1`), and compares outputs. If every input agrees, the mutant is **likely equivalent** — no test *can* kill it. (Detection needs at least one non-exception comparison; if every input raises, the result is inconclusive, not "equivalent.") Equivalent mutants are reported separately and removed from the effective rate:

$$\text{effective kill rate} \;=\; \frac{\text{killed}}{\text{tested} - \text{equivalent}}.$$

## MC/DC verification

For safety-critical functions that must prove every condition independently affects the outcome — [DO-178C Level A](https://en.wikipedia.org/wiki/DO-178C) — Wesker verifies Modified Condition/Decision Coverage by flipping each comparison operator independently against the full test suite.

---

## Installation

```bash
pip install wesker
```

From source:

```bash
git clone https://github.com/rohanvinaik/Wesker.git
cd Wesker
pip install -e .
```

Python 3.10+. No dependencies beyond the standard library and your test framework.

---

## Usage

### CLI

```bash
wesker src/                          # profile a directory
wesker src/scoring.py src/query.py   # profile specific files
wesker src/ --threshold 90           # fail CI if kill rate < 90%
wesker src/ --max-per-category 0 --passes 1   # exhaustive mode
wesker src/ --json                   # JSON output for CI
wesker --mcdc src/scoring.py::compute_score   # MC/DC verification
```

Full option reference:

```
wesker [targets...] [options]

  --threshold N            Exit 1 if kill rate < N%
  --mcdc FILE::FUNC ...    MC/DC verification on specific functions
  --json                   JSON output (for CI parsing)
  --budget MS              Per-file time budget (default: 10000ms)
  --max-per-category N     Mutants per category per pass (default: 5, 0=exhaustive)
  --passes N               Convergence passes (default: 3)
  --exclude FILE ...       Files to skip
  --quiet                  Minimal output
```

### As a library

```python
from Wesker.ci import profile_function

result = profile_function(".", "src/scoring.py", "compute_score")
print(result["kill_matrix"])        # which test killed which mutant
print(result["survivor_records"])   # survivors, with category + location
print(result["is_gateable"])        # True if every mutant was tested
```

Per-function caching (returns instantly on repeat calls until the code changes):

```python
from Wesker.ci import profile_function_cached

result = profile_function_cached(".", "src/scoring.py", "compute_score")
```

Whole file, or whole codebase:

```python
from Wesker.ci import profile_file, profile_codebase

for r in profile_file(".", "src/scoring.py", passes=3):
    print(f"{r['function_key']}: {r['total_killed']}/{r['total_mutants']}")

result = profile_codebase(".", ["src/scoring.py", "src/query.py"])
print(result["kill_pct"], result["per_category"])
```

### Configuration

```toml
# pyproject.toml
[tool.wesker]
source_dir = "src/mypackage"
exclude = ["src/mypackage/server.py"]
max_per_category = 5          # mutants per category per pass (default: 5)
convergence_passes = 3        # convergence passes (default: 3)
mcdc_targets = [["src/mypackage/scoring.py", "compute_score"]]
```

Layout is auto-detected from `[tool.coverage.run]`, `[tool.hatch.build]`, or an `src/*/` convention when `[tool.wesker]` is absent.

### GitHub Action

Two workflows. The first runs on every pull request and is scoped to the diff, so it costs
seconds. The second measures the whole codebase on a schedule and writes the badge. On a public
repo GitHub's standard runners are free, so both cost nothing but wall-clock nobody is waiting on.

**On pull requests** — survivors land as code-scanning alerts, inline on the diff:

```yaml
name: Specification
on: pull_request
permissions:
  contents: read
  security-events: write        # required to upload SARIF
jobs:
  spec:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0        # the diff scope needs the merge base
      - uses: rohanvinaik/Wesker@v0.5.0
        with:
          base-ref: ${{ github.event.pull_request.base.sha }}
          sarif: .wesker/wesker.sarif
      - uses: github/codeql-action/upload-sarif@v3
        if: always() && hashFiles('.wesker/wesker.sarif') != ''
        with:
          sarif_file: .wesker/wesker.sarif
          category: wesker
```

**On a schedule** — the whole codebase, for the badge:

```yaml
name: Specification (full)
on:
  schedule: [{cron: "0 6 * * 1"}]
  workflow_dispatch:
jobs:
  spec:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: rohanvinaik/Wesker@v0.5.0
        id: spec
        with:
          budget: "30000"
      - run: echo "${{ steps.spec.outputs.spec-pct }}% of ${{ steps.spec.outputs.dimensions-total }} dimensions"
```

See [`.github/workflows/`](.github/workflows/) for the versions this repo runs on itself,
including badge generation.

| Input | Default | |
|-------|---------|--|
| `base-ref` | — | scope to files changed since this ref; omit for the whole codebase |
| `targets` | auto | explicit files; otherwise discovered from `[tool.wesker]` or layout |
| `budget` | `15000` | per-file budget, ms |
| `threshold` | — | fail if `spec-pct` is below this |
| `sarif` | `.wesker/wesker.sarif` | where to write the SARIF report |
| `allow-truncation` | `false` | report a budget-limited sample rather than failing |

Outputs: `spec-pct`, `dimensions-total`, `dimensions-pinned`, `dimensions-unspecified`,
`kill-pct`, `total-mutants`, `survivors`, `execution-mode`, `report`, `sarif`.

**Requires pytest, and a suite that passes on unmutated code.** The action would rather fail
loudly than publish a number it cannot stand behind: it refuses to report if the run falls back
to the non-pytest runner, if most of the suite fails before any mutant is introduced (a broken
environment reports `0%` and looks identical to unspecified code), or if the budget truncated
the run (a sample is not a completeness measurement). Each refusal prints the one-line diagnosis
and the fix.

#### Badge

The scheduled workflow writes SVGs to a `badges` branch, so the README stays untouched:

```markdown
![Specification](https://raw.githubusercontent.com/OWNER/REPO/badges/.github/badges/specification.svg)
```

---

## The bigger picture

Specification completeness is the prerequisite for everything you'd want to do to code and *prove* you didn't break it — safe refactoring, algebraic optimization, mechanical transformation. A function whose behavior its tests underdetermine is an ambiguous specification: you cannot safely optimize, cache, parallelize, or refactor what you cannot prove equivalent.

Wesker makes that measurement routine by removing the cost barrier. The theoretical foundation — specification complexity as a lattice from *no tests* to *fully specified*, the Monty Hall architecture, and the link between mutation pressure and algebraic decomposability — is developed in the [mutation testing theory](https://github.com/rohanvinaik/LintGate/blob/main/docs/mutation/mutation-theory.md) document in [LintGate](https://github.com/rohanvinaik/LintGate). Wesker is the standalone engine that makes it operational — and its budget-optimal selection layer is proved: `coverage_submodular`, `marginal_antitone`, and `greedy_coverage_bound` are machine-checked in Lean, so the $(1-1/e)$ guarantee is a theorem, not a claim.

---

Zero dependencies. Fully deterministic. Exhaustive mode when you need certainty; provably-optimal selection when you need speed.

For forty-eight years, mutation testing was something you ran overnight — if you ran it at all. Wesker makes it a line in your CI log, and a proof that the line is honest.

MIT — Rohan Vinaik
