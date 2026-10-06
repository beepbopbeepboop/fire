# BOUNDS-CHECKED INDEXING, written as the PROMISE that makes indexing safe.
#
# On this target every value is one word, so there is no container to index and
# the contract cannot mention `xs[i]`.  What it CAN carry is the bound indexing
# needs, which is the part a reader gets wrong: `i < n` is a claim about `i`,
# and a function handed an `i` with no such claim has no way to say where the
# bound came from.
#
# BOTH bounds are written, and the second one is not decoration.  `i < n` alone
# is satisfied by `i = -1, n = 0`, because the compiler reads a comparison
# SIGNED: measured here, `@requires(i < n) @ensures(result >= i)` on `i + i` is
# REFUTED at `i = -1`, where `-1 < 0` holds and `-2 >= -1` does not.  A bound
# written without its non-negativity half is a bound on the wrong order.
@requires(i >= 0)
@requires(i < n)
@ensures(result <= n)
def at_offset(i, n):
    return i
