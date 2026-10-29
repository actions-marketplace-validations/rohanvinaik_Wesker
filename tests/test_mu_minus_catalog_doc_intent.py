"""docs/MU_MINUS_CATALOG.md agrees with the catalog and the engine (#44).

THE RISK. The doc states, for each of Def. 11.8's 38 operators, whether it is generated, how, and
where. A reader trusts it over the code. A doc that drifts reads as a two-sign certificate covering
an operator the engine dropped, or omitting one it added. These checks make every drift-prone fact
in it a test:
- each operator's form, status and sub-modes;
- each Fork 2 mode's applicable types;
- the summary counts;
- every test it cites as evidence.
"""

from __future__ import annotations

import ast
import pathlib
import re
from collections import Counter

from Wesker.engine import _OUTPUT_TYPE_CONDITIONAL
from Wesker.mu_minus import MU_MINUS_CATALOG

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_DOC = (_ROOT / "docs" / "MU_MINUS_CATALOG.md").read_text()


def _section(title: str) -> str:
    start = _DOC.index(f"## {title}")
    nxt = _DOC.find("\n## ", start + 1)
    return _DOC[start : nxt if nxt != -1 else len(_DOC)]


def _rows(text: str) -> list[list[str]]:
    rows = []
    for line in text.splitlines():
        if line.startswith("|") and not line.startswith("|---"):
            rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return rows


def test_every_operator_row_is_the_catalogs():
    by_key = {op.key: op for op in MU_MINUS_CATALOG}
    seen: list[str] = []
    for cells in _rows(_section("Families")):
        if len(cells) != 5 or cells[0] not in by_key:
            continue
        key, form, status, modes, _applicability = cells
        op = by_key[key]
        listed = tuple(
            mode if ":" in mode or mode == "STMT" else f"OUTPUT:{mode}"
            for mode in re.findall(r"`([^`]+)`", modes)
        )
        assert (form, status, listed) == (op.form, op.status, op.modes), key
        seen.append(key)
    assert sorted(seen) == sorted(by_key), "each operator exactly once"


def test_the_fork_2_types_table_is_the_engine_table():
    table = {}
    for cells in _rows(_section("Fork 2 applicable types")):
        if len(cells) == 2 and cells[0].startswith("`"):
            table[cells[0].strip("`")] = [t.strip() for t in cells[1].split(",")]
    assert table == {
        mode: sorted(types) for mode, _desc, types in _OUTPUT_TYPE_CONDITIONAL
    }


def test_the_summary_counts_are_the_catalogs():
    counts = Counter(op.status for op in MU_MINUS_CATALOG)
    summary = {
        cells[0]: int(cells[1].split()[0]) for cells in _rows(_section("Summary"))[1:]
    }
    assert summary == {
        "built": counts["built"],
        "partial": counts["partial"],
        "realized by another operator": counts["realized_by"],
        "unsupported": counts["unsupported"],
    }


def test_every_cited_test_exists():
    cited = set(re.findall(r"tests/(test_\w+\.py)::(test_\w+)", _DOC))
    assert cited, "the evidence table cites tests"
    for filename, name in cited:
        tree = ast.parse((_ROOT / "tests" / filename).read_text())
        defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        assert name in defined, f"{filename}::{name}"
