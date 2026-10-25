"""Write authority — where a test run under a mutant may change the filesystem (Detective #105).

THE DEFECT. Mutant evaluation runs with the working directory set to the project root, on purpose:
tests may read relative paths from it. So a mutant of a file-writing function writes wherever its
mutated paths resolve. Measured while dogfooding `audit --remove` on Detective: a SWAP mutant of
``atomic_write_text(path, source)`` wrote files NAMED by a test's source text into the project root,
and staging files such as ``pyproject.toml.tmp-<pid>`` landed beside the real ``pyproject.toml``. One
more mutated rename and the real file would have been replaced. Nothing contained it.

THE AUTHORITY, and why it is not "the temporary directory". A test run may change:

* the session's pytest temporary directory (``tmp_path``, ``tmpdir``, ``tmp_path_factory``) — the
  regime's own declared root, wherever ``--basetemp`` or pytest's default puts it;
* any entry this process CREATED EXCLUSIVELY, directly in the system temporary directory, and
  everything beneath it — what ``mkdtemp``, ``mkstemp``, ``NamedTemporaryFile`` and
  ``TemporaryDirectory`` hand a test;
* devices (``os.devnull``).

The second grant is what keeps legitimate temporary writes working without permitting the whole
temporary directory: an exclusive creation can never name an entry that already exists, so a test
gains room only where nothing was. A file another process left in the temporary directory, or one
this process wrote there non-exclusively, stays protected.

THE MECHANISM. One audit hook, installed once and armed only while a test runs against a mutant
(:func:`contain_writes`). An effect outside the authority raises :class:`WriteOutsideAuthority`
inside the hook, so it never lands. The raise is only how the test unwinds: pytest's call wrapper
and the engine's own worker both catch ``BaseException``, so the measurement reads the window's
record instead, after the run, where nothing the test caught can have erased it. A prevented write
is never a kill: the run's outcome is the guard's, not the mutant's. The caller names the mutant
``write_outside_authority``, neither killed nor survived.

Bytecode is suppressed for the window (``sys.dont_write_bytecode``) rather than allowlisted, so an
import a test performs lazily writes nothing at all.

THE BOUNDARY, stated: an audit hook sees what CPython audits. A subprocess's writes, native code
writing through its own file calls, and writes through descriptors opened before the window are
outside it. So is an ``open`` relative to a directory descriptor (the event carries no descriptor;
it is resolved against the working directory, the conservative reading). A thread that outlives the
window, an uncontained worker included, is no longer guarded once the window closes.
"""

from __future__ import annotations

import contextlib
import os
import sys
import tempfile
import threading
from collections.abc import Iterable, Iterator

try:  # POSIX only; without it a directory descriptor cannot be named, and stays unplaceable
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

#: The refusal code a mutant carries when a test run against it tried to write outside its authority.
WRITE_OUTSIDE_AUTHORITY = "write_outside_authority"


