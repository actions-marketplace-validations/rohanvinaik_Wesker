"""A pure-Python spin loop for the trace-budget tests — deliberately trivial and deliberately
scalable. `n` sets the work: small = a test that fits any budget, large = the computationally
heavy shape that made the unbudgeted traced baseline present as a hang. Kept in its own module
because the tracer keys on a frame's `co_filename`, so the target must live in a real file.
"""


def spin(n: int) -> int:
    total = 0
    for i in range(n):
        total += i
    return total
