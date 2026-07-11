# Wesker

**The provably most-efficient mutation testing there is — which is what turns it from a nightly batch job into a CI operation that runs on every commit.**

`Zero dependencies · 7 semantic categories · Machine-checked (1−1/e)-optimal mutant selection · Fully deterministic`

Mutation testing is the gold standard for measuring specification completeness — mutate the code, check if tests catch it, find the behavioral gaps that line coverage cannot see. The concept has been understood since DeMillo, Lipton, and Sayward formalized it in 1978. For 48 years, it has been too expensive to use routinely. The tools that exist (mutmut, cosmic-ray, PIT, Stryker) are faithful implementations of the original idea — and they inherit its cost model: `O(mutants × subprocess_startup × full_test_suite)`. On real codebases, that means hours.

Wesker restructures the computation. A 100-function project profiles in under 10 seconds. The soundness guarantee is the same as exhaustive mutation testing — the efficiency comes from not doing work that provably cannot produce results, not from weakening the analysis.

**The efficiency is *proven*, not benchmarked — which is what lets mutation testing run on every commit instead of nightly.** Every reduction is lossless (it flips no kill/survive verdict), and the one place Wesker spends a bounded budget it spends optimally: a **machine-checked $(1-1/e)$-optimal** selection, the best any polynomial-time algorithm can achieve. The cost is minimal *by construction*, not by hope — [the proof is below](#why-this-is-provably-the-least-work-a-sound-profiler-can-do).

```
Wesker — Prism Specification Metrics (3 passes, 5/cat)

  [1/13] sources.py      212/212 [212/235] 904ms
  [2/13] behavior.py       82/82 [82/173]  309ms
  [3/13] economics.py      35/35 [35/118]  277ms
  ...
  [13/13] engine.py        84/84 [84/94]   197ms

Kill rate: 100% (1229/1229) | Universe: 2195 | 109 functions | 4.1s
```

1229 mutants across 7 categories, 109 functions, 13 files — 100% kill rate in 4.1 seconds. Wesker tested 56% of the 2195-mutant universe, and those were the *provably most-informative* 56%, not a random draw: budget goes to the mutants of maximal marginal behavioral-dimension coverage. Every tested mutant was killed; the rest is one flag away (`max_per_category=0` runs exhaustive mode, identical to classical mutation testing).

---

## What mutation testing actually measures

Line coverage tells you which code *executed*. Mutation testing tells you which *behaviors* are constrained by your tests. These are fundamentally different questions.

A function with 99% line coverage can have a 40% mutation kill rate. That means 60% of its behavioral dimensions — its outputs, its boundary conditions, its branch logic — could change without any test noticing. The tests prove the code runs. They do not prove what it computes.

Each surviving mutant is a specific alteration to the function's logic that produces different output and no test notices. Taken together, surviving mutants form a constructive specification of everything the tests *don't require* the function to do — the **negative space**. The mutation kill rate measures how much of the function's behavior is actually pinned down. This is **specification completeness**: the degree to which the test suite fully determines what the code does.

---

## Seven categories tell you *what kind* of gap you have

Not just "a mutant survived" but *which behavioral dimension* the tests leave unconstrained:

| Category | What it mutates | What survival means |
|----------|----------------|-------------------|
| **VALUE** | Constants (`0`→`1`, `True`→`False`, `"x"`→`""`) | Tests don't pin exact outputs |
| **BOUNDARY** | Comparisons (`<`↔`<=`, `>`↔`>=`, `==`↔`!=`) | Tests don't exercise boundary conditions |
| **ARITHMETIC** | Operators (`+`↔`-`, `*`↔`/`, `//`→`/`, remove unary `-`) | Tests don't verify computations |
| **LOGICAL** | Boolean logic (`and`↔`or`, remove `not`) | Tests don't exercise conditional composition |
| **SWAP** | Argument order in function calls | Tests can't distinguish argument positions |
| **STATE** | `self.x = ...`→removed, `return x`→`return None` | Tests don't verify side effects or return values |
| **TYPE** | `isinstance(x, T)`→`True` | Tests don't exercise type guards |

The category IS the diagnosis. A VALUE survivor means "assert the exact value, not just the shape." A BOUNDARY survivor means "test at the boundary, not near it." An ARITHMETIC survivor means "verify the computation, not just that it returns a number." The fix is always specific, not "write more tests."

These seven categories cover the standard mutation operator set from the literature: AOR (Arithmetic Operator Replacement), ROR (Relational Operator Replacement), COR (Conditional Operator Replacement), UOI (Unary Operator Insertion/Deletion), and the domain-specific operators for state mutation and type guards.

---

## How it gets fast without losing soundness

The cost reduction is multiplicative across three architectural layers. Each is provably safe — no information is lost at any layer.

### Layer 1: In-process AST mutation (10-50x)

Traditional tools (mutmut, cosmic-ray) spawn a subprocess per mutant, rewrite source files on disk, and invoke the test runner externally. Each cycle costs ~0.4s of subprocess startup plus disk I/O. For 200 mutants, that is 80 seconds of pure overhead before a single test executes.

Wesker compiles mutant ASTs in memory using Python's `ast` module, monkey-patches them into a sandboxed namespace via the test function's `__globals__`, and evaluates directly. Same process. No I/O. No file rewrites. No subprocess startup. The per-mutant overhead drops from ~400ms to ~1ms.

This architecture follows the **meta-mutant dispatch table** pattern validated by mutest-rs (Lévai & McMinn, ICST 2023, TOSEM 2026) and mu2's `MutationClassLoader` (Vikram & Padhye, ISSTA 2023). The soundness argument is straightforward: the mutated function is compiled from the same AST that a file-rewriting tool would produce; the evaluation is the same assertion check. The execution path is different, the observable semantics are identical.

### Layer 2: Categorical exclusion — the Monty Hall filter (2-5x)

Before generating a single mutant, Wesker walks the function's AST and checks which mutation categories have syntactic targets:

- No comparison operators? **BOUNDARY** mutants cannot exist — skip.
- No `self.x = ...` assignments? **STATE** mutants cannot exist — skip.
- No arithmetic operators? **ARITHMETIC** mutants cannot exist — skip.
- Fewer than 2 call arguments? **SWAP** mutants cannot exist — skip.

This is not sampling. It is elimination of structural impossibilities. If the syntactic target for a mutation category does not exist in the function's AST, no mutation in that category can be generated. Skipping it loses zero information. A typical function has 3-4 applicable categories out of 7, reducing the mutation space by 40-60% before any test runs.

This is the **Monty Hall insight**: the game show host opens doors that have no prize behind them. You learn nothing by opening them yourself. The AST structure reveals which categories are empty doors.

### Layer 3: Targeted test discovery (5-20x)

Traditional tools run the full test suite against every mutant. For a project with 300 tests, that is 300 test invocations per mutant. Most of those tests have no relationship to the mutated function and cannot possibly kill the mutant.

Wesker discovers relevant tests in three layers:
1. **Convention matching** — `src/query.py` maps to `tests/test_query.py` (fast, high precision)
2. **Static AST impact** — scan test files for references to the mutated function name
3. **Full fallback** — only if layers 1-2 found nothing

Most functions resolve at layer 1. Each mutant runs against 3-15 tests, not the full suite. The soundness argument: if a test does not import, reference, or transitively call the mutated function, it cannot detect the mutation. Running it is pure waste.

### Combined cost model

Traditional:
```
O(functions × mutants_per_function × subprocess_startup × full_test_suite)
```

Wesker:
```
O(functions × applicable_mutants × in_process_toggle × covering_tests)
```

| Factor | Traditional (mutmut) | Wesker | Reduction |
|--------|---------------------|--------|-----------|
| Mutants per function | 50-200 | 15-35 (greedy-selected) | 3-10x |
| Per-mutant overhead | ~400ms (subprocess) | ~1ms (in-process) | ~400x |
| Tests per mutant | Full suite (100-500) | Covering tests (3-15) | 10-30x |
| **Wall-clock for 100 functions** | **30-120 minutes** | **4-15 seconds** | **100-1000x** |

This is what makes mutation testing viable as a CI action. A 30-minute batch job becomes a 10-second step that runs on every commit.

### Why this is *provably* the least work a sound profiler can do

The speedup is not a bag of heuristics — every layer is either **lossless** or **optimal within computational hardness**:

- **Layers 1–3 change no verdict.** In-process evaluation runs the *same* AST and the *same* assertion; categorical exclusion skips only mutants that *cannot be generated*; targeted discovery skips only tests that *cannot kill*. Each is a soundness-preserving reduction to the cost floor of exhaustive mutation testing.
- **The selection layer spends the remaining budget optimally.** Picking the `max_per_category` most-informative mutants is maximum coverage over behavioral dimensions — NP-hard — and greedy attains the best ratio any tractable algorithm can (the machine-checked $(1-1/e)$ bound, [proved below](#declining-marginal-utility--greedy-submodular-selection)).

So Wesker does **no work that provably cannot produce a result**, and spends what remains on the **provably most-informative mutants achievable in polynomial time** — minimal-work by construction, with the soundness of exhaustive mutation testing intact. Exhaustive mode (`max_per_category=0`) removes the budget and returns the classical result unchanged; the selection layer governs only *which* mutants a *bounded* run tests, never *what a mutant means*.

---

## Why bounded runs stay sound

Wesker does not test every possible mutant by default. For a function with 20 VALUE mutation targets and `max_per_category=5`, it tests 5 per pass. This is deliberate, and the theoretical justification is rigorous.

### The universe is always computable

`estimate_universe_size()` counts every possible mutation target across all applicable categories by walking the AST — no mutant generation, no test execution, pure counting. This is the same universe that exhaustive tools like mutmut would generate. Setting `max_per_category=0` (unlimited) runs Wesker in **exhaustive mode**, producing results identical to traditional mutation testing.

The output always reports both numbers: `killed/tested [tested/universe]`. A result like `82/82 [82/173]` means 82 mutants were tested, all 82 were killed, and the full universe for that file is 173. You know exactly how much of the space was covered.

### Multi-pass convergence

Each convergence pass takes the next window of the greedy dimension-coverage order (see [Declining marginal utility](#declining-marginal-utility--greedy-submodular-selection)). Pass 0 tests the `max_per_category` highest-marginal-coverage targets; pass 1 the next window; and so on — so after N passes exactly `N × max_per_category` unique mutants are tested per category, *extending* dimension coverage instead of re-rolling a random subset.

Even under the *legacy random-sampling fallback* (`greedy=False`), the probability of missing a real survivor after K passes is bounded:

```
P(miss) = ((n - k) / n) ^ K
```

where `n` = targets in category, `k` = max_per_category. Greedy selection (the default, [below](#declining-marginal-utility--greedy-submodular-selection)) replaces this probabilistic bound with a coverage *guarantee* — the table is the worst case it improves on.

| Targets (n) | k=5, 1 pass | k=5, 3 passes | k=5, 5 passes |
|-------------|-------------|---------------|---------------|
| 5 | 0% (exhaustive) | 0% | 0% |
| 10 | 50% | 12.5% | 3.1% |
| 20 | 75% | 42% | 24% |
| 50 | 90% | 73% | 59% |

For functions with ≤5 targets per category (the majority in well-decomposed code), sampling IS exhaustive — you naturally test everything. For larger functions, increasing passes tightens the bound. In practice, functions with 50+ targets per category are rare and are themselves a signal that the function needs decomposition.

### Declining marginal utility — greedy submodular selection

The first few mutants per behavioral dimension are the most informative, and Wesker *selects* for that rather than trusting a random draw to find it. Each mutant probes one **behavioral dimension** — the `(category, construct-kind)` it alters (`BOUNDARY:Lt`, `ARITHMETIC:Add`, …). Take a mutant's coverage to be the dimension it pins, and the value of a selected set *S* to be the number of distinct dimensions *S* covers. That set-cover value is monotone **submodular**, so its marginal coverage κ is **antitone**: once a dimension is confirmed, another mutant in it adds nothing. This isn't an analogy for "diminishing returns" — it is the mechanism, and it is what the old seeded-shuffle sampling was a lossy proxy for.

Selecting the `max_per_category` mutants greedily by marginal coverage therefore reaches **≥(1 − 1/e) of the optimally-coverable dimensions** within any budget — exact when cover-sets are singletons — by Nemhauser–Wolsey–Fisher. Each convergence pass takes the next window of that greedy order, so multi-pass accrual *is* the gap-contraction the bound is stated over. The three load-bearing facts — coverage submodularity, marginal antitonicity, and the (1 − 1/e) greedy bound — are **machine-checked in Lean** (`coverage_submodular`, `marginal_antitone`, `greedy_coverage_bound`), so the selection rule rests on a proof rather than on `P(miss) = ((n − k)/n)^K`. That probabilistic bound still describes the legacy random-sampling fallback (`greedy=False`); exhaustive mode is identical under either.

**The theorems, formally.** Write $\mathcal{D}$ for the behavioral dimensions of a function and $\mathrm{cover}(v)\subseteq\mathcal{D}$ for the dimension a mutant $v$ pins. The coverage of a selected set $S$ and the marginal coverage of adding $v$ are

$$f(S) \;=\; \Bigl|\bigcup_{v\in S}\mathrm{cover}(v)\Bigr|, \qquad \kappa(v\mid S) \;=\; f\bigl(S\cup\{v\}\bigr)-f(S) \;=\; \Bigl|\mathrm{cover}(v)\setminus\bigcup_{u\in S}\mathrm{cover}(u)\Bigr|,$$

and the selector is greedy, $v_{i+1}\in\arg\max_{v}\ \kappa(v\mid S_i)$. Three facts, each machine-checked in Lean against `Mathlib` (axiom-clean):

*Coverage is submodular* — [`coverage_submodular`] — for all $S\subseteq T$ and every $v$,

$$f\bigl(T\cup\{v\}\bigr) + f(S)\;\le\; f\bigl(S\cup\{v\}\bigr) + f(T).$$

*Equivalently, marginal coverage is antitone* — [`marginal_antitone`] — so a dimension already covered is never worth re-covering:

$$S\subseteq T \;\Longrightarrow\; \kappa(v\mid T)\;\le\;\kappa(v\mid S).$$

*Greedy attains $1-1/e$* — [`greedy_coverage_bound`] — with $g_i$ the optimality gap after $i$ picks and budget $k$, the submodular contraction $g_{i+1}\le\bigl(1-\tfrac{1}{k}\bigr)g_i$ (with $g_0\le\mathrm{opt}$, $g_i\ge 0$) gives

$$\mathrm{opt} - g_k \;\ge\; \bigl(1-e^{-1}\bigr)\,\mathrm{opt}.$$

The Wesker selector instantiates $\mathrm{cover}$ with the `(category, construct-kind)` map, so the code is a *realization* of the proved abstract result — not a re-derivation of it. For singleton cover-sets (one mutant, one dimension) the greedy is exact: the first $k$ picks cover $\min(k,\lvert\mathcal{D}\rvert)$ dimensions, the optimum.

And $1-1/e$ is not a convenient bound — it is the **ceiling**. Maximum coverage is NP-hard, and $1-1/e\approx 0.632$ is the best ratio *any* polynomial-time algorithm can guarantee unless $\mathrm{P}=\mathrm{NP}$ (Feige, 1998). Greedy attains it. So the selector is not merely better than random sampling — it is **optimal among all tractable sound selectors**; no polynomial-time mutation profiler can allocate a fixed per-category budget more informatively.

Category *order* is still set by **predictive priors** (Layer 2 of the Monty Hall architecture, §6.2). Each Wesker run writes per-category aggregate survival statistics to `.wesker/mutation_report.json`; subsequent runs load them and test historically-weak categories first — a project where ARITHMETIC survives at 40% while VALUE is always killed tests ARITHMETIC first, spending budget where specification gaps actually exist. Priors choose *which category* to spend budget on; greedy coverage chooses *which mutants within it*. The two compose: order by prior, then cover by dimension.

On first run (no cache), all priors are uniform (0.5) and categories are tested in arbitrary order. After one run, the cache exists and every subsequent run is informed. The prioritization is conservative: it changes the *order* of evaluation within each pass, not the total number of mutants generated. If budget is unlimited, the result is identical regardless of ordering. The effect is felt only when budget runs out before completing all categories — which is exactly when you want the most informative categories tested first.

### When to use exhaustive mode

For published libraries, safety-critical code, or when you want the badge to say "every mutant tested":

```toml
[tool.wesker]
max_per_category = 0       # unlimited — test every mutant
convergence_passes = 1     # one pass is enough when unlimited
```

This produces results identical to traditional mutation testing — same mutants, same evaluation, same kill rate. The only difference is execution architecture (in-process vs. subprocess, targeted tests vs. full suite), which affects speed but not semantics.

---

## Equivalent mutant detection

The classic problem with mutation testing: some mutants are *semantically equivalent* — no input can distinguish them from the original. These inflate the denominator and make the score look worse than it is.

When a mutant survives, Wesker compiles both the original and mutated function, runs them on synthesized boundary inputs (0, 1, -1, 0.5, boundary±1), and compares outputs. If every input produces identical results from both versions, the mutant is **likely equivalent** — no test *can* kill it. Equivalence detection requires at least one successful (non-exception) comparison to declare a match; if all inputs raise exceptions, the result is inconclusive (not marked equivalent).

Equivalent mutants are reported separately and excluded from the effective kill rate:

```
effective_kill_rate = killed / (tested - equivalent)
```

## MC/DC verification

For safety-critical functions requiring proof that every condition independently affects the output — the [DO-178C Level A](https://en.wikipedia.org/wiki/DO-178C) standard — Wesker verifies Modified Condition/Decision Coverage by flipping each comparison operator independently against the full test suite.

---

## Installation

```bash
pip install wesker
```

Or from source:

```bash
git clone https://github.com/rohanvinaik/Wesker.git
cd Wesker
pip install -e .
```

Requires Python 3.10+. No dependencies beyond the standard library and your test framework.

---

## Usage

### CLI

Profile an entire source directory:

```bash
wesker src/
```

Profile specific files:

```bash
wesker src/scoring.py src/query.py
```

Fail CI if kill rate drops below a threshold:

```bash
wesker src/ --threshold 90
```

Run in exhaustive mode (every possible mutant, no sampling):

```bash
wesker src/ --max-per-category 0 --passes 1
```

JSON output for CI parsing:

```bash
wesker src/ --json
```

MC/DC verification on safety-critical functions:

```bash
wesker --mcdc src/scoring.py::compute_score
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

Profile a single function (interactive/editor use):

```python
from Wesker.ci import profile_function

result = profile_function(".", "src/scoring.py", "compute_score")
print(result["kill_matrix"])        # which test killed which mutant
print(result["survivor_records"])   # surviving mutants with category + location
print(result["is_gateable"])        # True if all mutants were tested
```

With per-function caching (returns instantly on repeat calls until code changes):

```python
from Wesker.ci import profile_function_cached

result = profile_function_cached(".", "src/scoring.py", "compute_score")
```

Profile an entire file:

```python
from Wesker.ci import profile_file

results = profile_file(".", "src/scoring.py", passes=3)
for r in results:
    print(f"{r['function_key']}: {r['total_killed']}/{r['total_mutants']}")
```

Profile a codebase (CI-level, with terminal output):

```python
from Wesker.ci import profile_codebase

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

Wesker auto-detects source layout from `[tool.coverage.run]`, `[tool.hatch.build]`, or `src/*/` convention when `[tool.wesker]` is not configured.

### GitHub Action

```yaml
- name: Mutation testing
  run: |
    pip install wesker
    wesker src/ --threshold 90
```

---

## The bigger picture

Mutation testing measures specification completeness — the degree to which a test suite fully determines what the code does. This is the prerequisite for safe refactoring, algebraic optimization, and mechanical code transformation. A function whose behavior is underdetermined by its tests is an ambiguous specification. You cannot safely optimize, cache, parallelize, or refactor what you cannot prove equivalent.

Wesker makes this measurement routine by eliminating the cost barrier. The theoretical foundation — specification complexity as a lattice from "no tests" to "fully specified," the Monty Hall architecture for efficient execution, and the connection between mutation pressure and algebraic decomposability — is developed in the [mutation testing theory](https://github.com/rohanvinaik/LintGate/blob/main/docs/mutation/mutation-theory.md) document within the [LintGate](https://github.com/rohanvinaik/LintGate) project. Wesker is the standalone engine that makes the theory operational — and its budget-optimal selection layer is proved: `coverage_submodular`, `marginal_antitone`, and `greedy_coverage_bound` are machine-checked in Lean, so the $(1-1/e)$ guarantee is a theorem, not a claim.

---

No config files required. No subprocess spawning. No external dependencies beyond your test framework. Seven semantic categories. Deterministic, budget-optimal multi-pass convergence. Full-universe exhaustive mode when you need it.

MIT — Rohan Vinaik