def write_authority_disposition(
    effect: str,
    path: str,
    exists: bool,
    is_dir: bool,
    roots: list[str],
    temp_root: str,
) -> str:
    """Whether ONE filesystem effect of a test run lies inside its write authority (#105, pure — pinned).

    Split out of the audit hook because the hook's inputs — an event's argument tuple, a directory
    descriptor, the live filesystem — cannot be supplied as literals, so every branch behind them
    would be unreachable by input synthesis. The hook resolves those into the plain facts here.

    ``effect`` is what the operation does to ``path``:

      "create"  an EXCLUSIVE creation: ``mkdir``, an ``O_EXCL`` / ``"x"`` open, a symlink or hard link
      "remove"  ``unlink``, ``rmdir``, ``rmtree``, the source of a rename
      "write"   any other open for writing, a truncate, the destination of a rename

    ``path`` is absolute and resolved; ``exists`` / ``is_dir`` describe it at event time. ``roots`` is
    the authority (the session's basetemp, devices, and every entry this process freshly created that
    contains ``path``); ``temp_root`` the resolved system temporary directory.

      "no_effect"          the operation cannot change the filesystem: an exclusive creation of a path
                           that exists (``makedirs(..., exist_ok=True)``), a removal of one that does not,
                           a write-open of an existing directory (``NamedTemporaryFile`` opens the
                           temporary directory itself and lets its opener create the file)
      "inside_authority"   ``path`` is a root or lies beneath one, compared by whole path components
      "fresh_temp_entry"   an exclusive creation of a new entry directly in ``temp_root``: it cannot
                           name anything that exists, so it is granted — and becomes authority itself
      "outside_authority"  anything else, the project tree included: prevented
      "unplaceable"        not an absolute path, or an effect this decision does not know: prevented,
                           because an effect that cannot be placed cannot be shown to be inside
    """
    if effect not in ("create", "remove", "write") or not os.path.isabs(path):
        return "unplaceable"
    if (effect == "create" and exists) or (effect == "remove" and not exists):
        return "no_effect"
    if effect == "write" and is_dir:
        return "no_effect"
    for root in roots:
        if root and (path == root or path.startswith(root.rstrip(os.sep) + os.sep)):
            return "inside_authority"
    if effect == "create" and temp_root and os.path.dirname(path) == temp_root:
        return "fresh_temp_entry"
    return "outside_authority"


class WriteOutsideAuthority(BaseException):
    """A test run under a mutant tried to change the filesystem outside its write authority (#105).

    Raised INSIDE the audit hook, so the operation never happens. A ``BaseException``, like
    ``interrupt.Abandoned``: a target that wraps its write in ``except Exception`` would otherwise
    swallow it and carry on down a fallback branch the real run never takes. Swallowing it cannot
    unwrite the window's record, which is what the measurement reads.
    """


# The audited operations that change the filesystem. `os.replace` raises "os.rename", and
# `os.unlink` raises "os.remove"; both spellings are listed so neither depends on that.
_EVENTS = frozenset(
    {
        "open",
        "os.mkdir",
        "os.rename",
        "os.replace",
        "os.remove",
        "os.unlink",
        "os.rmdir",
        "shutil.rmtree",
        "os.symlink",
        "os.link",
        "os.truncate",
    }
)
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
_EXCLUSIVE = os.O_CREAT | os.O_EXCL
# Linux's nameless file: an open with it creates no directory entry at all.
_ANONYMOUS = getattr(os, "O_TMPFILE", 0)


def _is_path(raw: object) -> bool:
    return isinstance(raw, (str, bytes, os.PathLike))


def _optional(args: tuple, index: int) -> object:
    return args[index] if len(args) > index else None


def _open_effect(args: tuple) -> tuple[tuple[str, object, object, bool], ...]:
    """The effect of an ``open`` event: ``(path, mode, flags)``, mode ``None`` for ``os.open``."""
    raw, mode, flags = args[0], _optional(args, 1), _optional(args, 2)
    if not _is_path(raw):
        return ()  # a descriptor: its own open was the audited event
    if isinstance(flags, int):
        writes, exclusive = bool(flags & _WRITE_FLAGS), flags & _EXCLUSIVE == _EXCLUSIVE
        if _ANONYMOUS and flags & _ANONYMOUS == _ANONYMOUS:
            return ()
    else:
        writes = isinstance(mode, str) and any(ch in mode for ch in "wax+")
        exclusive = isinstance(mode, str) and "x" in mode
    if not writes:
        return ()
    # A write follows a symlink to its target; an exclusive creation of an existing link fails.
    return (
        (("create", raw, None, False),) if exclusive else (("write", raw, None, True),)
    )


