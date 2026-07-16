"""The private copy, and the guard that makes it work.

These two things are one design and neither is sound alone, so they are tested together. The
loader imports a second copy of the package under a private name with its intra-package imports
rewritten IN MEMORY; because both copies are compiled from the same files they share a
``co_filename``, which is precisely why ``_patch_module_qualified`` must discriminate on the
module NAME instead. The test below asserts that filenames are identical — not as trivia, but
because that identity is the reason the guard exists, and a future change that made them differ
would silently remove the guard's justification.
"""

from __future__ import annotations

import Wesker.ci
import Wesker.engine
from Wesker.engine import _is_private_copy
from Wesker.self_profile import PRIVATE_PREFIX, load_private_wesker, targets_own_package


def test_a_target_that_is_the_package_directory_itself_counts_as_self():
    """Detective found this one: with only a `startswith(package + os.sep)` test, a target
    naming the package DIRECTORY (rather than a file inside it) slips through, because
    'Wesker' does not start with 'Wesker/'. Such a run would profile Wesker with the public
    engine and self-mutate."""
    assert targets_own_package(["Wesker"], "Wesker", ".") is True


def test_a_sibling_whose_name_merely_starts_with_the_package_name_is_not_self():
    """Segment boundary: /x/Weskerish must not match a package at /x/Wesker."""
    assert targets_own_package(["Weskerish/x.py"], "Wesker", ".") is False


def test_an_ordinary_project_never_triggers_the_private_copy():
    assert targets_own_package(["src/app.py"], "Wesker", ".") is False


def test_the_private_copy_resolves_its_own_engine_not_the_public_one():
    """THE STEP-1 CLAIM. `ci` imports `run_function_converged` from `engine` at module scope;
    in the private copy that import must land on the PRIVATE engine. If it resolved to the
    public one, the profiling run would execute code that the run itself is busy mutating —
    which is the entire bug this design removes."""
    load_private_wesker()
    import _wesker_self.ci  # type: ignore[import-not-found]
    import _wesker_self.engine  # type: ignore[import-not-found]

    assert _wesker_self.ci.run_function_converged.__module__ == "_wesker_self.engine"
    assert Wesker.ci.run_function_converged.__module__ == "Wesker.engine"
    assert (
        _wesker_self.ci.run_function_converged is not Wesker.ci.run_function_converged
    )
    assert _wesker_self.engine is not Wesker.engine


def test_both_copies_share_a_co_filename_which_is_why_the_guard_is_name_based():
    """The guard's whole justification, asserted. Both copies are compiled from the same source
    file, so `_co_filename_matches` CANNOT tell them apart — only the module name can."""
    load_private_wesker()
    import _wesker_self.ci  # type: ignore[import-not-found]

    private = _wesker_self.ci.run_function_converged.__code__.co_filename
    public = Wesker.ci.run_function_converged.__code__.co_filename
    assert private == public

    assert _is_private_copy("_wesker_self.engine", PRIVATE_PREFIX) is True
    assert _is_private_copy("Wesker.engine", PRIVATE_PREFIX) is False


def test_loading_the_private_copy_is_idempotent():
    assert load_private_wesker() is load_private_wesker()
