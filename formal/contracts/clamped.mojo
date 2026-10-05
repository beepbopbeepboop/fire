# `clamp` in a clause, with THREE postconditions over one contract: the bound
# is a conjunction and each half is separately checkable, so a partial failure
# says which half broke.
@requires(lo <= hi)
@ensures(result >= lo)
@ensures(result <= hi)
@ensures(result == clamp(n, lo, hi))
def clamped(n, lo, hi):
    if n < lo:
        return lo
    else:
        if n > hi:
            return hi
        else:
            return n
