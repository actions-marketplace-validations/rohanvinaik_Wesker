"""Intent tests for Wesker CLI flags: --isolated and --mem-limit-mb (W#45 / B01)."""

from __future__ import annotations

import pytest

from Wesker import cli


def test_cli_help_documents_isolation_flags(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--isolated" in out
    assert "--mem-limit-mb" in out


def test_cli_mem_limit_mb_must_be_positive():
    with pytest.raises(SystemExit) as exc:
        cli.main(["--mem-limit-mb", "0"])
    assert exc.value.code != 0

    with pytest.raises(SystemExit) as exc:
        cli.main(["--mem-limit-mb", "-10"])
    assert exc.value.code != 0


def test_cli_passes_isolation_flags_to_runner(monkeypatch, tmp_path):
    (tmp_path / "foo.py").write_text("def f(): return 1\n")
    called_with: dict = {}

    def fake_profile_codebase_live(root, files, **kwargs):
        called_with.update(kwargs)
        return {
            "kill_pct": 100,
            "total_killed": 1,
            "total_mutants": 1,
            "total_functions": 1,
            "elapsed_ms": 10,
        }

    import Wesker.ci

    monkeypatch.setattr(Wesker.ci, "profile_codebase_live", fake_profile_codebase_live)
    monkeypatch.chdir(tmp_path)

    rc = cli.main(["--isolated", "--mem-limit-mb", "256", "--quiet", "foo.py"])
    assert rc == 0
    assert called_with.get("isolated") is True
    assert called_with.get("worker_mem_limit_mb") == 256
