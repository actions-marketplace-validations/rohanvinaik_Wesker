"""Intent test: Wesker#27 — A timeout is not a kill; deterministic step budgets decide divergence.

Pins:
1. Wall-clock timeout returns killed=False, killed_by="undetermined".
2. Deterministic step budget exceeding cap returns killed=False, killed_by="diverged".
3. A runaway loop mutant stops deterministically via step budget and records "diverged".
4. mutant_disposition returns "diverged" and "undetermined" outside SCORED_DISPOSITIONS.
"""

from __future__ import annotations

import ast

from Wesker.engine import (
    SCORED_DISPOSITIONS,
    MutationCategory,
    evaluate_mutant,
    generate_mutants,
    mutant_disposition,
)


def _infinite_loop_fn(x: int) -> int:
    i = 0
    while i < x:
        i += 1
    return i


def test_mutant_disposition_vocabulary() -> None:
    """mutant_disposition maps diverged and undetermined to their named non-kill dispositions."""
    disp_div = mutant_disposition(
        constructed=True,
        installed=True,
        entered=True,
        contained=True,
        killed=False,
        killed_by="diverged",
    )
    assert disp_div == "diverged"
    assert disp_div not in SCORED_DISPOSITIONS

    disp_und = mutant_disposition(
        constructed=True,
        installed=True,
        entered=True,
        contained=True,
        killed=False,
        killed_by="undetermined",
    )
    assert disp_und == "undetermined"
    assert disp_und not in SCORED_DISPOSITIONS


def test_step_budget_stops_runaway_loop_deterministically() -> None:
    """A mutant that removes loop advance terminates deterministically under step_budget (#27)."""
    tree = ast.parse(
        """def loop_target(x: int) -> int:
    i = 0
    while i < x:
        i += 1
    return i
"""
    ).body[0]

    # Mutants will include deleting i += 1 (STMT: pass)
    mutants = list(generate_mutants(tree, [MutationCategory.STMT]))
    runaway_mutant = next(
        m
        for m in mutants
        if "pass" in getattr(m, "description", "")
        or m.category == MutationCategory.STMT
    )

    def test_runaway(fn=_infinite_loop_fn) -> None:
        from inspect import unwrap

        from Wesker.monitoring import step_budget

        # The caller declares this bound; the engine does not invent one for every test.
        with step_budget([unwrap(fn).__code__], cap=100):
            assert fn(10) == 10

    # Under evaluate_mutant with step_budget, the runaway loop is intercepted deterministically
    res = evaluate_mutant(
        runaway_mutant,
        [test_runaway],
        _infinite_loop_fn,
        timeout_ms=2000,
        qualname="loop_target",
    )

    assert res.killed is False
    assert res.killed_by == "diverged"


def test_wall_clock_timeout_is_undetermined_not_killed(monkeypatch) -> None:
    """A wall-clock timeout returns killed=False, killed_by="undetermined" (#27)."""
    tree = ast.parse(
        """def simple_target(x: int) -> int:
    return x + 1
"""
    ).body[0]
    mutants = list(generate_mutants(tree, [MutationCategory.VALUE]))
    mutant = mutants[0]

    def test_passing() -> None:
        pass

    import Wesker.engine as engine_mod

    monkeypatch.setattr(
        engine_mod, "_run_test_with_timeout", lambda *a, **k: "undetermined"
    )
    monkeypatch.setattr(engine_mod, "_outcome_on_original", lambda *a, **k: None)

    res = evaluate_mutant(
        mutant,
        [test_passing],
        lambda x: x + 1,
        timeout_ms=1000,
        qualname="simple_target",
    )

    assert res.killed is False
    assert res.killed_by == "undetermined"
