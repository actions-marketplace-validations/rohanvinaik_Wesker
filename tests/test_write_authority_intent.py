"""Intent pins for write authority: a test run under a mutant cannot write into the project (Detective #105).

THE DEFECT, measured 2026-10-04 while dogfooding `audit --remove` on Detective, and reproduced again
2026-10-25 in a disposable clone (13 untracked files from one run). Mutant evaluation runs with the
working directory set to the project root, on purpose. A SWAP mutant of
``atomic_write_text(path, source)`` therefore wrote files NAMED by a test's source text into that root,
and staging files such as ``pyproject.toml.tmp-<pid>`` landed beside the real ``pyproject.toml``: one
mutated rename from replacing it. The same mutant then scored as a CRASH KILL, because the test's
``read_text`` of the file it expected raised.

What the engine must do instead, and what these pin:

* a test run against a mutant may write only inside its authority — the session's pytest basetemp,
  entries this process created exclusively in the system temporary directory, devices — and every
  other effect is prevented before it lands;
* the prevented write is never a kill: the mutant is ``write_outside_authority``, neither killed nor
  survived, and names the test and the path;
* legitimate temporary writes (``tmp_path``, ``mkdtemp``, ``NamedTemporaryFile``, a
  ``TemporaryDirectory`` and its cleanup) keep working, while a file already in the temporary
  directory stays protected — the authority is not "the temporary directory";
* the baseline is not armed: a test's own writes there land exactly as before.

Written from what the engine must do; a generated suite would pin today's answer, right or wrong.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

import pytest

from Wesker.engine import (
    SCORED_DISPOSITIONS,
    MutationCategory,
    _isolated_result,
    evaluate_mutant,
    generate_mutants,
    mutant_disposition,
    run_function_profiling,
)
from Wesker.isolation import IsolatedRun
from Wesker.write_authority import (
    WRITE_OUTSIDE_AUTHORITY,
    WriteOutsideAuthority,
    contain_writes,
    declared_roots,
    install,
    session_write_roots,
    write_authority_disposition,
)

# THE PURE DECISION FIRST: when this file pins the decision, a mutant of it that refuses everything
# would make the end-to-end runs below fail for reasons unrelated to the assertion that kills it.

# ── the pure decision (#105, pinned) ─────────────────────────────────────────────────────────

ROOT = "/work/basetemp"
TEMP = "/sys/tmp"


def _decide(effect, path, exists=False, is_dir=False, roots=(ROOT,), temp=TEMP):
    return write_authority_disposition(effect, path, exists, is_dir, list(roots), temp)


def test_inside_a_root_is_authorized_for_every_effect():
    for effect, exists in (("create", False), ("remove", True), ("write", False)):
        assert _decide(effect, ROOT + "/t0/f", exists) == "inside_authority"
    assert _decide("remove", ROOT, exists=True) == "inside_authority", "the root itself"


def test_containment_is_by_whole_path_components():
    """`pytest-1` does not contain `pytest-10`: a prefix match would authorize a sibling directory."""
    assert _decide("write", "/work/basetemp1/f") == "outside_authority"
    assert _decide("write", "/work/basetemp/f", roots=("/work/basetemp/",)) == (
        "inside_authority"
    ), "a trailing separator on the root changes nothing"


def test_the_project_tree_is_outside_authority():
    assert _decide("write", "/proj/store.json.tmp-1") == "outside_authority"
    assert _decide("create", "/proj/new_dir") == "outside_authority"
    assert _decide("remove", "/proj/pyproject.toml", exists=True) == "outside_authority"


def test_an_exclusive_creation_directly_in_the_temp_root_is_a_fresh_entry():
    assert _decide("create", TEMP + "/tmpab12cd") == "fresh_temp_entry"


def test_only_an_exclusive_creation_of_a_direct_child_is_fresh():
    """A non-exclusive write can name a file that exists; a nested path lies in someone's directory."""
    assert _decide("write", TEMP + "/tmpab12cd") == "outside_authority"
    assert _decide("create", TEMP + "/someone/else") == "outside_authority"
    assert _decide("create", TEMP + "/tmpab12cd", temp="") == "outside_authority", (
        "no temp root known, no fresh entry"
    )


