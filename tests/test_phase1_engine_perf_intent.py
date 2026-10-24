from __future__ import annotations

import ast
import types

from Wesker.engine import (
    _precompute_patch_targets,
    _prepare_base_globals,
)
from Wesker.tce import compute_node_key, nodes_equivalent


def test_tce_precomputed_key() -> None:
    """nodes_equivalent must accept precomputed original_key and match AST equivalence (#41)."""
    node1 = ast.parse("x = 1 + 2").body[0]
    node2 = ast.parse("x = 1 + 2").body[0]
    node3 = ast.parse("x = 1 + 3").body[0]

    key1 = compute_node_key(node1)
    assert key1 is not None

    assert nodes_equivalent(node1, node2, original_key=key1) is True
    assert nodes_equivalent(node1, node3, original_key=key1) is False


def test_precompute_patch_targets(monkeypatch) -> None:
    """_precompute_patch_targets returns patch targets for qualified module names (#40)."""
    import sys

    mod = types.ModuleType("my_test_pkg.my_mod")

    def dummy():
        pass

    mod.dummy = dummy
    monkeypatch.setitem(sys.modules, "my_test_pkg.my_mod", mod)

    targets = _precompute_patch_targets("dummy", dummy.__code__.co_filename, "dummy")
    assert len(targets) > 0
    assert (mod, False) in targets


def test_prepare_base_globals_relative_package() -> None:
    """_prepare_base_globals must preserve __package__ and __name__ for relative imports (#46)."""
    fn_globals = {"__package__": "my_pkg.subpkg", "__name__": "my_pkg.subpkg.mod"}

    def raw_fn():
        pass

    target_fn = types.FunctionType(raw_fn.__code__, fn_globals, name="target_fn")
    target_fn.__module__ = "my_pkg.subpkg.mod"

    base_globals = _prepare_base_globals(target_fn)
    assert base_globals["__package__"] == "my_pkg.subpkg"
    assert base_globals["__name__"] == "my_pkg.subpkg.mod"


def test_cli_isolated_and_mem_limit_flags(monkeypatch) -> None:
    """Wesker CLI must parse --isolated and --mem-limit-mb flags (#45)."""
    from Wesker import ci, cli

    captured = {}

    def fake_profile_codebase_live(root, targets, **kwargs):
        captured.update(kwargs)
        return {"kill_pct": 100, "total_killed": 1, "total_mutants": 1, "functions": []}

    monkeypatch.setattr(ci, "profile_codebase_live", fake_profile_codebase_live)
    monkeypatch.setattr(cli, "_discover_python_files", lambda paths: ["foo.py"])

    cli.main(["foo.py", "--isolated", "--mem-limit-mb", "256", "--quiet"])
    assert captured.get("isolated") is True
    assert captured.get("worker_mem_limit_mb") == 256
