# THE NEGATIVE CONTROL.  `@ensures(result <= hi)` is FALSE for this clamp,
# because `n` is a `UInt64` and the SIGNED reading the compiler uses makes
# `0 - n` negative for a negative `n` -- so the "lower bound" arm of the
# clamp returns a number BELOW `lo`.
#
# This file exists so the checker is measured against a contract that is wrong.
# A test suite of contracts that all hold measures nothing: the four bugs
# `lib/Contracts.lean`'s docstring lists are all claims that were believed
# because nothing tried to refute them.
@requires(lo <= hi)
@ensures(result >= lo)
@ensures(result <= hi)
def wrong_clampv(n, lo, hi):
    if n > hi:
        return hi
    else:
        if n < lo:
            return 0 - n
        else:
            return n