def test_operations_that_cannot_change_anything_are_no_effect():
    assert _decide("create", "/proj/existing", exists=True) == "no_effect", (
        "makedirs(exist_ok=True) on an existing directory"
    )
    assert _decide("remove", "/proj/missing", exists=False) == "no_effect"
    assert _decide("write", TEMP, exists=True, is_dir=True) == "no_effect", (
        "NamedTemporaryFile opens the temp directory itself; its opener creates the file"
    )


def test_an_existing_entry_never_becomes_a_fresh_one():
    """What makes the authority narrower than the temporary directory: an exclusive creation of an
    entry that already exists fails, so it grants nothing."""
    assert _decide("create", TEMP + "/pre-existing", exists=True) == "no_effect"


def test_an_unplaceable_path_or_unknown_effect_is_refused():
    assert _decide("write", "relative/path") == "unplaceable"
    assert _decide("write", "") == "unplaceable"
    assert _decide("chmod", ROOT + "/f") == "unplaceable"


def test_an_empty_root_authorizes_nothing():
    assert _decide("write", "/anything", roots=("",)) == "outside_authority"


# ── the hook, armed directly ─────────────────────────────────────────────────────────────────


@pytest.fixture
def layout(tmp_path, monkeypatch):
    """A project (the working directory, outside authority) beside the test's own authority root."""
    install()
    project = tmp_path / "project"
    authority = tmp_path / "authority"
    project.mkdir()
    authority.mkdir()
    (project / "pyproject.toml").write_text("[project]\nname = 'real'\n")
    monkeypatch.chdir(project)
    with declared_roots([str(authority)]):
        yield project, authority


def _project_entries(project: Path) -> set[str]:
    return {p.name for p in project.iterdir()}


def test_a_write_inside_the_authority_lands(layout):
    _, authority = layout
    with contain_writes() as blocked:
        (authority / "store.json").write_text("ok")
        os.makedirs(authority / "a" / "b")
        os.replace(authority / "store.json", authority / "a" / "b" / "moved.json")
    assert blocked == []
    assert (authority / "a" / "b" / "moved.json").read_text() == "ok"


def test_a_relative_write_lands_in_the_project_and_is_prevented_and_named(layout):
    project, _ = layout
    before = _project_entries(project)
    with contain_writes() as blocked, pytest.raises(WriteOutsideAuthority):
        Path("store.json.tmp-123").write_text("stray")
    assert _project_entries(project) == before, "the write landed"
    assert blocked == [os.path.join(os.path.realpath(project), "store.json.tmp-123")]


def test_a_rename_into_the_project_is_prevented(layout):
    """D#105's near-miss: a staged file renamed over the project's real pyproject.toml."""
    project, authority = layout
    staged = authority / "pyproject.toml.tmp-1"
    staged.write_text("[project]\nname = 'test-content'\n")
    with contain_writes() as blocked, pytest.raises(WriteOutsideAuthority):
        os.replace(staged, project / "pyproject.toml")
    assert (project / "pyproject.toml").read_text() == "[project]\nname = 'real'\n"
    assert staged.exists()
    assert len(blocked) == 1


def test_a_rename_out_of_the_project_is_prevented(layout):
    """Both endpoints are effects: moving a project file out deletes it from the project."""
    project, authority = layout
    with contain_writes() as blocked, pytest.raises(WriteOutsideAuthority):
        os.rename(project / "pyproject.toml", authority / "taken")
    assert (project / "pyproject.toml").exists()
    assert blocked


def test_removing_a_project_file_is_prevented(layout):
    project, _ = layout
    with contain_writes() as blocked, pytest.raises(WriteOutsideAuthority):
        (project / "pyproject.toml").unlink()
    assert (project / "pyproject.toml").exists()
    assert blocked


