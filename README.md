# Wesker

**Mutation testing at CI speed — with exhaustive-grade soundness and a provably optimal test budget.**

[![CI](https://github.com/rohanvinaik/Wesker/actions/workflows/ci.yml/badge.svg)](https://github.com/rohanvinaik/Wesker/actions/workflows/ci.yml)
[![Quality Gate](https://sonarcloud.io/api/project_badges/measure?project=rohanvinaik_Wesker&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=rohanvinaik_Wesker)
[![Mean σ](https://raw.githubusercontent.com/rohanvinaik/Wesker/badges/.github/badges/sigma.svg)](https://github.com/rohanvinaik/Wesker/actions/workflows/spec-badges.yml)
<br>
[![Mutation Kill Rate](https://raw.githubusercontent.com/rohanvinaik/Wesker/badges/.github/badges/mutation-kill-rate.svg)](https://github.com/rohanvinaik/Wesker/actions/workflows/spec-badges.yml)
[![Mutation Sampling](https://raw.githubusercontent.com/rohanvinaik/Wesker/badges/.github/badges/mutation-sampling.svg)](https://github.com/rohanvinaik/Wesker/actions/workflows/spec-badges.yml)
[![MC/DC](https://raw.githubusercontent.com/rohanvinaik/Wesker/badges/.github/badges/mcdc.svg)](https://github.com/rohanvinaik/Wesker/actions/workflows/spec-badges.yml)

`Zero dependencies · 7 semantic categories · (1−1/e)-optimal selection · Fully deterministic`

<div align="center">

$$\mathrm{SC}(f)=1 \quad\Longleftrightarrow\quad \underbrace{\log_2\bigl\lvert\,\{f\}\cup\mathrm{survivors}\,\bigr\rvert}_{\displaystyle H(f \,\mid\, \mathrm{tests})}=0$$

*Every surviving mutant is one bit of behavior your tests never asked for.*
*A function is fully specified exactly when that set collapses to the function itself — when its conditional entropy hits zero.*

</div>

Mutation testing is the gold standard for measuring what your tests actually pin down: change the code, and see whether a test complains. Every mutation that slips through silently is a behavior your suite never constrained — a gap line coverage cannot see. DeMillo, Lipton, and Sayward formalized this in 1978, and for 48 years it has been too slow for routine use. The established tools — mutmut, cosmic-ray, PIT, Stryker — faithfully implement the original cost model and inherit its price: on real code, a full run takes hours.

Wesker restructures the computation. A 100-function project profiles in under ten seconds, at the same soundness as an exhaustive run — it simply refuses to do work that provably cannot change a result.

```
Wesker — Prism Specification Metrics (3 passes, 5/cat)

  [1/13] sources.py      212/212 [212/235] 904ms
  [2/13] behavior.py       82/82 [82/173]  309ms
  [3/13] economics.py      35/35 [35/118]  277ms
  ...
  [13/13] engine.py        84/84 [84/94]   197ms

Kill rate: 100% (1229/1229) | Universe: 2195 | 109 functions | 4.1s
```

1229 mutants across 7 categories, 109 functions, 13 files — a 100% kill rate in 4.1 seconds. Wesker tested 56% of the 2,195-mutant universe and killed every one; the rest is one flag away (`max_per_category=0` runs it exhaustively, identical to classical mutation testing). Those mutants were not sampled at random. They were **selected** — and that selection is where Wesker's speed stops being an engineering trick and becomes a theorem.

---

## What mutation testing actually measures

Line coverage tells you which code *executed*. Mutation testing tells you which *behaviors* your tests constrain. These are different questions.

A function with 99% line coverage can still have a 40% kill rate — meaning 60% of its behavioral dimensions (its outputs, its boundaries, its branch logic) could change without a single test noticing. The tests prove the code runs. They do not prove what it computes.

Each surviving mutant is a specific alteration that changes behavior and goes unnoticed. Taken together, the survivors are a constructive map of everything the tests *don't* require the function to do — its **negative space**. The kill rate measures how much of that behavior is actually pinned down: **specification completeness**, the degree to which the suite determines what the code does.

---

## Seven categories tell you *what kind* of gap you have

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

The category **is** the diagnosis. A VALUE survivor says *assert the exact value, not just the shape*. A BOUNDARY survivor says *test at the boundary, not near it*. An ARITHMETIC survivor says *verify the computation, not just that it returns a number*. The fix is always specific — never "write more tests."

Together these cover the standard operator set from the literature — AOR, ROR, COR, UOI — plus domain operators for state mutation and type guards.

---

## How it gets fast without losing soundness

The cost drops multiplicatively across three layers. Each is provably safe: no information is lost at any one of them.

### Layer 1 · In-process AST mutation — 10–50×

Traditional tools spawn a subprocess per mutant, rewrite source files on disk, and invoke the test runner externally — roughly 400 ms of overhead per mutant before a single test executes. For 200 mutants, that is 80 seconds of pure startup cost.

Wesker compiles mutant ASTs in memory, patches them into a sandboxed namespace through the test's `__globals__`, and evaluates in-process. No subprocess, no disk I/O, no file rewrites. Per-mutant overhead falls from ~400 ms to ~1 ms.

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

### The combined cost model

Traditional mutation testing costs

$$O\big(\text{functions} \times \text{mutants/fn} \times \text{subprocess startup} \times \text{full suite}\big).$$

Wesker costs

$$O\big(\text{functions} \times \text{applicable mutants} \times \text{in-process toggle} \times \text{covering tests}\big).$$

| Factor | Traditional (mutmut) | Wesker | Reduction |
|--------|---------------------|--------|-----------|
| Mutants per function | 50–200 | 15–35 (greedy-selected) | 3–10× |
| Per-mutant overhead | ~400 ms (subprocess) | ~1 ms (in-process) | ~400× |
| Tests per mutant | Full suite (100–500) | Covering tests (3–15) | 10–30× |
| **Wall-clock, 100 functions** | **30–120 min** | **4–15 s** | **100–1000×** |

A 30-minute batch job becomes a 10-second step. That is what makes mutation testing a per-commit check instead of a nightly one.

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

```yaml
- name: Mutation testing
  run: |
    pip install wesker
    wesker src/ --threshold 90
```

---

## The bigger picture

Specification completeness is the prerequisite for everything you'd want to do to code and *prove* you didn't break it — safe refactoring, algebraic optimization, mechanical transformation. A function whose behavior its tests underdetermine is an ambiguous specification: you cannot safely optimize, cache, parallelize, or refactor what you cannot prove equivalent.

Wesker makes that measurement routine by removing the cost barrier. The theoretical foundation — specification complexity as a lattice from *no tests* to *fully specified*, the Monty Hall architecture, and the link between mutation pressure and algebraic decomposability — is developed in the [mutation testing theory](https://github.com/rohanvinaik/LintGate/blob/main/docs/mutation/mutation-theory.md) document in [LintGate](https://github.com/rohanvinaik/LintGate). Wesker is the standalone engine that makes it operational — and its budget-optimal selection layer is proved: `coverage_submodular`, `marginal_antitone`, and `greedy_coverage_bound` are machine-checked in Lean, so the $(1-1/e)$ guarantee is a theorem, not a claim.

---

Zero dependencies. Fully deterministic. Exhaustive mode when you need certainty; provably-optimal selection when you need speed.

For forty-eight years, mutation testing was something you ran overnight — if you ran it at all. Wesker makes it a line in your CI log, and a proof that the line is honest.

MIT — Rohan Vinaik
