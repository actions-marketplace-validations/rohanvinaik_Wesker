"""Calibration corpus for Wesker's step budget (W#27): data-dependent loops of common shapes."""

from __future__ import annotations


def first_false(flags: list, start: int) -> int:
    """D#80: the index of the first False at or after start, or the end of the list."""
    i = max(start, 0)
    while i < len(flags) and flags[i]:
        i += 1
    return i


def reachable(graph: dict, start: str) -> list:
    """D#126 shape 1: a seen-set walk whose end depends on state the loop changes."""
    seen = set()
    stack = [start]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(graph.get(current, ()))
    return sorted(seen)


def prune_fixed_point(depends: dict, removed: set) -> set:
    """D#126 shape 2: grow `removed` until a pass removes nothing more."""
    removed = set(removed)
    read = {
        k for k, deps in depends.items() if k not in removed and set(deps) & removed
    }
    while read:
        removed |= read
        read = {
            k for k, deps in depends.items() if k not in removed and set(deps) & removed
        }
    return removed


def gcd(a: int, b: int) -> int:
    while b:
        a, b = b, a % b
    return abs(a)


def binary_search(xs: list, target: int) -> int:
    lo, hi = 0, len(xs) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if xs[mid] == target:
            return mid
        if xs[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1


def insertion_sort(xs: list) -> list:
    out = list(xs)
    for i in range(1, len(out)):
        key = out[i]
        j = i - 1
        while j >= 0 and out[j] > key:
            out[j + 1] = out[j]
            j -= 1
        out[j + 1] = key
    return out


def bubble_sort(xs: list) -> list:
    out = list(xs)
    n = len(out)
    for i in range(n):
        for j in range(n - i - 1):
            if out[j] > out[j + 1]:
                out[j], out[j + 1] = out[j + 1], out[j]
    return out


def sieve(n: int) -> list:
    if n < 2:
        return []
    is_prime = [True] * (n + 1)
    is_prime[0] = is_prime[1] = False
    i = 2
    while i * i <= n:
        if is_prime[i]:
            for j in range(i * i, n + 1, i):
                is_prime[j] = False
        i += 1
    return [k for k in range(n + 1) if is_prime[k]]


def collatz_steps(n: int) -> int:
    steps = 0
    while n != 1:
        n = n // 2 if n % 2 == 0 else 3 * n + 1
        steps += 1
    return steps


def digit_sum(n: int) -> int:
    n = abs(n)
    total = 0
    while n > 0:
        total += n % 10
        n //= 10
    return total


def power(base: int, exp: int) -> int:
    result = 1
    while exp > 0:
        if exp % 2 == 1:
            result *= base
        base *= base
        exp //= 2
    return result


def run_length(s: str) -> list:
    out = []
    i = 0
    while i < len(s):
        j = i
        while j < len(s) and s[j] == s[i]:
            j += 1
        out.append((s[i], j - i))
        i = j
    return out


def levenshtein(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[len(b)]


def merge_intervals(intervals: list) -> list:
    out = []
    for start, end in sorted(intervals):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def newton_sqrt(x: float) -> float:
    if x == 0:
        return 0.0
    guess = x
    while abs(guess * guess - x) > 1e-9 * x:
        guess = (guess + x / guess) / 2
    return guess


def word_count(text: str) -> int:
    count = 0
    i = 0
    n = len(text)
    while i < n:
        while i < n and text[i] == " ":
            i += 1
        if i < n:
            count += 1
        while i < n and text[i] != " ":
            i += 1
    return count


def kmp_prefix(pattern: str) -> list:
    pi = [0] * len(pattern)
    k = 0
    for q in range(1, len(pattern)):
        while k > 0 and pattern[k] != pattern[q]:
            k = pi[k - 1]
        if pattern[k] == pattern[q]:
            k += 1
        pi[q] = k
    return pi


def two_sum_sorted(xs: list, target: int) -> tuple:
    lo, hi = 0, len(xs) - 1
    while lo < hi:
        s = xs[lo] + xs[hi]
        if s == target:
            return (lo, hi)
        if s < target:
            lo += 1
        else:
            hi -= 1
    return (-1, -1)


def bisect_root(c: float) -> float:
    """The root of x**3 - c on [0, max(1, c)] by a fixed sixty halvings."""
    lo, hi = 0.0, max(1.0, c)
    for _ in range(60):
        mid = (lo + hi) / 2
        if mid * mid * mid < c:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def mat_mult(a: list, b: list) -> list:
    rows, inner, cols = len(a), len(b), len(b[0])
    out = [[0] * cols for _ in range(rows)]
    for i in range(rows):
        for j in range(cols):
            total = 0
            for k in range(inner):
                total += a[i][k] * b[k][j]
            out[i][j] = total
    return out


def flatten(nested: list) -> list:
    out = []
    stack = [iter(nested)]
    while stack:
        for item in stack[-1]:
            if isinstance(item, list):
                stack.append(iter(item))
                break
            out.append(item)
        else:
            stack.pop()
    return out


def lcs_length(a: str, b: str) -> int:
    table = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                table[i][j] = table[i - 1][j - 1] + 1
            else:
                table[i][j] = max(table[i - 1][j], table[i][j - 1])
    return table[len(a)][len(b)]


def primes_below(n: int) -> list:
    out = []
    for cand in range(2, n):
        d = 2
        prime = True
        while d * d <= cand:
            if cand % d == 0:
                prime = False
                break
            d += 1
        if prime:
            out.append(cand)
    return out


def chunk_sums(xs: list, size: int) -> list:
    out = []
    i = 0
    while i < len(xs):
        out.append(sum(xs[i : i + size]))
        i += size
    return out


def count_set_bits(n: int) -> int:
    count = 0
    while n:
        n &= n - 1
        count += 1
    return count


def bit_length(n: int) -> int:
    """A halving loop: its ``//`` -> ``/`` mutant runs the float-underflow tail and terminates."""
    count = 0
    while n > 0:
        n //= 2
        count += 1
    return count