def _effects(event: str, args: tuple) -> tuple[tuple[str, object, object, bool], ...]:
    """``(effect, raw path, dir_fd, follow)`` for each path an audited operation changes.

    ``follow`` is True only where the operation writes THROUGH a final symlink. A removal, a rename and
    a creation act on the entry itself, so its parent is resolved and its own name kept: resolving a
    link in ``tmp_path`` to a target elsewhere would refuse removing the link.
    """
    if event == "open":
        return _open_effect(args)
    if event == "os.mkdir":
        return (("create", args[0], _optional(args, 2), False),)
    if event in ("os.rename", "os.replace"):
        return (
            ("remove", args[0], _optional(args, 2), False),
            ("write", args[1], _optional(args, 3), False),
        )
    if event in ("os.remove", "os.unlink", "os.rmdir", "shutil.rmtree"):
        return (("remove", args[0], _optional(args, 1), False),)
    if event == "os.symlink":
        return (("create", args[1], _optional(args, 2), False),)
    if event == "os.link":
        return (("create", args[1], _optional(args, 3), False),)
    if event == "os.truncate" and _is_path(args[0]):
        return (("write", args[0], None, True),)
    return ()


def _fd_directory(fd: int) -> str | None:
    """The path a directory descriptor names, or None where the platform cannot say.

    ``shutil.rmtree`` — and so ``TemporaryDirectory.cleanup`` — removes entries RELATIVE to a directory
    descriptor (``os.remove('f', 4)``). Resolved against the working directory instead, every one of
    them would land in the project root and refuse an ordinary cleanup.
    """
    get_path = getattr(fcntl, "F_GETPATH", None)
    try:
        if get_path is not None:  # macOS
            raw = fcntl.fcntl(fd, get_path, bytes(1024))  # type: ignore[union-attr]
            return os.fsdecode(raw.split(b"\0", 1)[0]) or None
        return os.readlink(f"/proc/self/fd/{fd}")  # Linux
    except OSError:
        return None


def _place(raw: object, dir_fd: object, follow: bool) -> str | None:
    """``raw`` as an absolute, resolved path; ``""`` for an empty one, which names nothing and fails on
    its own; None when it cannot be placed."""
    try:
        text = os.fsdecode(raw)  # type: ignore[arg-type]
        if not text:
            return ""
        if os.path.isabs(text):
            absolute = text
        elif isinstance(dir_fd, int) and dir_fd >= 0:
            base = _fd_directory(dir_fd)
            if base is None:
                return None
            absolute = os.path.join(base, text)
        else:
            absolute = os.path.join(os.getcwd(), text)
        parent, name = os.path.split(absolute)
        if follow or name in ("", ".", ".."):
            return os.path.realpath(absolute)
        return os.path.join(os.path.realpath(parent), name)
    except (TypeError, ValueError, OSError):
        return None


_TEMP_ROOTS: dict[str, str] = {}


def _temp_root() -> str:
    raw = tempfile.gettempdir()
    real = _TEMP_ROOTS.get(raw)
    if real is None:
        real = _TEMP_ROOTS[raw] = os.path.realpath(raw)
    return real


def _device_roots() -> tuple[str, ...]:
    return (os.path.realpath(os.devnull), "/dev") if os.name == "posix" else ()


# Every entry this process created exclusively, directly in the temporary directory. Tracked whether
# or not a window is armed, so a temporary directory a module-scoped fixture or a collection-time
# `mkdtemp` made before any mutant ran is still the test's own room once one does.
_CREATED: set[str] = set()
# Roots the regime declares for the running session (`declared_roots`): its pytest basetemp.
_DECLARED: tuple[str, ...] = ()
# The armed window — its interception record and its roots, read together in one load so a thread
# racing the window's close sees one window or none — or None while no test runs against a mutant.
_ACTIVE: tuple[list[str], tuple[str, ...]] | None = None
_LOCAL = threading.local()
_INSTALL_LOCK = threading.Lock()
_installed = False


def _created_ancestors(path: str) -> list[str]:
    """The freshly created entries that are ``path`` or contain it — a walk of its parents."""
    found: list[str] = []
    current = path
    while True:
        if current in _CREATED:
            found.append(current)
        parent = os.path.dirname(current)
        if parent == current:
            return found
        current = parent


