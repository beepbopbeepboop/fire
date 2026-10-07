# COLLATZ.  The body HALVES a variable in one branch and TRIPLES it in the
# other, and `//` is not a linear form, so the decreasing variable `v` is outside
# the relation in both.  What remains is `steps`, which INCREASES, and the
# synthesised variant is `- steps` — strictly decreasing by 1 and provably so,
# with a non-negativity nothing establishes.  Measured: the drop is proved, the
# non-negativity is UNKNOWN, and the value is UNKNOWN.  Collatz terminates, and
# this layer cannot say why in a form it can check.
def collatz(n):
    v = n
    steps = 0
    while v != 1:
        if v % 2 == 0:
            v = v // 2
        else:
            v = 3 * v + 1
        steps = steps + 1
    return steps
