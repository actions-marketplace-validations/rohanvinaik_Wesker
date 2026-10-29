"""Intent: code the engine runs on inputs it INVENTED cannot change the measuring process (W#29).

THE DEFECT, measured 2026-10-25 on 7e61cd3. Wesker's whole-codebase CI run sat 180 minutes in
`Thread.start()`, twice. Reproduced on Linux CPython 3.14.9 under a diagnostic, it showed:
- the hung worker's thread never ran a line of Python;
- the measuring process could map no memory at all;
- a logged `resource.setrlimit` named the cause: `RLIMIT_AS = (1, 1)` on the measuring process itself.

The stack was `run_function_converged → check_equivalent → orig_fn(*args)`, then
`_isolated_worker._apply_mem_limit → memory_guard.apply_address_limit → resource.setrlimit`.
The equivalence check runs the original and each mutant in the measuring process, on invented
boundary inputs. For `_apply_mem_limit` the ORIGINAL did exactly what it is written to do and capped its
caller's address space. A non-root process cannot raise a hard limit it lowered. Seconds later, a new
worker thread could not map its first frame and ended silently, and `Thread.start()` waited forever.
macOS does not enforce `RLIMIT_AS`, which is why it never hung there.

THE RULING:
- `check_equivalent` and `_check_equivalent_wrapper` run their calls under two stacked windows.
  `write_authority.contain_speculation` refuses, before the system call, the process effects it lists
  (resource limits, spawned processes, signals, the working directory, the environment).
  `contain_writes`, a test run's own window, refuses writes outside the authority. Each keeps its
  record, and the check reads both.
- A refused effect, raised or swallowed, is never evidence of equivalence.
- A real test run's window refuses none of the process effects: a test's own `monkeypatch.chdir`
  stays the remedy the write authority prescribes.

These tests use `RLIMIT_NOFILE`'s soft limit, which both macOS and Linux enforce and which the test
process can raise back.
"""

from __future__ import annotations

import ast
import os
import resource

import pytest

from Wesker.engine import MutationCategory, check_equivalent, generate_mutants
from Wesker.write_authority import (
    SpeculativeEffectRefused,
    contain_speculation,
    contain_writes,
)


def _node(src: str) -> ast.FunctionDef:
    return ast.parse(src).body[0]  # type: ignore[return-value]


@pytest.fixture
def nofile():
    before = resource.getrlimit(resource.RLIMIT_NOFILE)
    yield before
    resource.setrlimit(
        resource.RLIMIT_NOFILE, before
    )  # a guard that failed must not break the session


_LOWERS = (
    "def lower(n):\n"
    "    import resource\n"
    "    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)\n"
    "    resource.setrlimit(resource.RLIMIT_NOFILE, (min(soft, 64), hard))\n"
    "    return n\n"
)
_SWALLOWS = (
    "def quiet(n):\n"
    "    import resource\n"
    "    try:\n"
    "        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)\n"
    "        resource.setrlimit(resource.RLIMIT_NOFILE, (min(soft, 64), hard))\n"
    "    except BaseException:\n"
    "        pass\n"
    "    return n\n"
)


@pytest.mark.parametrize("src", [_LOWERS, _SWALLOWS], ids=["raised", "swallowed"])
def test_an_equivalence_check_cannot_lower_a_limit_of_the_measuring_process(
    nofile, src
):
    node = _node(src)
    mutants = generate_mutants(node, {MutationCategory.VALUE})
    assert mutants, "the fixture needs a mutant to compare"
    for mutant in mutants:
        assert check_equivalent(node, mutant) is False, (
            "an effectful function's mutant was judged equivalent by running it"
        )
    assert resource.getrlimit(resource.RLIMIT_NOFILE) == nofile, "the limit landed"


def test_a_speculative_chdir_is_refused_and_the_working_directory_stays(tmp_path):
    node = _node(
        f"def go(n):\n    import os\n    os.chdir({str(tmp_path)!r})\n    return n\n"
    )
    before = os.getcwd()
    mutants = generate_mutants(node, {MutationCategory.VALUE})
    assert mutants
    assert not any(check_equivalent(node, m) for m in mutants)
    assert os.getcwd() == before


def test_a_speculative_write_into_the_project_is_refused(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # the tree the window protects is the working directory
    node = _node(
        "def save(n):\n    with open('stray.txt', 'w') as fh:\n        fh.write(str(n))\n    return n\n"
    )
    mutants = generate_mutants(node, {MutationCategory.VALUE})
    assert mutants
    assert not any(check_equivalent(node, m) for m in mutants)
    assert not (tmp_path / "stray.txt").exists()


def test_the_window_refuses_while_armed_records_it_and_disarms_after(nofile):
    with contain_speculation() as refused, pytest.raises(SpeculativeEffectRefused):
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, nofile[1]))
    assert refused == ["resource.setrlimit"]
    assert resource.getrlimit(resource.RLIMIT_NOFILE) == nofile
    os.chdir(os.getcwd())  # disarmed: the same family of effect is no longer refused


def test_a_real_test_runs_window_keeps_chdir(tmp_path, monkeypatch):
    with contain_writes():
        monkeypatch.chdir(
            tmp_path
        )  # the remedy the write authority's own refusal prescribes
        assert os.path.samefile(os.getcwd(), tmp_path)


def test_a_pure_function_is_still_compared_by_running_it():
    # A mutant that is genuinely equivalent on every boundary input must still read equivalent: the guard
    # refuses effects, never a pure computation.
    node = _node("def ident(n):\n    m = n\n    return n\n")
    mutants = generate_mutants(
        node, {MutationCategory.DATAFLOW}
    )  # `return n -> return m`
    assert mutants
    assert all(check_equivalent(node, m) for m in mutants)


def test_the_window_refuses_process_effects_alone_and_composes_with_a_callers_own_write_guard(
    tmp_path, monkeypatch, nofile
):
    # Writes are not this window's business: Wesker stacks it with `contain_writes`, and Detective
    # composes it alone beside its own write guard, whose hook is then the one that sees and names a write.
    monkeypatch.chdir(tmp_path)
    with contain_speculation() as refused:
        (tmp_path / "theirs.txt").write_text("the caller's guard decides this")
        with pytest.raises(SpeculativeEffectRefused):
            resource.setrlimit(resource.RLIMIT_NOFILE, (64, nofile[1]))
    assert (tmp_path / "theirs.txt").exists()
    assert refused == ["resource.setrlimit"]
    assert resource.getrlimit(resource.RLIMIT_NOFILE) == nofile
