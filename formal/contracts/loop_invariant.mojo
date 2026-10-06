# A LOOP INVARIANT, written as the `assert` that states it.
#
# `assert` is not a contract and this file does not pretend it is one: it is a
# check at ONE point in the run, and `--check-contracts` is what turns the
# entry-and-return clauses above into the same kind of check.  What the two
# share is the discipline -- the invariant is written down where it can be
# checked, and a run that violates it stops rather than continuing.
#
# The loop's invariant is `total == i * (i - 1) / 2`, and it is asserted at the
# TOP of the body where it is true for the first iteration (i = 0, total = 0).
def sum_to(n):
    total = 0
    i = 0
    while i < n:
        assert i >= 0
        assert total >= 0
        total = total + i
        i = i + 1
    return total
