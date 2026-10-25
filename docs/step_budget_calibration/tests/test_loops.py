import loops


def test_first_false():
    assert loops.first_false([True, True, False], 0) == 2
    assert loops.first_false([True] * 40 + [False], 3) == 40
    assert loops.first_false([True] * 25, 0) == 25


def test_reachable():
    graph = {f"n{i}": [f"n{i + 1}", f"n{(i * 7) % 60}"] for i in range(60)}
    assert loops.reachable(graph, "n0")[:3] == ["n0", "n1", "n10"]
    assert len(loops.reachable(graph, "n0")) == 61
    assert loops.reachable({"a": ["b"], "b": ["a"]}, "a") == ["a", "b"]


def test_prune_fixed_point():
    depends = {f"m{i}": [f"m{i - 1}"] for i in range(1, 40)}
    assert loops.prune_fixed_point(depends, {"m0"}) == {f"m{i}" for i in range(40)}
    assert loops.prune_fixed_point({"x": ["y"]}, set()) == set()


def test_gcd():
    assert loops.gcd(1071, 462) == 21
    assert loops.gcd(832040, 514229) == 1
    assert loops.gcd(-48, 18) == 6


def test_binary_search():
    xs = list(range(0, 4000, 3))
    assert loops.binary_search(xs, 2997) == 999
    assert loops.binary_search(xs, 2998) == -1
    assert loops.binary_search(xs, 0) == 0


def test_insertion_sort():
    xs = [(i * 37) % 101 for i in range(120)]
    assert loops.insertion_sort(xs) == sorted(xs)
    assert loops.insertion_sort([3, 1, 2]) == [1, 2, 3]


def test_bubble_sort():
    xs = [(i * 53) % 97 for i in range(70)]
    assert loops.bubble_sort(xs) == sorted(xs)


def test_sieve():
    primes = loops.sieve(3000)
    assert len(primes) == 430
    assert primes[-1] == 2999
    assert loops.sieve(1) == []


def test_collatz_steps():
    assert loops.collatz_steps(27) == 111
    assert loops.collatz_steps(97) == 118
    assert loops.collatz_steps(1) == 0


def test_digit_sum():
    assert loops.digit_sum(98765432123456789) == 89
    assert loops.digit_sum(-405) == 9


def test_power():
    assert loops.power(3, 200) == 3**200
    assert loops.power(7, 0) == 1
    assert loops.power(2, 63) == 2**63


def test_run_length():
    s = "a" * 30 + "b" * 7 + "c" + "a" * 12
    assert loops.run_length(s) == [("a", 30), ("b", 7), ("c", 1), ("a", 12)]


def test_levenshtein():
    assert loops.levenshtein("kitten sitting on", "sitting kitten in") == 7
    assert loops.levenshtein("", "abc") == 3


def test_merge_intervals():
    ivs = [(i * 5, i * 5 + 7) for i in range(80)] + [(1000, 1001)]
    assert loops.merge_intervals(ivs) == [(0, 402), (1000, 1001)]


def test_newton_sqrt():
    assert abs(loops.newton_sqrt(2.0) - 1.4142135623730951) < 1e-8
    assert abs(loops.newton_sqrt(1e6) - 1000.0) < 1e-6
    assert loops.newton_sqrt(0) == 0.0


def test_word_count():
    assert loops.word_count("  the quick  brown fox   jumps over the lazy dog ") == 9
    assert loops.word_count("") == 0


def test_kmp_prefix():
    assert loops.kmp_prefix("abacabadabacaba") == [
        0,
        0,
        1,
        0,
        1,
        2,
        3,
        0,
        1,
        2,
        3,
        4,
        5,
        6,
        7,
    ]
    assert loops.kmp_prefix("aaaa") == [0, 1, 2, 3]


def test_two_sum_sorted():
    xs = list(range(0, 900, 2))
    assert loops.two_sum_sorted(xs, 1000) == (51, 449)
    assert loops.two_sum_sorted(xs, 3) == (-1, -1)


def test_bisect_root():
    assert abs(loops.bisect_root(27.0) - 3.0) < 1e-9
    assert abs(loops.bisect_root(0.5) - 0.7937005259840998) < 1e-9


def test_mat_mult():
    a = [[i + j for j in range(9)] for i in range(9)]
    b = [[i * j % 5 for j in range(9)] for i in range(9)]
    out = loops.mat_mult(a, b)
    assert out[3][4] == sum(a[3][k] * b[k][4] for k in range(9))
    assert out[8][8] == sum(a[8][k] * b[k][8] for k in range(9))


def test_flatten():
    nested = [1, [2, [3, [4, [5, 6]], 7], 8], [[9]], 10]
    assert loops.flatten(nested) == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]


def test_lcs_length():
    assert loops.lcs_length("AGGTABQRSTUV", "GXTXAYBQRZTUV") == 9
    assert loops.lcs_length("", "abc") == 0


def test_primes_below():
    assert loops.primes_below(400)[-3:] == [383, 389, 397]
    assert len(loops.primes_below(400)) == 78


def test_chunk_sums():
    assert loops.chunk_sums(list(range(100)), 7)[:3] == [21, 70, 119]
    assert len(loops.chunk_sums(list(range(100)), 7)) == 15


def test_count_set_bits():
    assert loops.count_set_bits(2**60 - 1) == 60
    assert loops.count_set_bits(0b1011_0110_1110) == 8


def test_bit_length():
    assert loops.bit_length(1000) == 10
    assert loops.bit_length(2**40) == 41
    assert loops.bit_length(0) == 0
