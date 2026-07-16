"""The three refusals — the only reason this is a separate entry point from the CLI.

WHY THIS EXISTS: a badge is believed. A human who sees a suspicious 0% investigates; a README
badge that says 0% is simply read and accepted. So the action's job is not to always produce a
number — it is to never produce a WRONG one, and each gate below converts a state that would
yield a plausible-but-false reading into a loud failure carrying its own fix.

Every one of these was measured before it was written. The suite-health gate in particular
exists because a repo whose dependencies fail to install reports `spec 0%` — every test fails
on unmutated code, so no test can testify, so every mutant "survives". That is a statement
about a broken environment wearing the costume of a statement about the code, and it is the
likeliest way a first-time user gets a wrong number and (rightly) rejects the tool.
"""

from __future__ import annotations

from Wesker.action import gate_execution_mode, gate_suite_health, gate_truncation

_HEALTHY = {"tests": 100, "inert": 0, "failing_on_baseline": [], "trace_truncated": 0}


def test_a_pytest_live_run_passes_the_execution_gate():
    assert gate_execution_mode({"execution_mode": "pytest-live"}) is None


def test_the_legacy_runner_is_refused_rather_than_reported():
    """The legacy direct-call runner cannot execute fixture-taking tests, so its number is not
    comparable to a standards-compliant mutation score. Measured on a real fixture suite: the
    legacy path reported 100% where the live path reported 59%. A CI check must not be able to
    publish the first number, with or without a footnote."""
    reason = gate_execution_mode({"execution_mode": "legacy-direct-call"})

    assert reason is not None
    assert "legacy-direct-call" in reason
    assert "pytest" in reason


def test_an_unknown_execution_mode_is_refused_by_default():
    """Whitelist, not blacklist: a mode this gate has never heard of is refused, so adding a
    runner cannot silently open a hole here."""
    assert gate_execution_mode({}) is not None


def test_a_healthy_suite_passes_the_health_gate():
    assert gate_suite_health({"suite": _HEALTHY}) is None


def test_a_wholly_broken_suite_is_refused_instead_of_scoring_zero():
    """THE ONE THAT MATTERS. Every test failing on unmutated code is an unmet dependency, not
    an unspecified codebase — and the two are indistinguishable in the score."""
    reason = gate_suite_health({"suite": {**_HEALTHY, "tests": 40, "inert": 40}})

    assert reason is not None
    assert "40/40" in reason
    assert "unmutated" in reason.lower()


def test_the_gate_names_the_tests_that_fail_on_correct_code():
    """An assertion that fails against unmutated code is a WRONG EXPECTATION — nameable, and
    actionable by a human, so the refusal hands over the names rather than only a count."""
    reason = gate_suite_health(
        {
            "suite": {
                **_HEALTHY,
                "tests": 4,
                "inert": 4,
                "failing_on_baseline": ["test_wrong"],
            }
        }
    )

    assert reason is not None and "test_wrong" in reason


def test_a_minority_of_broken_tests_does_not_block_the_run():
    """A couple of failing tests is an ordinary repo, not a broken environment. Refusing here
    would make the tool useless in exactly the situation people most want to measure."""
    assert gate_suite_health({"suite": {**_HEALTHY, "tests": 100, "inert": 10}}) is None


def test_collecting_zero_tests_is_refused():
    """0% specified is technically true of a suiteless repo and useless as a published claim —
    there is nothing to measure specification AGAINST."""
    reason = gate_suite_health({"suite": {**_HEALTHY, "tests": 0, "inert": 0}})

    assert reason is not None and "0 tests" in reason


def test_a_report_without_suite_health_skips_the_gate():
    """No session baseline (no target files) means no reading — the gate must abstain rather
    than invent one."""
    assert gate_suite_health({}) is None


def test_an_untruncated_run_passes():
    assert gate_truncation({"total_truncated": 0}) is None


def test_a_truncated_run_is_refused_as_a_sample():
    """A budget-cut function's unevaluated mutants are missing from BOTH sides of the ratio, so
    the percentage is a sample of whatever was cheap to reach. The scheduled full run has no
    deadline, so there is never a good reason to badge one."""
    reason = gate_truncation({"total_truncated": 3})

    assert reason is not None
    assert "3 function(s)" in reason
    assert "sample" in reason