def _hook(event: str, args: tuple) -> None:
    if event not in _EVENTS:
        return
    window = _ACTIVE
    if window is None:
        # Unarmed, only an exclusive creation matters: it may become the test's room later.
        if event == "open":
            flags = _optional(args, 2)
            if not (isinstance(flags, int) and flags & _EXCLUSIVE == _EXCLUSIVE):
                return
        elif event != "os.mkdir":
            return
    if getattr(_LOCAL, "busy", False):
        return  # this hook's own resolution (a descriptor lookup) is not a test's effect
    _LOCAL.busy = True
    try:
        blocked, roots = window if window is not None else (None, ())
        for effect, raw, dir_fd, follow in _effects(event, args):
            if blocked is None and effect != "create":
                continue
            path = _place(raw, dir_fd, follow)
            if path == "":
                code = "no_effect"
            elif path is None:
                code = "unplaceable"
            else:
                code = write_authority_disposition(
                    effect,
                    path,
                    os.path.lexists(path),
                    os.path.isdir(path),
                    [*roots, *_created_ancestors(path)],
                    _temp_root(),
                )
            if code == "fresh_temp_entry" and path is not None:
                _CREATED.add(path)
            elif blocked is not None and code in ("outside_authority", "unplaceable"):
                blocked.append(path if path is not None else repr(raw))
                raise WriteOutsideAuthority(f"{event}: {path or raw!r}")
            if event in ("os.rename", "os.replace") and code == "no_effect":
                return  # a rename whose source is missing fails; its destination is untouched
    finally:
        _LOCAL.busy = False


def install() -> None:
    """Install the audit hook once per process. Unarmed, it only records exclusive temporary creations.

    Installed before collection where the pair controls the session (`pytest_runner.run_in_session`,
    the isolated worker), so a temporary directory created at import or by a fixture is known by the
    time a mutant's test writes into it. The stdlib validates its temporary directory with a probe
    write on first use; that runs here, before the hook can see it.
    """
    global _installed
    if _installed:
        return
    with _INSTALL_LOCK:
        if _installed:
            return
        _temp_root()
        sys.addaudithook(_hook)
        _installed = True


@contextlib.contextmanager
def declared_roots(roots: Iterable[str]) -> Iterator[None]:
    """Declare the running session's write roots — its pytest basetemp — for the duration."""
    global _DECLARED
    install()
    previous = _DECLARED
    _DECLARED = tuple(os.path.realpath(root) for root in roots if root)
    try:
        yield
    finally:
        _DECLARED = previous


@contextlib.contextmanager
def contain_writes() -> Iterator[list[str]]:
    """Arm the write authority for ONE test run against a mutant; yield the record of what it prevented.

    Process-wide while armed, so a thread the test or the code under test starts is held to the same
    authority as the test's own worker. The record is the measurement's signal, not the exception:
    read it after the run.
    """
    global _ACTIVE
    install()
    blocked: list[str] = []
    previous, previous_bytecode = _ACTIVE, sys.dont_write_bytecode
    _ACTIVE = (blocked, (*_DECLARED, *_device_roots()))
    sys.dont_write_bytecode = True
    try:
        yield blocked
    finally:
        _ACTIVE, sys.dont_write_bytecode = previous, previous_bytecode


def session_write_roots(config: object) -> tuple[str, ...]:
    """The write roots a pytest session's regime declares: its basetemp, resolved.

    Reading the basetemp CREATES it on first use, and creating it rotates pytest's numbered
    directories and repoints its ``pytest-current`` link — writes outside any test's authority. So it
    is read here, before a window is armed, never lazily inside one. A session without the factory (a
    pytest that does not provide it) declares nothing, and its tests' ``tmp_path`` writes are refused
    by name rather than silently allowed.
    """
    factory = getattr(config, "_tmp_path_factory", None)
    getbasetemp = getattr(factory, "getbasetemp", None)
    if getbasetemp is None:
        return ()
    try:
        return (os.path.realpath(str(getbasetemp())),)
    # BLE001: describing the session's authority must not fail the session; none is declared
    except Exception:  # noqa: BLE001
        return ()
