"""Small-iteration cases: the regime the step budget's floor exists for (originals of 0-3 iterations)."""

import loops


def test_first_false_small():
    assert loops.first_false([False], 0) == 0
    assert loops.first_false([], 0) == 0
    assert loops.first_false([True], 0) == 1


def test_reachable_small():
    assert loops.reachable({}, "a") == ["a"]
    assert loops.reachable({"a": ["b"]}, "a") == ["a", "b"]


def test_prune_small():
    assert loops.prune_fixed_point({"x": ["y"]}, {"y"}) == {"x", "y"}
    assert loops.prune_fixed_point({}, {"z"}) == {"z"}


def test_gcd_small():
    assert loops.gcd(7, 0) == 7
    assert loops.gcd(0, 5) == 5
    assert loops.gcd(6, 3) == 3


def test_binary_search_small():
    assert loops.binary_search([], 1) == -1
    assert loops.binary_search([4], 4) == 0
    assert loops.binary_search([1, 3], 3) == 1


def test_insertion_sort_small():
    assert loops.insertion_sort([]) == []
    assert loops.insertion_sort([2, 1]) == [1, 2]


def test_bubble_sort_small():
    assert loops.bubble_sort([1]) == [1]
    assert loops.bubble_sort([2, 1]) == [1, 2]


def test_sieve_small():
    assert loops.sieve(2) == [2]
    assert loops.sieve(10) == [2, 3, 5, 7]


def test_collatz_small():
    assert loops.collatz_steps(2) == 1
    assert loops.collatz_steps(4) == 2


def test_digit_sum_small():
    assert loops.digit_sum(0) == 0
    assert loops.digit_sum(7) == 7
    assert loops.digit_sum(19) == 10


def test_power_small():
    assert loops.power(5, 1) == 5
    assert loops.power(3, 2) == 9


def test_run_length_small():
    assert loops.run_length("") == []
    assert loops.run_length("a") == [("a", 1)]
    assert loops.run_length("ab") == [("a", 1), ("b", 1)]


def test_levenshtein_small():
    assert loops.levenshtein("a", "") == 1
    assert loops.levenshtein("a", "b") == 1


def test_newton_small():
    assert abs(loops.newton_sqrt(1.0) - 1.0) < 1e-9
    assert abs(loops.newton_sqrt(4.0) - 2.0) < 1e-9


def test_word_count_small():
    assert loops.word_count("a") == 1
    assert loops.word_count(" ") == 0


def test_kmp_small():
    assert loops.kmp_prefix("a") == [0]
    assert loops.kmp_prefix("ab") == [0, 0]


def test_two_sum_small():
    assert loops.two_sum_sorted([1, 2], 3) == (0, 1)
    assert loops.two_sum_sorted([5], 5) == (-1, -1)


def test_flatten_small():
    assert loops.flatten([]) == []
    assert loops.flatten([[1]]) == [1]


def test_lcs_small():
    assert loops.lcs_length("a", "a") == 1
    assert loops.lcs_length("ab", "b") == 1


def test_primes_small():
    assert loops.primes_below(3) == [2]
    assert loops.primes_below(6) == [2, 3, 5]


def test_chunk_small():
    assert loops.chunk_sums([], 3) == []
    assert loops.chunk_sums([1, 2], 3) == [3]


def test_bits_small():
    assert loops.count_set_bits(0) == 0
    assert loops.count_set_bits(1) == 1
    assert loops.count_set_bits(6) == 2


def test_merge_small():
    assert loops.merge_intervals([]) == []
    assert loops.merge_intervals([(1, 2), (2, 3)]) == [(1, 3)]


def test_mat_small():
    assert loops.mat_mult([[2]], [[3]]) == [[6]]


def test_bisect_small():
    assert abs(loops.bisect_root(1.0) - 1.0) < 1e-9


def test_bit_length_small():
    assert loops.bit_length(1) == 1
    assert loops.bit_length(3) == 2
