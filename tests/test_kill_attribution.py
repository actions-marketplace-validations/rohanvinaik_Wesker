"""Kill ATTRIBUTION: a test failure counts only when the mutation caused it.

`evaluate_mutant` installs a mutant two independent ways:

  * into the TEST's namespace (`_patch_mutant_into_test` -> ``patched``), and
  * across the MODULE-qualified bindings (`_patch_module_qualified` -> ``module_saved``),
    so a test calling ``mod.func(...)`` hits the mutant too.

When the first fails, the unpatched path INJECTS the mutant as a positional argument — a
contract only Wesker's own inline tests observe. A discovered test with an unfilled fixture
parameter then receives the mutant AS the fixture and fails on garbage; that failure is
about the fixture, not the mutation, and must not be credited (the prism/economics
artifact: 118 of 131 "assertion kills" were this).

The control for that is a re-run against the ORIGINAL — which has to undo the MODULE patch
as well, not merely inject the original. Otherwise both runs execute the mutant, agree
trivially, and every real kill is discarded. ``patched`` is False for EVERY parametrized
case (its wrapper's ``__globals__`` hold no target binding), so getting this wrong silently
zeroes the kill count of any suite using ``@pytest.mark.parametrize`` — while the suite
itself still passes.

Engine-core cannot self-profile, so this is a hand-written unit test by design.
"""

from __future__ import annotations

import ast
import importlib.util
import sys

import pytest

from Wesker.engine import evaluate_mutant, generate_mutants
from Wesker.filter import filter_categories

_SRC = "def analyze(n):\n    return n * 2\n"


@pytest.fixture
def target(tmp_path):
    """A real module on disk, imported under its own name — so ``co_filename`` is a real
    path the module-qualified patch can match, exactly as in a consumer repo."""
    path = tmp_path / "econ_mod.py"
    path.write_text(_SRC)
    spec = importlib.util.spec_from_file_location("econ_mod", str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["econ_mod"] = mod
    spec.loader.exec_module(mod)
    try:
        yield mod, str(path)
    finally:
        sys.modules.pop("econ_mod", None)


def _mutants():
    node = ast.parse(_SRC).body[0]
    return generate_mutants(
        node, filter_categories(node, True), max_per_category=0, pass_index=0
    )


def _kills(tests, mod, path):
    return sum(
        evaluate_mutant(
            m, tests, mod.analyze, qualname="analyze", source_path=path
        ).killed
        for m in _mutants()
    )


def test_unrelated_fixture_test_earns_no_kills(target):
    """The artifact. This test never references the target and needs a fixture, so the
    unpatched path hands it the mutant AS `tmp_state` and it fails on garbage. It fails the
    same way on the original, so it distinguishes nothing and must kill nothing."""
    mod, path = target

    def test_nudge_contains_tool_count(tmp_state):
        assert tmp_state["tool_count"] == 3

    assert _kills([test_nudge_contains_tool_count], mod, path) == 0


def test_module_calling_test_still_earns_its_kills(target):
    """The regression. `analyze` is NOT in this callable's globals (only `econ_mod` is), so
    `patched` is False — the same shape a parametrized case has, since Wesker binds it
    through a wrapper. It reaches the mutant via the MODULE patch, so its failure IS caused
    by the mutation and must be credited. Comparing against the original without undoing
    the module patch would run the mutant twice and discard this."""
    mod, path = target

    def case():
        assert mod.analyze(5) == 10

    assert _kills([case], mod, path) == len(_mutants())
