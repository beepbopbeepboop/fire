# `abs` in a clause.  The postcondition is stated with `abs` and the body
# computes it by hand, so the contract and the body are two INDEPENDENT
# statements about the same value -- which is the point: a clause written by
# restating the body's own expression checks nothing, and this one does not.
#
# `@requires(n >= 0)` is load-bearing.  Without it the clause is FALSE: `abs` of
# a negative `UInt64` read as signed can be `2^63`, whose sign bit is set, so
# `abs(INT64_MIN) < 0`.  The precondition is what makes the promise true, and
# dropping it turns a proved contract into a refuted one.
@requires(n >= 0)
@ensures(result == abs(n))
def abspos(n):
    if n > 0:
        return n
    else:
        return 0 - n
