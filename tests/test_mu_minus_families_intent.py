"""μ⁻ — the rest of Def. 11.8's output perturbation family (#44; Detective #116–#123).

Intent tests authored from docs/theory/NEGATIVE_SPECIFICATION.md §11, not from the code.

THE DEFECT. A two-sign run generated nine of Def. 11.8's 38 operators (none, const, id, neg, abs, NaN,
empty, perm, yield). A negative intent test could name any of the other 29 and run, but no μ⁻ mutant
cross-checked that the suite rules out the output it names, so a two-sign ✓ COMPLETE said nothing about
it. The founder's ruling (2026-10-06): allow all of them.

WHAT MUST HOLD for each new operator, whatever the implementation:

* Prop. 11.11, soundness by restriction. A Fork-2 operator is emitted only where EVERY observed return
  type is applicable, and there it NEVER RAISES. A perturbation that raised would be scored as a crash
  kill: adequacy credited for a fault the suite never saw.
* The return expression is evaluated exactly once. Evaluating it twice repeats its side effects, which
  perturbs more than the output.
* Determinism. The same mutant must behave the same in the run and in converge's isolated verification
  (a separate process with its own PYTHONHASHSEED), or the certificate's reproducibility check refuses.
* count == generation (the issue-#9 invariant) under every observed type.
* The nine operators already built keep their ids and diffs: those are what `flag` keys on.
"""

from __future__ import annotations

import ast
import datetime as dt
import importlib.util
import json
import math
import os
import subprocess
import sys
import textwrap
from decimal import Decimal
from fractions import Fraction

import pytest

from Wesker.engine import (
    _OUTPUT_TYPE_CONDITIONAL,
    MutationCategory,
    _OutputMutator,
    estimate_universe_size,
    evaluate_mutant,
    generate_mutants,
)

_EDGE = {
    "int": [0, 1, -1, 10**5000, -(10**5000)],
    "float": [0.0, -0.0, 1.5, -2.5, math.nan, math.inf, -math.inf, 1e308, 5e-324],
    "complex": [0j, 1 + 2j, complex(math.nan, math.inf)],
    "Decimal": [Decimal("1.5"), Decimal("NaN"), Decimal("Infinity"), Decimal("-0")],
    "Fraction": [Fraction(1, 3), Fraction(0)],
    "bool": [True, False],
    "str": ["", "a", "Hello World", "\ud800", "ß", "a\u0301"],
    "bytes": [b"", b"abc", b"\xff\x00"],
    "list": [[], [1], [1, 2, 3], [[1], {"a": 1}], [None]],
    "tuple": [(), (1,), (1, 2, 3)],
    "set": [set(), {1}, {"a", "b", "c"}, {(1, 2), (3,)}, {1, "a"}],
    "frozenset": [frozenset(), frozenset({"x", "y"})],
    "dict": [{}, {"a": 1}, {"a": 1, "b": [2]}, {1: None}],
    "date": [dt.date.min, dt.date.max, dt.date(2020, 1, 1)],
    "datetime": [
        # DTZ901: the NAIVE extremes are the edge values; an aware pair follows
        dt.datetime.min,  # noqa: DTZ901
        # DTZ901: as above
        dt.datetime.max,  # noqa: DTZ901
        dt.datetime(2020, 1, 1, tzinfo=dt.UTC),
        dt.datetime.max.replace(tzinfo=dt.timezone(dt.timedelta(hours=-5))),
    ],
    "timedelta": [dt.timedelta.min, dt.timedelta.max, dt.timedelta(0)],
}

_NEW_FORM_A = {
    "return_zero_of",
    "return_type",
    "return_not",
    "return_true",
    "return_false",
    "return_plus_one",
    "return_minus_one",
    "return_next_up",
    "return_next_down",
    "return_scale",
    "return_round",
    "return_inf",
    "return_truncate",
    "return_swapcase",
    "return_pad",
    "return_reverse",
    "return_drop",
    "return_duplicate",
    "return_singleton",
    "return_ctype",
    "return_field_default",
    "return_sortbreak",
    "return_adjacent",
}


def _perturbed_fn(mode: str, src: str = "def f(v):\n    return v\n"):
    """Compile the mode's rewrite of ``src``'s first return, standalone."""
    node = ast.parse(src).body[0]
    mutator = _OutputMutator(0, mode)
    out = mutator.visit(node)
    ast.fix_missing_locations(out)
    assert mutator.applied, mode
    ns: dict = {}
    # S102: compiling the perturbed function under test is the point
    exec(compile(ast.Module(body=[out], type_ignores=[]), "<mu>", "exec"), ns)  # noqa: S102
    return ns[node.name]


