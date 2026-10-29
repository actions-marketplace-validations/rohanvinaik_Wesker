"""A test whose file was edited after import must still fingerprint, never crash (Detective #104).

Measured while dogfooding Detective's `audit --remove` on Detective itself: the removal deleted three tests
in the middle of a test file, then re-audited the target in the same process. The live session's test
functions still carried their old line numbers, so `inspect.getsource` read the EDITED file from a stale
line inside a docstring and raised `tokenize.TokenError` ("unterminated string literal"). `test_fingerprint`
caught only OSError/TypeError, so the whole CLI died with a traceback after a removal it had already made.

A stale code object's source may be unreadable, depending on the interpreter's tokenizer. The same name
fallback is safe: the origin file's content digest is also part of the fingerprint, so an edited file never
warms a stale entry. Force tokenizer failures separately from the real edited-file scenario.
"""

from __future__ import annotations

import importlib.util
import inspect
import tokenize

import pytest

from Wesker.trace_cache import test_fingerprint as fingerprint_of

_BEFORE = (
    "def test_dup():\n"
    "    assert 5 > 0\n"
    "\n"
    "\n"
    "def test_kept():\n"
    '    """Zero is not positive,\n'
    "    which pins the boundary,\n"
    '    on its own line."""\n'
    "    assert 0 <= 0\n"
)
# `test_dup` deleted with ONE blank after it (three lines), the shape `audit --remove` left when the crash was
# measured: `test_kept` moves up three lines, so its old first line (5) now names the docstring's closing line,
# and tokenizing from there opens a string that never closes (measured: TokenError, "EOF in multi-line string").
_AFTER = _BEFORE.split("\n", 3)[3]


def _stale_function(tmp_path):
    """`test_kept` imported from its file the way pytest imports a test module, then the file edited."""
    path = tmp_path / "test_stale_mod.py"
    path.write_text(_BEFORE)
    spec = importlib.util.spec_from_file_location("test_stale_mod", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fn = module.test_kept
    before = fingerprint_of(fn)
    path.write_text(_AFTER)
    return fn, before


def test_a_test_edited_under_its_code_object_fingerprints_instead_of_crashing(tmp_path):
    fn, _ = _stale_function(tmp_path)
    assert isinstance(fingerprint_of(fn), str)


@pytest.mark.parametrize("error_type", (SyntaxError, tokenize.TokenError))
def test_unreadable_stale_source_uses_a_content_sensitive_fallback(
    tmp_path, monkeypatch, error_type
):
    fn, before = _stale_function(tmp_path)

    def unreadable_source(_fn):
        raise error_type("stale source")

    monkeypatch.setattr(inspect, "getsource", unreadable_source)
    assert isinstance(fingerprint_of(fn), str)
    assert fingerprint_of(fn) != before


def test_the_edit_still_voids_the_fingerprint(tmp_path):
    """The stale item cannot share a key with its pre-edit self."""
    fn, before = _stale_function(tmp_path)
    assert fingerprint_of(fn) != before


def test_two_stale_edits_never_share_a_fingerprint(tmp_path, monkeypatch):
    """The fallback key is only a NAME, so on its own two different edits would collide and the
    first edit's entry would be served for the second. The origin file's content digest is what
    keeps them apart; this pins that, since both edits take the fallback."""
    fn, _ = _stale_function(tmp_path)

    def unreadable_source(_fn):
        raise tokenize.TokenError("stale source")

    monkeypatch.setattr(inspect, "getsource", unreadable_source)
    first = fingerprint_of(fn)
    (tmp_path / "test_stale_mod.py").write_text(_AFTER + "# a later edit\n")
    assert fingerprint_of(fn) != first
