# `//` and `%` where the two agree that a truncating divide is wrong: the
# operands' SIGNS differ, or the division is inexact with a negative dividend.
# The proof-side counterpart of `test_formal_run.py`'s
# `both_arch_floor_division_and_modulo_agree_with_cpython` — that case is the
# runtime measurement, this one is what a generated proof has to close over.
#
# Every divisor here is a LITERAL, and that is deliberate rather than incidental.
# `fdiv64`/`sdiv64` both carry `if b = 0 then 0 else …` — the model's answer for
# a zero divisor, which the machine matches by writing 0 and trapping before
# the divide — and the walk's terminal value flow runs only on the path where
# the divisor is NOT zero, so with a symbolic `b` that guard has nothing to
# discharge it and the goal needs a fact the generator does not emit. That hole
# predates this file (`formal/examples/udivmod.mojo` is why nobody hit it: its
# divisor is `7`) and it is
# `bugs/FORMAL_a_division_by_a_symbolic_value_leaves_the_zero_guard_open.md`.
#
# CPython 3.14 answers, written out rather than computed, because a proof
# example whose expectation comes from the generator proves whatever the
# generator says:
#
#     7 // (0 - 2)  == -4      # a positive dividend over a negative divisor
#     (0 - 7) // 2  == -4      # the truncating answer is -3
#     1 // 2        ==  0      # the ordinary inexact case, and the FIRST thing
#                              # a correction written as `sKey a = sKey b`
#                              # breaks, since `sKey` is an involution and that
#                              # condition is `a = b`
#     (0 - 7) // (0 - 2) == 3  # the signs AGREE and it is still not -3
#     (0 - 8) // 2  == -4      # exact, so no correction
#
#     (0 - 7) % 2   ==  1      # the standard ODD test, which answered 0 for
#                              # every negative odd value
#     7 % (0 - 3)   == -2      # the sign of the DIVISOR, not the dividend
#     (0 - 7) % (0 - 3) == -1
#     7 % 3         ==  1
#
# `/` is on the last line and is NOT the same operator: it stays a truncating
# integer divide, because this model has no float and `7 / (0 - 2)` is -3
# rather than CPython's -3.5 (`FORMAL.md` §6 Phase 7). A file that used `//`
# where it meant `/` would pass this example and fail the run suite, which is
# why the two are on adjacent lines rather than mixed.
def floors():
    return (7 // (0 - 2)) + ((0 - 7) // 2) + (1 // 2) \
        + ((0 - 7) // (0 - 2)) + ((0 - 8) // 2)


def moduli():
    return ((0 - 7) % 2) + (7 % (0 - 3)) + ((0 - 7) % (0 - 3)) + (7 % 3)


def truncating_slash_still_truncates():
    return 7 / (0 - 2)


def remainder_is_inside_the_divisor():
    # `x % 2 == 1` is the standard ODD test, and a program that spells it that
    # way needs a conditional — which lowers to `CSEL`, unmodelled
    # (`bugs/FORMAL_arm64_csel_is_not_modelled_so_the_step_table_cannot_claim_it.md`),
    # so this example states the test's arithmetic instead: for every negative
    # odd `x`, `x % 2 - 1` is 0 and `x % 2` is 1 where a truncating remainder
    # would give -1 and the test would answer "even".
    return (((0 - 7) % 2) - 1) + ((0 - 9) % 2) + ((0 - 7) % 4)