def _sub_mode(m) -> str:
    return m.dimension.split(":")[1] if m.dimension else ""


def _cases():
    for mode, _desc, types in _OUTPUT_TYPE_CONDITIONAL:
        if mode in _NEW_FORM_A:
            for tname in sorted(types):
                yield pytest.param(mode, tname, id=f"{mode}-{tname}")


def test_every_new_operator_is_a_type_conditional_mode():
    # The table is the single source both counting and generation read; the 23 Form A operators
    # Def. 11.8 adds must all be in it, each with a non-empty applicable set.
    table = {mode: types for mode, _desc, types in _OUTPUT_TYPE_CONDITIONAL}
    assert _NEW_FORM_A <= set(table)
    assert all(table[m] for m in _NEW_FORM_A)


@pytest.mark.parametrize(("mode", "tname"), list(_cases()))
def test_never_raises_on_an_edge_value_of_an_applicable_type(mode, tname):
    # Prop. 11.11. NaN, infinities, the extreme dates, a lone surrogate, a 5000-digit int, the empty
    # containers: a raise here would be a crash kill the suite never earned.
    fn = _perturbed_fn(mode)
    for value in _EDGE[tname]:
        fn(value)


@pytest.mark.parametrize(("mode", "tname"), list(_cases()))
def test_changes_some_value_of_every_applicable_type(mode, tname):
    # An operator that never changes any value of a type it claims is a built-in survivor on that
    # type: it fences nothing and still costs a mutant. (true/false leave one of the two bools.)
    fn = _perturbed_fn(mode)

    def same(a, b):
        if type(a) is not type(b):
            return False
        if isinstance(a, float) and math.isnan(a):
            return math.isnan(b)
        if isinstance(a, int):
            return a == b
        return a == b and repr(a) == repr(b)

    assert any(not same(fn(v), v) for v in _EDGE[tname]), (mode, tname)


def test_the_return_expression_is_evaluated_once_under_every_template():
    # A template that names the value twice binds it once. `calls` counts evaluations of the
    # original return expression; any template evaluating it twice would double the side effect.
    src = textwrap.dedent(
        """
        def f(calls, v):
            return calls.append(1) or v
        """
    )
    samples = {
        "int": 3,
        "float": 2.5,
        "str": "ab",
        "bytes": b"ab",
        "bool": True,
        "list": [1, 2, 3],
        "tuple": (1, 2, 3),
        "set": {1, 2},
        "frozenset": frozenset({1, 2}),
        "dict": {"a": 1, "b": 2},
        "complex": 1j,
        "Decimal": Decimal("1.5"),
        "Fraction": Fraction(1, 2),
        "date": dt.date(2020, 1, 1),
        "datetime": dt.datetime(2020, 1, 1, tzinfo=dt.UTC),
        "timedelta": dt.timedelta(1),
    }
    for mode, _desc, types in _OUTPUT_TYPE_CONDITIONAL:
        if mode not in _NEW_FORM_A:
            continue
        fn = _perturbed_fn(mode, src)
        for tname in types:
            calls: list = []
            fn(calls, samples[tname])
            assert len(calls) == 1, (mode, tname, len(calls))


def test_a_shadowed_builtin_cannot_change_the_perturbation():
    # The function's own parameters shadow every builtin the templates use. Reached through
    # __import__("builtins"), the perturbation is still the operator Def. 11.8 names.
    src = textwrap.dedent(
        """
        def f(v, type=None, min=None, repr=None, list=None, dict=None, tuple=None, set=None,
              frozenset=None, int=None, str=None, bytes=None, round=None, bool=None):
            return v
        """
    )
    assert _perturbed_fn("return_drop", src)({"a", "b"}) == {"b"}
    assert _perturbed_fn("return_ctype", src)([1, 2]) == (1, 2)
    assert _perturbed_fn("return_round", src)(2.6) == 3.0
    assert _perturbed_fn("return_type", src)("é") == "é".encode()
    assert _perturbed_fn("return_zero_of", src)(2.5) == 0.0


