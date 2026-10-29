"""The μ⁻ catalog (#44): every operator of Def. 11.8, and the engine sub-modes that realize it.

Intent tests authored from docs/theory/NEGATIVE_SPECIFICATION.md, Def. 11.8.

THE DEFECT. A two-sign certificate named only the sub-modes it ran. Nothing said which of
Def. 11.8's 38 operators those were, or which it did not measure and why. A reader of a
"✓ COMPLETE" had no way to tell a fence the suite pins from one the engine never asked about.

WHAT MUST HOLD. The catalog lists each of the 38 operators exactly once, Def. 11.8 counting
"empty" once across the string and container families. A built, partial or realized operator names
only sub-modes the engine really generates. An operator that is not generated says why. Every OUTPUT
sub-mode the engine generates is accounted to some operator, so nothing is measured that the
catalog does not name.
"""

from __future__ import annotations

from collections import Counter

from Wesker.engine import (
    _OUTPUT_CALL_SUB_MODES,
    _OUTPUT_SUB_MODES,
    _OUTPUT_TYPE_CONDITIONAL,
    _OUTPUT_YIELD_SUB_MODES,
    _STATE_SUB_MODES,
)
from Wesker.mu_minus import MU_MINUS_CATALOG

_OUTPUT_MODES = (
    {mode for mode, _desc in _OUTPUT_SUB_MODES}
    | {mode for mode, _desc, _types in _OUTPUT_TYPE_CONDITIONAL}
    | {mode for mode, _desc in _OUTPUT_YIELD_SUB_MODES + _OUTPUT_CALL_SUB_MODES}
)


def test_the_catalog_is_def_11_8_operator_for_operator():
    keys = [op.key for op in MU_MINUS_CATALOG]
    assert len(keys) == 38 and len(set(keys)) == 38
    families = Counter(op.family for op in MU_MINUS_CATALOG)
    assert families == {
        "(i) universal": 6,
        "(ii) boolean": 3,
        "(iii) numeric": 9,
        "(iv) string": 5,
        "(v) container": 6,
        "(vi) structured": 2,
        "(vii) ordered": 3,
        "(viii) effect": 4,
    }


def test_the_standing_of_each_operator_is_one_of_four_named_states():
    statuses = Counter(op.status for op in MU_MINUS_CATALOG)
    assert statuses == {"built": 30, "partial": 2, "realized_by": 2, "unsupported": 4}
    assert {op.key for op in MU_MINUS_CATALOG if op.status == "unsupported"} == {
        "field",
        "class",
        "clamp",
        "state-extra",
    }
    assert {op.key for op in MU_MINUS_CATALOG if op.status == "partial"} == {
        "dict",
        "raise",
    }
    assert {op.key for op in MU_MINUS_CATALOG if op.status == "realized_by"} == {
        "0",
        "state-noop",
    }


def test_every_named_mode_is_one_the_engine_generates():
    state_modes = {mode for mode, _desc in _STATE_SUB_MODES}
    for op in MU_MINUS_CATALOG:
        for qualified in op.modes:
            category, _, mode = qualified.partition(":")
            if category == "OUTPUT":
                assert mode in _OUTPUT_MODES, (op.key, qualified)
            elif category == "STATE":
                assert mode in state_modes, (op.key, qualified)
            else:
                assert (category, mode) == ("STMT", ""), (op.key, qualified)


def test_a_measured_operator_names_its_modes_and_an_unmeasured_one_says_why():
    for op in MU_MINUS_CATALOG:
        if op.status == "unsupported":
            assert not op.modes and op.note, op.key
        else:
            assert op.modes, op.key
        if op.status in ("partial", "realized_by"):
            assert op.note, op.key


def test_every_generated_output_mode_is_accounted_to_an_operator():
    named = {
        qualified.partition(":")[2]
        for op in MU_MINUS_CATALOG
        for qualified in op.modes
        if qualified.startswith("OUTPUT:")
    }
    assert _OUTPUT_MODES == named
