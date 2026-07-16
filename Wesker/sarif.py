"""SARIF 2.1.0 output — the survivors, as a machine's work queue.

WHY THIS EXISTS: a kill rate is a score, and a score is something you look at once. A SURVIVOR
is a task: this line, this behavioral dimension, no test pins it. SARIF is how that task reaches
the places engineers already look — GitHub code scanning renders it inline in the diff and in the
Security tab, and every tool that reads code-scanning alerts can consume it from there.

The distinction that makes this worth emitting: a linter reports an OPINION ("this looks wrong"),
so a tool acting on it is guessing at intent. Wesker reports a PROOF OBLIGATION — no test
distinguishes the original from this specific mutant — and it ships with its own acceptance test.
Write a test that kills the mutant and the obligation is discharged, verifiably, by re-running.
Nothing in that loop is an inference.

Zero dependencies: SARIF is JSON, and this module builds a dict. Nothing here imports the engine,
so it stays cheap to load and trivial to test.
"""

from __future__ import annotations

from typing import Any

SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
SARIF_VERSION = "2.1.0"
INFORMATION_URI = "https://github.com/rohanvinaik/Wesker"

# One rule per mutation category, so results are filterable by the KIND of behavior left
# unspecified. Keyed by the category string the engine reports rather than by importing its enum:
# this module is meant to stay loadable without the engine, and an unknown category degrades to a
# generic rule instead of raising — a new operator must never break the report.
_RULE_HELP: dict[str, str] = {
    "VALUE": "A constant can be replaced without any test noticing.",
    "BOUNDARY": "A comparison's boundary can shift without any test noticing — the classic "
    "off-by-one lives here.",
    "ARITHMETIC": "An arithmetic operator can be swapped without any test noticing.",
    "LOGICAL": "A logical operator or branch condition can be inverted without any test noticing.",
    "SWAP": "Two operands or arguments can be exchanged without any test noticing.",
    "STATE": "A mutation to state or an attribute assignment goes unnoticed by every test.",
    "TYPE": "A type-level substitution goes unnoticed by every test.",
    "STMT": "A statement can be deleted entirely without any test noticing — the code may be "
    "dead, or its effect may simply be unasserted.",
    "EXCEPTION": "An exception's type, or whether it is raised or swallowed at all, is not "
    "pinned by any test.",
}
_GENERIC_HELP = "A mutation in this category goes unnoticed by every test."


def rule_id(category: str) -> str:
    """Stable SARIF rule id for a mutation category."""
    return f"wesker/{category.lower()}" if category else "wesker/unspecified"


def _rule(category: str) -> dict[str, Any]:
    help_text = _RULE_HELP.get(category, _GENERIC_HELP)
    return {
        "id": rule_id(category),
        "name": f"Unspecified{category.title().replace('_', '')}Behavior",
        "shortDescription": {
            "text": f"{category or 'Unspecified'} behavior is not specified"
        },
        "fullDescription": {"text": help_text},
        "help": {
            "text": help_text,
            "markdown": (
                f"**{help_text}**\n\n"
                "Wesker changed the code and every test still passed, so this behavior is "
                "not pinned by the suite. That is a *proof obligation*, not a style opinion: "
                "write a test that fails against the change and it is discharged.\n\n"
                "Detective can synthesize that test for you:\n\n"
                "```\npipx run detective-spec converge <file>::<function>\n```\n"
            ),
        },
        "defaultConfiguration": {"level": "warning"},
        "properties": {"tags": ["specification", "mutation-testing", "wesker"]},
    }


def _message(survivor: dict) -> str:
    """The line an engineer actually reads.

    Prefers the CONCRETE change (``n >= 10 → n > 10``) over the category description
    ("off-by-one comparison"): the first is a fact about this line that can be checked by
    looking at it, the second is a taxonomy. Falls back to the description when the engine
    could not reduce the edit to a single line, and names the dimension either way.
    """
    change = (survivor.get("change") or "").strip()
    if change:
        head = f"No test distinguishes `{change}` here"
    else:
        described = survivor.get("mutant", "")
        # Descriptions arrive as "ARITHMETIC_c537e5ab: replace arithmetic operator" — the id
        # prefix is bookkeeping and only adds noise in a diff annotation.
        if ": " in described:
            described = described.split(": ", 1)[1]
        head = f"No test notices this change: {described}"

    dimension = survivor.get("dimension") or ""
    dim_note = (
        f" The behavioral dimension `{dimension}` is unspecified." if dimension else ""
    )
    return f"{head}.{dim_note}"


def _location(survivor: dict) -> dict[str, Any]:
    """File always; line only when the mutator reported one.

    A survivor whose line is unknown is reported AT ITS FILE rather than dropped or pinned to a
    guessed line: an imprecise true location beats both a silent omission and a confident lie.
    """
    uri = str(survivor.get("function_key", "")).split("::", 1)[0]
    physical: dict[str, Any] = {"artifactLocation": {"uri": uri}}
    line = survivor.get("mutated_line")
    if isinstance(line, int) and line > 0:
        physical["region"] = {"startLine": line}
    return {"physicalLocation": physical}


def _result(survivor: dict) -> dict[str, Any]:
    category = str(survivor.get("category", ""))
    result: dict[str, Any] = {
        "ruleId": rule_id(category),
        "level": "warning",
        "message": {"text": _message(survivor)},
        "locations": [_location(survivor)],
    }
    # ``mutant_id`` is content-addressed and invocation-stable, so it is exactly what SARIF
    # wants for fingerprinting: the same unspecified dimension keeps one alert identity across
    # runs instead of being closed and reopened on every push.
    mutant_id = survivor.get("mutant_id")
    if mutant_id:
        result["partialFingerprints"] = {"weskerMutantId/v1": str(mutant_id)}
    return result


def to_sarif(report: dict, *, version: str = "") -> dict[str, Any]:
    """Render a codebase-level mutation report as a SARIF 2.1.0 log.

    ``report`` is the dict returned by ``profile_codebase``/``profile_codebase_live`` — the
    ``survivors`` list is the only key read, so a report without survivors renders a valid,
    empty run rather than failing. An empty run is meaningful: it is how a clean result is
    reported, and code scanning uses it to resolve alerts that no longer apply.
    """
    survivors = report.get("survivors") or []
    categories = sorted({str(s.get("category", "")) for s in survivors})
    driver: dict[str, Any] = {
        "name": "Wesker",
        "informationUri": INFORMATION_URI,
        "rules": [_rule(c) for c in categories],
    }
    if version:
        driver["version"] = version
    return {
        "$schema": SCHEMA,
        "version": SARIF_VERSION,
        "runs": [
            {
                "tool": {"driver": driver},
                "results": [_result(s) for s in survivors],
            }
        ],
    }
