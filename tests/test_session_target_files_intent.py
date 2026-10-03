"""The live session's baseline names the files it traces (Detective #103).

`run_with_live_suite` traces the session baseline "once for all of" its target files, and for any other
file "the per-function baseline stands". Only the first half was visible. A consumer profiling a function
in ANOTHER file inside the session read the shared baseline anyway; that baseline holds no line of the
file, so the profile came back empty (no kill, no coverage) and VALID. Measured through Detective's
`audit --remove`: it left the one-hop bridge check measuring nothing, and a test another function needed
was deleted.

`LazySessionBaseline.target_files` now carries the traced files' real paths, readable without forcing the
build (the `budgets` / `regime_digest` contract), and a fork keeps them. Pinned from intent.
"""

from __future__ import annotations

import os
import sys

from Wesker.ci import run_with_live_suite
from Wesker.engine import _SESSION_BASELINE, LazySessionBaseline


def test_the_holder_names_its_traced_files_without_forcing_the_build():
    built: list[int] = []
    holder = LazySessionBaseline(
        lambda subset=None: built.append(1), target_files=frozenset({"/r/src/f.py"})
    )
    assert holder.target_files == frozenset({"/r/src/f.py"})
    assert holder.built is False
    assert built == []


def test_an_undeclared_holder_is_empty_never_an_invented_set():
    """Empty means the constructor did not say (a bare closure, an older seam). A consumer reads it as
    undeclared, never as "traces no file"."""
    assert LazySessionBaseline(lambda subset=None: None).target_files == frozenset()


def test_a_fork_answers_for_the_same_files():
    """A fork is the same session baseline handed to a sibling function, so it traces the same files."""
    holder = LazySessionBaseline(
        lambda subset=None: None, target_files=frozenset({"/r/src/f.py"})
    )
    assert holder.fork().target_files == frozenset({"/r/src/f.py"})


def test_the_live_session_publishes_the_real_path_of_each_target(tmp_path):
    """Through the real seam: a target named RELATIVE to the root arrives as its real path, the form a
    frame's file resolves to, and nothing else is in the set."""
    mod = "wesker_target_files_probe"
    root = tmp_path / "proj"
    root.mkdir()
    (root / f"{mod}.py").write_text("def f(x):\n    return x + 1\n")
    (root / f"test_{mod}.py").write_text(
        f"from {mod} import f\n\n\ndef test_f():\n    assert f(1) == 2\n"
    )
    seen: dict[str, object] = {}

    def _probe():
        holder = _SESSION_BASELINE.get()
        seen["files"] = None if holder is None else holder.target_files

    cwd = os.getcwd()
    try:
        os.chdir(root)
        run_with_live_suite(str(root), _probe, target_files=[f"{mod}.py"])
    finally:
        os.chdir(cwd)
        for name in (mod, f"test_{mod}"):
            sys.modules.pop(name, None)
    assert seen["files"] == frozenset({os.path.realpath(root / f"{mod}.py")})