def test_an_exclusive_create_in_the_project_is_prevented(layout):
    project, _ = layout
    with contain_writes() as blocked:
        with pytest.raises(WriteOutsideAuthority):
            os.close(os.open("fresh", os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        with pytest.raises(WriteOutsideAuthority):
            os.mkdir("fresh_dir")
    assert not (project / "fresh").exists()
    assert not (project / "fresh_dir").exists()
    assert len(blocked) == 2


def test_operations_without_effect_in_the_project_are_not_prevented(layout):
    project, _ = layout
    with contain_writes() as blocked:
        os.makedirs(project, exist_ok=True)
        Path("missing.txt").unlink(missing_ok=True)
        with pytest.raises(FileNotFoundError):
            os.replace("no-such-source", "pyproject.toml")
    assert blocked == []


def test_legitimate_temporary_writes_keep_working(layout):
    """Every way the stdlib hands a test a temporary file or directory, cleanup included: the
    cleanup removes entries relative to a directory descriptor, which must be placed correctly."""
    with contain_writes() as blocked:
        made = tempfile.mkdtemp()
        Path(made, "inner.txt").write_text("x")
        fd, name = tempfile.mkstemp()
        os.write(fd, b"x")
        os.close(fd)
        os.unlink(name)
        with tempfile.NamedTemporaryFile("w") as fh:
            fh.write("x")
        with tempfile.TemporaryFile() as fh:
            fh.write(b"x")
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "sub").mkdir()
            Path(tmp, "sub", "deep.txt").write_text("x")
        shutil.rmtree(made)
        with open(os.devnull, "w") as sink:
            sink.write("x")
    assert blocked == []


def test_a_temporary_directory_made_before_the_window_is_still_the_tests_room(layout):
    """A module-scoped fixture or a collection-time `mkdtemp` runs before any mutant does."""
    made = tempfile.mkdtemp()
    try:
        with contain_writes() as blocked:
            Path(made, "later.txt").write_text("x")
        assert blocked == []
    finally:
        shutil.rmtree(made)


def test_a_file_already_in_the_temp_directory_stays_protected(layout):
    """The authority is NOT the temporary directory: an entry this process did not create
    exclusively — here written non-exclusively before the window — cannot be rewritten or removed."""
    path = os.path.join(tempfile.gettempdir(), f"wesker-preexisting-{os.getpid()}.txt")
    with open(path, "w") as fh:
        fh.write("someone else's")
    try:
        with contain_writes() as blocked:
            with pytest.raises(WriteOutsideAuthority), open(path, "w") as fh:
                fh.write("clobbered")
            with pytest.raises(WriteOutsideAuthority):
                os.unlink(path)
        assert Path(path).read_text() == "someone else's"
        assert len(blocked) == 2
    finally:
        os.unlink(path)


def test_removing_a_symlink_in_the_authority_does_not_follow_it(layout):
    project, authority = layout
    link = authority / "link"
    link.symlink_to(project / "pyproject.toml")
    with contain_writes() as blocked:
        link.unlink()
    assert blocked == []
    assert (project / "pyproject.toml").exists()


def test_writing_through_a_symlink_into_the_project_is_prevented(layout):
    project, authority = layout
    link = authority / "link"
    link.symlink_to(project / "pyproject.toml")
    with contain_writes() as blocked, pytest.raises(WriteOutsideAuthority):
        link.write_text("through the link")
    assert (project / "pyproject.toml").read_text() == "[project]\nname = 'real'\n"
    assert blocked


def test_a_swallowed_interception_is_still_recorded(layout):
    """The target may catch BaseException and carry on; the record is what the measurement reads."""
    project, _ = layout
    with contain_writes() as blocked:
        try:
            Path("stray").write_text("x")
        # BLE001/S110: a target swallowing everything is what is under test
        except BaseException:  # noqa: BLE001, S110
            pass
    assert blocked
    assert not (project / "stray").exists()


def test_a_thread_the_test_starts_is_held_to_the_same_authority(layout):
    project, _ = layout
    seen: dict = {}

    def writer():
        try:
            Path("from_thread").write_text("x")
        # BLE001: recorded for the assertion below
        except BaseException as exc:  # noqa: BLE001
            seen["exc"] = exc

    with contain_writes() as blocked:
        t = threading.Thread(target=writer)
        t.start()
        t.join(timeout=30)
    assert isinstance(seen.get("exc"), WriteOutsideAuthority)
    assert blocked
    assert not (project / "from_thread").exists()


def test_bytecode_is_suppressed_for_the_window_and_restored(layout):
    before = sys.dont_write_bytecode
    with contain_writes():
        assert sys.dont_write_bytecode is True
    assert sys.dont_write_bytecode is before


def test_the_session_roots_name_the_per_user_root_only_for_pytests_default_basetemp(
    tmp_path,
):
    """Pytest's default basetemp is a numbered directory under its per-user root; an explicit
    `--basetemp` is the regime's own choice and declares only itself."""

    class _Factory:
        def __init__(self, basetemp):
            self._basetemp = basetemp

        def getbasetemp(self):
            return self._basetemp

    def _config(basetemp):
        return type("C", (), {"_tmp_path_factory": _Factory(basetemp)})()

    default = tmp_path / "pytest-of-someone" / "pytest-7"
    given = tmp_path / "chosen-basetemp"
    for path in (default, given):
        path.mkdir(parents=True)
    real = os.path.realpath
    assert session_write_roots(_config(default)) == (
        real(default),
        real(default.parent),
    )
    assert session_write_roots(_config(given)) == (real(given),)
    assert session_write_roots(object()) == (), "no factory, nothing declared"


def test_a_nested_pytest_session_inside_the_window_is_not_refused(
    tmp_path, monkeypatch, request
):
    """Measured dogfooding #105's reproduction: a test that starts a NESTED pytest session in-process
    (a tool's live session; a raw `pytest.main`) creates that session's numbered basetemp beside the
    outer one, under the same per-user root, inside the window. Refusing it refused every mutant such
    a test reached — 13 of `audit.candidate_reach`'s — for the harness's write, not the mutant's.

    The project sits outside pytest's scratch root, as a real checkout does; one inside it is the
    next test's case."""
    project = Path(tempfile.mkdtemp(prefix="wa-nested-"))
    try:
        (project / "test_inner.py").write_text(
            "def test_inner(tmp_path):\n    (tmp_path / 'f').write_text('x')\n"
        )
        monkeypatch.chdir(project)
        with (
            declared_roots(session_write_roots(request.config)),
            contain_writes() as blocked,
        ):
            rc = pytest.main([str(project), "-p", "no:cacheprovider", "-q"])
        assert rc == 0
        assert blocked == [], blocked
    finally:
        monkeypatch.undo()
        shutil.rmtree(project)


def test_a_root_that_contains_the_project_grants_nothing(tmp_path, monkeypatch):
    """The project tree is never a test's room, wherever it is checked out: inside a declared root
    (pytest's scratch root, where the pair's own end-to-end tests keep their projects) or inside a
    temporary directory this process created. A root INSIDE the project (a project-local
    `--basetemp`) still stands."""
    project = tmp_path / "project"
    local_basetemp = project / ".basetemp"
    local_basetemp.mkdir(parents=True)
    monkeypatch.chdir(project)
    with declared_roots([str(tmp_path), str(local_basetemp)]):
        with contain_writes() as blocked, pytest.raises(WriteOutsideAuthority):
            Path("stray.txt").write_text("x")
        assert blocked and not (project / "stray.txt").exists()
        with contain_writes() as blocked:
            (local_basetemp / "t0").mkdir()
            (local_basetemp / "t0" / "f").write_text("x")
        assert blocked == []
    made = Path(tempfile.mkdtemp(prefix="wa-made-"))
    try:
        monkeypatch.chdir(made)
        with contain_writes() as blocked, pytest.raises(WriteOutsideAuthority):
            Path("stray.txt").write_text("x")
        assert blocked and not (made / "stray.txt").exists()
    finally:
        monkeypatch.undo()
        shutil.rmtree(made)


def test_unarmed_the_hook_prevents_nothing(layout):
    """The baseline is never armed: a test's own writes into the project land exactly as before."""
    project, _ = layout
    Path("baseline_out.txt").write_text("x")
    os.replace(project / "baseline_out.txt", project / "renamed.txt")
    assert (project / "renamed.txt").read_text() == "x"


# ── through the engine ───────────────────────────────────────────────────────────────────────

_STORE = (
    "import os\n\n\n"
    "def atomic_write_text(path, text):\n"
    "    staging = f'{path}.tmp-{os.getpid()}'\n"
    "    with open(staging, 'w') as fh:\n"
    "        fh.write(text)\n"
    "    os.replace(staging, path)\n\n\n"
    "def save(path, text):\n"
    "    atomic_write_text(path, text)\n"
    "    return path\n"
)


def _swap_mutant():
    node = next(n for n in ast.parse(_STORE).body if getattr(n, "name", "") == "save")
    mutants = generate_mutants(node, {MutationCategory.SWAP}, max_per_category=0)
    (swap,) = [
        m
        for m in mutants
        if "atomic_write_text(text, path)" in ast.unparse(m.mutated_node)
    ]
    return node, swap


@pytest.fixture
def store(tmp_path, monkeypatch):
    """The D#105 shape on disk, its own module, with the working directory as its project root."""
    install()
    project = tmp_path / "project"
    authority = tmp_path / "authority"
    project.mkdir()
    authority.mkdir()
    (project / "pyproject.toml").write_text("[project]\nname = 'real'\n")
    path = project / "wa_store.py"
    path.write_text(_STORE)
    spec = importlib.util.spec_from_file_location("wa_store", str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["wa_store"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.chdir(project)
    try:
        with declared_roots([str(authority)]):
            yield mod, str(path), project, authority
    finally:
        sys.modules.pop("wa_store", None)


def _saves_into(mod, authority):
    def test_saves():
        target = authority / "store.json"
        assert mod.save(str(target), '{"a": 1}') == str(target)
        assert target.read_text() == '{"a": 1}'

    return test_saves


def test_the_path_swapping_mutant_is_prevented_and_named_never_killed(store):
    """THE regression. Before: a stray `{"a": 1}` in the project root, and a crash kill."""
    mod, path, project, authority = store
    _, swap = _swap_mutant()
    before = _project_entries(project)
    result = evaluate_mutant(
        swap, [_saves_into(mod, authority)], mod.save, qualname="save", source_path=path
    )
    assert _project_entries(project) == before, "the mutant wrote into the project"
    assert result.killed is False, f"a prevented write was scored a kill: {result}"
    assert result.refusal == WRITE_OUTSIDE_AUTHORITY
    assert result.refused_test and result.refused_test.endswith("test_saves")
    assert result.blocked_writes and all(
        p.startswith(os.path.realpath(project)) for p in result.blocked_writes
    )
    disposition = mutant_disposition(
        result.constructed,
        result.installed,
        result.entered,
        True,
        False,
        result.refusal,
    )
    assert disposition == WRITE_OUTSIDE_AUTHORITY
    assert disposition not in SCORED_DISPOSITIONS
    assert mod.save.__code__.co_filename == path, "the original was not restored"


def test_a_kill_by_another_test_outranks_the_prevented_write(store):
    """A refusal withholds a verdict only where nothing else gives one. Here the second test keeps
    BOTH paths inside its authority, so the swapped write lands there, and it asserts the file is
    where it asked: an assertion kill earned without any prevented write."""
    mod, path, _, authority = store
    _, swap = _swap_mutant()

    def kills_inside_the_authority():
        wanted, other = authority / "wanted.txt", authority / "other.txt"
        mod.save(str(wanted), str(other))
        assert wanted.exists(), "the file was written somewhere else"

    result = evaluate_mutant(
        swap,
        [_saves_into(mod, authority), kills_inside_the_authority],
        mod.save,
        qualname="save",
        source_path=path,
    )
    assert result.killed is True, result
    assert result.killed_by == "assertion"
    assert result.refusal == "", "a refusal was carried on a kill"
    assert result.test_name and result.test_name.endswith("kills_inside_the_authority")


def test_an_assertion_kill_by_a_clean_test_stands_beside_a_refused_one(store):
    mod, path, _, authority = store
    node, _ = _swap_mutant()
    mutants = generate_mutants(node, {MutationCategory.OUTPUT}, max_per_category=0)

    def pins_the_return():
        target = authority / "pinned.json"
        assert mod.save(str(target), "v") == str(target)

    def writes_into_the_project():
        Path("written_by_the_test.txt").write_text("x")

    killed = 0
    for mutant in mutants:
        result = evaluate_mutant(
            mutant,
            [writes_into_the_project, pins_the_return],
            mod.save,
            qualname="save",
            source_path=path,
        )
        if result.killed:
            killed += 1
            assert result.killed_by == "assertion"
            assert result.refusal == "", "a refusal was carried on a kill"
    assert killed >= 1, "no mutant was killed, so the precedence was never exercised"


def test_a_test_that_writes_into_the_project_on_the_original_is_refused_under_every_mutant(
    store,
):
    """The baseline is unaffected (its write lands); under a mutant the same write is prevented, so
    every mutant is named — never killed, never a survivor."""
    mod, _, project, authority = store
    node, _ = _swap_mutant()
    target = authority / "s.json"

    def writes_project_then_pins():
        value = mod.save(str(target), "v")
        Path("report.txt").write_text(repr(value))
        assert value == str(target)

    res = run_function_profiling(
        node,
        "wa_store.py::save",
        {MutationCategory.OUTPUT, MutationCategory.STMT},
        [writes_project_then_pins],
        mod.save,
        max_per_category=0,
    )
    refused = sum(
        cr.unscored_by.get(WRITE_OUTSIDE_AUTHORITY, 0) for cr in res.per_category
    )
    assert refused >= 1, res.to_dict()
    assert res.total_killed == 0, "a prevented write was scored a kill"
    assert res.survivor_records == [], "a refused mutant was reported as a survivor"
    named = [
        r for r in res.unscored_records if r["disposition"] == WRITE_OUTSIDE_AUTHORITY
    ]
    assert len(named) == refused
    assert all(r["test"].endswith("writes_project_then_pins") for r in named)
    assert all(r["blocked_writes"] for r in named)
    # The baseline ran unarmed and its write landed; no mutant's run replaced what it wrote.
    assert (project / "report.txt").read_text() == repr(str(target))


# ── the isolated path's verdict mapping ──────────────────────────────────────────────────────


def _run(**kw):
    base = {"returncode": 1, "timed_out": False, "contained": True, "stdout": ""}
    base.update(kw)
    return IsolatedRun(**base)


def test_an_isolated_run_failed_only_by_the_guard_is_refused_not_killed():
    _, swap = _swap_mutant()
    result = _isolated_result(
        swap,
        _run(
            write_blocked="tests/t.py::test_saves", blocked_writes=("/proj/x",), ran=1
        ),
        1.0,
    )
    assert result.killed is False
    assert result.refusal == WRITE_OUTSIDE_AUTHORITY
    assert result.refused_test == "tests/t.py::test_saves"
    assert result.blocked_writes == ["/proj/x"]


def test_an_isolated_kill_by_another_node_stands():
    _, swap = _swap_mutant()
    result = _isolated_result(
        swap, _run(write_blocked="tests/t.py::a", killed_by="assertion", ran=2), 1.0
    )
    assert result.killed is True
    assert result.killed_by == "assertion"
    assert result.refusal == ""


# ── through a real pytest session, both execution modes ──────────────────────────────────────


@pytest.mark.parametrize("isolated", [False, True], ids=["in_process", "isolated"])
def test_a_live_session_contains_the_mutant_and_names_it(tmp_path, isolated):
    """End to end through `run_in_session`: the test keeps its paths under `tmp_path`, the SWAP
    mutant swaps them out, and the project root must come out exactly as it went in."""
    from Wesker.pytest_runner import run_in_session

    root = tmp_path / "proj"
    (root / "tests").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        "[project]\nname = 'real'\n\n[tool.pytest.ini_options]\npythonpath = ['.']\n"
    )
    (root / "wa_live_store.py").write_text(_STORE)
    (root / "tests" / "test_wa_live_store.py").write_text(
        "from wa_live_store import save\n\n\n"
        "def test_save_writes_the_file(tmp_path):\n"
        "    target = tmp_path / 'store.json'\n"
        "    assert save(str(target), '{\"a\": 1}') == str(target)\n"
        "    assert target.read_text() == '{\"a\": 1}'\n"
    )
    before = _project_entries(root)
    node = next(n for n in ast.parse(_STORE).body if getattr(n, "name", "") == "save")
    names = ("wa_live_store", "test_wa_live_store", "tests.test_wa_live_store")

    def body(calls, session):
        import wa_live_store

        return run_function_profiling(
            node,
            "wa_live_store.py::save",
            {MutationCategory.SWAP, MutationCategory.OUTPUT},
            calls,
            wa_live_store.save,
            max_per_category=0,
            isolated=isolated,
        )

    from Wesker.ci import _PROJECT_ROOT

    # The kill vocabulary names tests relative to the session's root, as `run_with_live_suite` binds it.
    token = _PROJECT_ROOT.set(str(root))
    cwd = os.getcwd()
    try:
        res = run_in_session(str(root), body)
    finally:
        os.chdir(cwd)
        _PROJECT_ROOT.reset(token)
        for name in names:
            sys.modules.pop(name, None)
    assert res is not None
    after = {e for e in _project_entries(root) if e not in ("__pycache__", ".wesker")}
    assert after == before, f"the project root changed: {sorted(after - before)}"
    assert (root / "pyproject.toml").read_text().startswith("[project]\nname = 'real'")
    named = [
        r for r in res.unscored_records if r["disposition"] == WRITE_OUTSIDE_AUTHORITY
    ]
    assert [r["change"] for r in named] == [
        "atomic_write_text(path, text) → atomic_write_text(text, path)"
    ], [(r["mutant_id"], r["disposition"]) for r in res.unscored_records]
    assert named[0]["test"].endswith("test_save_writes_the_file")
    assert all(
        os.path.dirname(p) == os.path.realpath(root) for p in named[0]["blocked_writes"]
    )
    assert res.total_killed >= 1, (
        "the OUTPUT mutants are killed as before: tmp_path writes land"
    )
    assert all(r["mutant_id"] != named[0]["mutant_id"] for r in res.killed_records)


@pytest.mark.parametrize("isolated", [False, True], ids=["in_process", "isolated"])
def test_the_prescribed_remedy_measures_the_mutant_in_both_modes(tmp_path, isolated):
    """The refusal's own remedy — resolve relative paths inside `tmp_path` (`monkeypatch.chdir`) —
    must work in both execution modes. The isolated worker arms at the CALL phase, after a fixture has
    changed directory, so the protected project tree must be the project root, never the working
    directory at arm time: read that way, `tmp_path` became the protected tree, and the test's own
    writes into it were refused under the very remedy the refusal prescribes."""
    from Wesker.ci import _PROJECT_ROOT
    from Wesker.pytest_runner import run_in_session

    root = tmp_path / "proj"
    (root / "tests").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        "[project]\nname = 'real'\n\n[tool.pytest.ini_options]\npythonpath = ['.']\n"
    )
    (root / "wa_remedy_store.py").write_text(_STORE)
    (root / "tests" / "test_wa_remedy_store.py").write_text(
        "import pytest\nfrom wa_remedy_store import save\n\n\n"
        "@pytest.fixture(autouse=True)\n"
        "def _inside_tmp(tmp_path, monkeypatch):\n"
        "    monkeypatch.chdir(tmp_path)\n\n\n"
        "def test_save_relative():\n"
        "    assert save('store.json', 'v') == 'store.json'\n"
        "    with open('store.json') as fh:\n"
        "        assert fh.read() == 'v'\n"
    )
    before = _project_entries(root)
    node = next(n for n in ast.parse(_STORE).body if getattr(n, "name", "") == "save")
    names = ("wa_remedy_store", "test_wa_remedy_store", "tests.test_wa_remedy_store")

    def body(calls, session):
        import wa_remedy_store

        return run_function_profiling(
            node,
            "wa_remedy_store.py::save",
            {MutationCategory.SWAP, MutationCategory.OUTPUT},
            calls,
            wa_remedy_store.save,
            max_per_category=0,
            isolated=isolated,
        )

    token = _PROJECT_ROOT.set(str(root))
    cwd = os.getcwd()
    try:
        res = run_in_session(str(root), body)
    finally:
        os.chdir(cwd)
        _PROJECT_ROOT.reset(token)
        for name in names:
            sys.modules.pop(name, None)
    assert res is not None
    refused = [
        r for r in res.unscored_records if r["disposition"] == WRITE_OUTSIDE_AUTHORITY
    ]
    assert refused == [], [(r["mutant_id"], r.get("blocked_writes")) for r in refused]
    assert res.total_killed == res.total_mutants >= 3, res.to_dict()
    after = {e for e in _project_entries(root) if e not in ("__pycache__", ".wesker")}
    assert after == before
