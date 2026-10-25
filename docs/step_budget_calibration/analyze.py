"""Summarise step-budget calibration logs (W#27) into the tables of STEP_BUDGET_CALIBRATION_2026-10-25.

Usage: python analyze.py LOG.jsonl [LOG.jsonl ...]

A TERMINATING observation is one where the original passed the test under the count and the mutant
then finished inside the wall: an assertion kill, a crash kill or a survival. Only those can tell
how far a mutant that ends goes; a wall-bound row ended nothing and is reported separately.
"""

import json
import sys

UNFINISHED = ("undetermined", "uncontained", "diverged")
BUCKETS = ((0, 0), (1, 10), (11, 100), (101, 1000), (1001, 10_000), (10_001, None))
CANDIDATES = (
    (16, 2000),
    (16, 5000),
    (32, 2000),
    (32, 5000),
    (32, 10_000),
    (64, 10_000),
)


def load(paths):
    rows = []
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            rows.extend(json.loads(line) for line in fh if line.strip())
    return rows


def ratio(r):
    return r["mutant_iterations"] / max(r["original_iterations"], 1)


def main(paths):
    rows = load(paths)
    term = [
        r
        for r in rows
        if r["original"] == "passed"
        and r["mutant_iterations"] is not None
        and r["result"] not in UNFINISHED
    ]
    fns = {(r["source"], r["qualname"]) for r in term}
    print(f"rows {len(rows)}; terminating {len(term)}; functions {len(fns)}")

    print("\noriginal count | obs | max mutant count | max ratio | binding observation")
    for lo, hi in BUCKETS:
        b = [
            r
            for r in term
            if r["original_iterations"] >= lo
            and (hi is None or r["original_iterations"] <= hi)
        ]
        if not b:
            print(f"{lo}..{hi or ''} | 0 | - | - | -")
            continue
        top = max(b, key=ratio)
        print(
            f"{lo}..{hi or ''} | {len(b)} | {max(r['mutant_iterations'] for r in b)} | "
            f"{ratio(top):.2f} | {top['qualname']} {top['original_iterations']} -> "
            f"{top['mutant_iterations']} ({top['description'].split(': ', 1)[-1]})"
        )

    print("\nk | F | terminating misfiled | tightest cap/count | binding observation")
    for k, f in CANDIDATES:
        misfiled = 0
        worst = None
        for r in term:
            cap = k * max(r["original_iterations"], 0) + f
            misfiled += r["mutant_iterations"] > cap
            if r["mutant_iterations"] and (
                worst is None or cap / r["mutant_iterations"] < worst[0]
            ):
                worst = (cap / r["mutant_iterations"], r)
        margin, r = worst
        print(
            f"{k} | {f} | {misfiled} | {margin:.2f}x | {r['qualname']} "
            f"{r['original_iterations']} -> {r['mutant_iterations']}"
        )

    walled = [r for r in rows if r["result"] in ("undetermined", "uncontained")]
    rates = sorted(
        1000.0 * r["mutant_ms"] / r["mutant_iterations"]
        for r in walled
        if (r["mutant_iterations"] or 0) >= 1000
    )
    slow = sorted(
        {r["qualname"] for r in walled if (r["mutant_iterations"] or 0) < 1000}
    )
    print(
        f"\nwall-bound rows {len(walled)}; with >= 1000 counted iterations {len(rates)}"
    )
    if rates:
        p50, p90 = rates[len(rates) // 2], rates[int(0.9 * len(rates))]
        print(
            f"us per counted iteration: p50 {p50:.3f}  p90 {p90:.3f}  max {rates[-1]:.3f}"
        )
    print(f"wall-bound with < 1000 counted iterations (not count-catchable): {slow}")


if __name__ == "__main__":
    main(sys.argv[1:])