def test_a_set_element_is_chosen_the_same_way_under_every_hash_seed(tmp_path):
    # converge re-observes the function in an isolated worker, a separate process. A set element
    # chosen by iteration order would move with PYTHONHASHSEED, the verdicts would differ between
    # the two observations, and the reproducibility check would refuse the certificate.
    probe = tmp_path / "probe.py"
    probe.write_text(
        textwrap.dedent(
            """
            import ast, json, sys
            from Wesker.engine import _OutputMutator

            def run(mode, value):
                node = ast.parse("def f(v):\\n    return v\\n").body[0]
                m = _OutputMutator(0, mode)
                out = m.visit(node)
                ast.fix_missing_locations(out)
                ns = {}
                exec(compile(ast.Module(body=[out], type_ignores=[]), "<p>", "exec"), ns)
                return sorted(ns["f"](value))

            words = {"alpha", "beta", "gamma", "delta", "epsilon"}
            print(json.dumps([run("return_drop", words), run("return_singleton", words)]))
            """
        )
    )
    seen = set()
    for seed in ("0", "1", "2", "12345"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        out = subprocess.run(
            [sys.executable, str(probe)],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        seen.add(out)
    assert len(seen) == 1, seen
    dropped, single = json.loads(seen.pop())
    assert dropped == ["beta", "delta", "epsilon", "gamma"]
    assert single == ["alpha"]


def test_a_heterogeneous_return_forgoes_every_mode_one_branch_cannot_take():
    node = ast.parse("def f(x):\n    return x\n").body[0]

    def modes(observed):
        return {
            _sub_mode(m)
            for m in generate_mutants(
                node,
                {MutationCategory.OUTPUT},
                max_per_category=0,
                observed_return_types=frozenset(observed),
            )
        }

    # int | str: `x + 1` would raise on the str branch, `x.swapcase()` on the int branch.
    mixed = modes({"int", "str"})
    assert not mixed & {
        "return_plus_one",
        "return_scale",
        "return_swapcase",
        "return_pad",
    }
    assert "return_type" in mixed  # applicable to both, and total on both
    # list | dict: drop dispatches per type, so it stays; duplicate has no dict meaning.
    containers = modes({"list", "dict"})
    assert "return_drop" in containers
    assert "return_duplicate" not in containers
    # bool is not int: no numeric operator for a predicate.
    assert not modes({"bool"}) & {"return_plus_one", "return_scale", "return_negate"}
    assert {"return_not", "return_true", "return_false"} <= modes({"bool"})


def test_count_equals_generation_under_every_observed_type():
    # The census must count exactly the mutants generation emits for each observed codomain, or
    # the denominator lies about the type-conditional universe (the issue-#9 invariant).
    node = ast.parse(
        "def f(x, y):\n    if x:\n        return x\n    return [x, y]\n"
    ).body[0]
    for tname in _EDGE:
        obs = frozenset({tname})
        muts = generate_mutants(
            node,
            {MutationCategory.OUTPUT},
            max_per_category=0,
            observed_return_types=obs,
        )
        assert len(muts) == estimate_universe_size(
            node, {MutationCategory.OUTPUT}, observed=obs
        ), tname


# The ids Wesker 1addf57 generated for `return x / 2`, one table per interpreter family. A content id
# hashes `ast.dump(..., include_attributes=True)`, whose default output changed in Python 3.13 (empty
# optional fields are omitted), so the same mutation has one id under 3.12 and another under 3.13+.
# Both tables were measured at 1addf57 and again at 6ba533d (3.12.12 and 3.14.6) and agree, so the
# property below holds in each family; the cross-family difference predates the new operators.
_IDS_AT_1ADDF57 = {
    "3.13+": {
        "return_none": "OUTPUT_988a4470",
        "return_const": "OUTPUT_6dc24194",
        "return_identity": "OUTPUT_637e0fc8",
        "return_negate": "OUTPUT_63dccc59",
        "return_abs": "OUTPUT_0b3b40ca",
        "return_nan": "OUTPUT_ccc01580",
    },
    "3.12": {
        "return_none": "OUTPUT_a6d1d302",
        "return_const": "OUTPUT_e6e0a7d3",
        "return_identity": "OUTPUT_bb386c45",
        "return_negate": "OUTPUT_d9b1d53a",
        "return_abs": "OUTPUT_af8eac1d",
        "return_nan": "OUTPUT_cf3813ee",
    },
}


def test_the_nine_built_operators_keep_their_ids():
    # Appended to the table, never interleaved: the ids below are the ones Wesker 1addf57 generated.
    # A survivor's id and diff are what `flag` records, so moving them would orphan every flag.
    node = ast.parse("def f(x):\n    return x / 2\n").body[0]
    muts = generate_mutants(
        node,
        {MutationCategory.OUTPUT},
        max_per_category=0,
        observed_return_types=frozenset({"float"}),
    )
    ids = {_sub_mode(m): m.mutant_id for m in muts}
    expected = _IDS_AT_1ADDF57["3.13+" if sys.version_info >= (3, 13) else "3.12"]
    assert {k: ids[k] for k in expected} == expected


def test_a_template_takes_the_return_values_source_position():
    # Parsed alone, a template's nodes sit at line 1; carried into the mutant they must sit on the
    # return they replaced, like the hand-built rewrites do.
    node = ast.parse("def f(x):\n    y = x\n    return [y, y]\n").body[0]
    (m,) = [
        m
        for m in generate_mutants(
            node,
            {MutationCategory.OUTPUT},
            max_per_category=0,
            observed_return_types=frozenset({"list"}),
        )
        if _sub_mode(m) == "return_drop"
    ]
    ret = m.mutated_node.body[-1]
    assert {n.lineno for n in ast.walk(ret.value) if hasattr(n, "lineno")} == {3}
    assert m.mutated_line == 3


def test_a_constant_return_is_not_its_own_target():
    # `return True` under →True is the original program: a guaranteed-equivalent, never a target.
    def modes(src):
        node = ast.parse(src).body[0]
        return {
            _sub_mode(m)
            for m in generate_mutants(
                node,
                {MutationCategory.OUTPUT},
                max_per_category=0,
                observed_return_types=frozenset({"bool"}),
            )
        }

    assert "return_true" not in modes("def f(x):\n    return True\n")
    assert "return_false" not in modes("def f(x):\n    return False\n")


def _load(tmp_path, name, src):
    path = tmp_path / f"{name}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod, str(path)


_KILL_CASES = [
    # (family, source, observed type, the test that pins the value, modes it must kill)
    (
        "boolean",
        "def f(n):\n    return n % 2 == 0\n",
        "bool",
        "assert mod.f(2) is True and mod.f(3) is False",
        {"return_not", "return_true", "return_false", "return_type"},
    ),
    (
        "numeric",
        "def f(xs):\n    return sum(xs) / len(xs)\n",
        "float",
        "assert mod.f([1.0, 2.0]) == 1.5 and type(mod.f([1.0])) is float",
        {
            "return_zero_of",
            "return_type",
            "return_plus_one",
            "return_minus_one",
            "return_next_up",
            "return_next_down",
            "return_scale",
            "return_round",
            "return_inf",
        },
    ),
    (
        "string",
        "def f(name):\n    return 'Hi, ' + name + '!'\n",
        "str",
        "assert mod.f('Bob') == 'Hi, Bob!'",
        {
            "return_type",
            "return_truncate",
            "return_swapcase",
            "return_pad",
            "return_reverse",
        },
    ),
    (
        "container",
        "def f(xs):\n    return [x for x in xs if x % 2 == 0]\n",
        "list",
        "assert mod.f([1, 2, 3, 4, 6]) == [2, 4, 6]",
        {
            "return_drop",
            "return_duplicate",
            "return_singleton",
            "return_ctype",
            "return_sortbreak",
        },
    ),
    (
        "dict",
        "def f(xs):\n    return {x: len(x) for x in xs}\n",
        "dict",
        "assert mod.f(['a', 'bb']) == {'a': 1, 'bb': 2}",
        {"return_drop", "return_field_default"},
    ),
    (
        "ordered",
        "import datetime\n\ndef f(d):\n    return d + datetime.timedelta(days=1)\n",
        "date",
        "import datetime\n    assert mod.f(datetime.date(2020, 1, 31)) == datetime.date(2020, 2, 1)",
        {"return_adjacent"},
    ),
]


@pytest.mark.parametrize(
    ("family", "src", "tname", "pin", "expected"),
    _KILL_CASES,
    ids=[c[0] for c in _KILL_CASES],
)
def test_each_family_dies_by_assertion_on_a_pinning_test(
    tmp_path, family, src, tname, pin, expected
):
    # A discriminating test kills every operator of the family BY ASSERTION, never by a crash of
    # the perturbation itself: the kill is a value distinction the suite actually made.
    name = f"mu_family_{family}"
    mod, path = _load(tmp_path, name, src)
    try:
        func_node = next(
            n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef)
        )
        muts = [
            m
            for m in generate_mutants(
                func_node,
                {MutationCategory.OUTPUT},
                max_per_category=0,
                observed_return_types=frozenset({tname}),
            )
            if _sub_mode(m) in expected
        ]
        assert {_sub_mode(m) for m in muts} == expected
        ns: dict = {"mod": mod}
        # S102: the pinning test is a literal from the case table above
        exec(f"def case():\n    {pin}\n", ns)  # noqa: S102
        for m in muts:
            r = evaluate_mutant(m, [ns["case"]], mod.f, qualname="f", source_path=path)
            assert r.constructed and r.installed, _sub_mode(m)
            assert r.killed and r.killed_by == "assertion", (_sub_mode(m), r.killed_by)
    finally:
        sys.modules.pop(name, None)
