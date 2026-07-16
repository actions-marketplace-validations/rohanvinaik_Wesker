"""Wesker — in-process AST mutation testing for Python.

Zero dependencies beyond the test framework. Categorical mutant stratification
(VALUE, BOUNDARY, SWAP, STATE, TYPE, ARITHMETIC, LOGICAL) with Monty Hall
filtering, 3-layer test discovery, equivalent mutant detection, and MC/DC
verification.
"""

# Keep in lockstep with pyproject's `version` — this is restated, so it drifts silently:
# it read 0.1.0 for the whole of the 0.3.0 release, and would have shipped 0.4.0 still
# claiming 0.1.0. Bump both, or neither.
__version__ = "0.6.2"

from .engine import (
    BoundaryInput,
    CategoryResult,
    Mutant,
    MutantResult,
    MutationCategory,
    ProfilingResult,
    SamplingResult,
    check_equivalent,
    estimate_universe_size,
    evaluate_mutant,
    extract_boundary_inputs,
    generate_mutants,
    run_function_converged,
    run_function_profiling,
    run_function_sampling,
)
from .filter import CategoryPrior, filter_categories, prioritize_categories

__all__ = [
    # Enums
    "MutationCategory",
    # Result types
    "BoundaryInput",
    "CategoryPrior",
    "CategoryResult",
    "Mutant",
    "MutantResult",
    "ProfilingResult",
    "SamplingResult",
    # Engine functions
    "check_equivalent",
    "estimate_universe_size",
    "evaluate_mutant",
    "extract_boundary_inputs",
    "generate_mutants",
    "run_function_converged",
    "run_function_profiling",
    "run_function_sampling",
    # Filter functions
    "filter_categories",
    "prioritize_categories",
]
