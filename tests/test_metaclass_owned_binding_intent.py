"""W#38 — a mutant whose binding the owner refuses is NOT INSTALLED; it never ends the file's profile.

THE DEFECT (reproduced 2026-10-25 on Wesker 1addf57). toolz's ``Compose`` defines a property whose
getter is literally named ``__name__``. Installing a mutant of it ran
``setattr(Compose, "__name__", <function>)``; for a class that assignment is taken by ``type``'s own
``__name__`` data descriptor, which accepts only a str, so ``TypeError: can only assign string to
Compose.__name__, not 'function'`` escaped ``_patch_mutant_into_test`` through ``evaluate_mutant`` and
``profile_file`` and ended the whole file's profile with no results for any function in it.

THE CONTRACT. A name the class's metaclass owns as a data descriptor, or any owner that refuses the
assignment, means the mutant cannot be bound: it is not installed, the original stays bound, nothing
is restored that was never installed, there is no fall-through to the bare-name strategies (for
``__name__`` those would rebind the TEST module's own ``__name__``), and every other function in the
file is still measured. Isolated execution reads the mutant ``not_installed``.

NOT closed here: the in-process path records no install proof at all (``MutantResult.installed`` keeps
its default there), so the same mutant reads ``not_entered`` in-process — unscored, never a kill or a
survivor, but under the wrong cause. Recording installation in ``evaluate_mutant`` is the remaining
step.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
import textwrap

import pytest

from Wesker.engine import (
    MutationCategory,
    _execution_guard,
    _metaclass_owns_name,
    _patch_mutant_into_test,
    _unpatch_mutant,
    evaluate_mutant,
    generate_mutants,
)

_SOURCE = textwrap.dedent(
    """
    class Compose:
        def __init__(self, *funcs):
            self.funcs = funcs

        def __call__(self, x):
            for f in reversed(self.funcs):
                x = f(x)
            return x

        @property
        def __name__(self):
            try:
                return "_of_".join(f.__name__ for f in self.funcs)
            except AttributeError:
                return type(self).__name__


    def compose(*funcs):
        return Compose(*funcs)
    """
)


def _load(tmp_path, name="w38_compose"):
    path = tmp_path / f"{name}.py"
    path.write_text(_SOURCE)
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module, str(path)


def _name_test(module):
    """A test whose globals hold `Compose`, as a real test module's would."""
    namespace = {
        "Compose": module.Compose,
        "compose": module.compose,
        "__name__": "tests.test_w38",
    }
    exec(  # noqa: S102
        "def test_name():\n"
        "    inc = lambda x: x + 1\n"
        "    inc.__name__ = 'inc'\n"
        "    assert compose(inc).__name__ == 'inc'\n",
        namespace,
    )
    return namespace["test_name"], namespace


class _Meta(type):
    pass


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("__name__", True),  # type's data descriptor: the class's own name
        ("__qualname__", True),
        ("__call__", False),  # a non-data slot on type: rebindable like any method
        ("__init__", False),
        ("compose_helper", False),  # absent everywhere on the metaclass
    ],
)
def test_the_metaclass_owns_exactly_its_data_descriptor_names(name, expected):
    assert _metaclass_owns_name(type("Plain", (), {}), name) is expected
    assert _metaclass_owns_name(_Meta("Custom", (), {}), name) is expected


def test_a_non_class_owner_is_never_metaclass_owned(tmp_path):
    module, _ = _load(tmp_path)
    assert _metaclass_owns_name(module, "__name__") is False
    assert _metaclass_owns_name(module.Compose(), "__name__") is False


def test_a_metaclass_owned_name_is_not_installed_and_nothing_moves(tmp_path):
    module, _ = _load(tmp_path)
    original = module.Compose.__dict__["__name__"]
    test_fn, namespace = _name_test(module)
    with _execution_guard() as proof:
        patched, saved, target = _patch_mutant_into_test(
            proof, test_fn, "Compose.__name__", lambda self: "MUTANT"
        )
        _unpatch_mutant(proof, patched, saved, target, "__name__")
    assert (patched, saved, target) == (False, None, None)
    assert module.Compose.__dict__["__name__"] is original
    assert module.Compose.__name__ == "Compose"
    # No fall-through to the bare-name strategies: the test module's own `__name__` is untouched.
    assert namespace["__name__"] == "tests.test_w38"


def test_an_owner_that_refuses_the_assignment_is_not_installed():
    # `int` is immutable: no metaclass descriptor owns `bit_length`, but the assignment is refused.
    namespace = {"int": int}
    exec("def test_fn():\n    assert int(5).bit_length() == 3\n", namespace)  # noqa: S102
    test_fn = namespace["test_fn"]
    with _execution_guard() as proof:
        patched, saved, target = _patch_mutant_into_test(
            proof, test_fn, "int.bit_length", lambda self: 0
        )
    assert (patched, saved, target) == (False, None, None)
    assert (5).bit_length() == 3


def test_evaluate_mutant_returns_instead_of_ending_the_profile(tmp_path):
    module, path = _load(tmp_path)
    tree = ast.parse(_SOURCE)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
    getter = next(
        n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "__name__"
    )
    mutant = next(iter(generate_mutants(getter, {MutationCategory.STATE})))
    test_fn, _ = _name_test(module)
    original = module.Compose.__dict__["__name__"]

    result = evaluate_mutant(
        mutant,
        [test_fn],
        original.fget,
        timeout_ms=2000,
        qualname="Compose.__name__",
        source_path=path,
    )

    assert result.killed is False, "a mutant that never ran cannot be killed"
    assert result.entered is False, "it was never installed, so never entered"
    assert module.Compose.__dict__["__name__"] is original
    assert module.Compose.__name__ == "Compose"


def test_the_file_profile_continues_and_isolated_reads_not_installed(
    tmp_path, monkeypatch
):
    from Wesker.ci import profile_file, run_with_live_suite

    (tmp_path / "w38_mod.py").write_text(_SOURCE)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_w38_mod.py").write_text(
        textwrap.dedent(
            """
            from w38_mod import Compose, compose


            def inc(x):
                return x + 1


            def double(x):
                return x * 2


            def test_name():
                assert compose(inc, double).__name__ == "inc_of_double"


            def test_call():
                assert compose(inc, double)(3) == 7
            """
        )
    )
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\npythonpath = ["."]\ntestpaths = ["tests"]\n'
    )
    monkeypatch.chdir(tmp_path)

    def body():
        return {
            mode: {
                r["function_key"]: r
                for r in profile_file(".", "w38_mod.py", isolated=mode)
            }
            for mode in (False, True)
        }

    rows = run_with_live_suite(str(tmp_path), body, target_files=["w38_mod.py"])
    assert rows is not None, "no live session"
    for mode, by_fn in rows.items():
        name_row = by_fn["w38_mod.py::Compose.__name__"]
        # Never a kill or a survivor: the mutants sit outside the denominator, and the run is refused.
        assert name_row["total_mutants"] == 0
        assert name_row["is_gateable"] is False
        # Every other function in the file was still measured.
        assert by_fn["w38_mod.py::Compose.__call__"]["total_killed"] > 0
        assert by_fn["w38_mod.py::compose"]["total_mutants"] > 0
        if mode:
            assert set(name_row["unscored_by"]) == {"not_installed"}
        else:
            assert sum(name_row["unscored_by"].values()) > 0
