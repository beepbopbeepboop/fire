# Linear recursion with an accumulator: one call site, reached with a smaller
# argument every time. The corpus's recursive programs all fan out to two
# calls, so this is the single-successor shape.
def down(n):
    if n == 0:
        return 0
    return down(n - 1) + 1


def recursion_linear(n):
    return down(n) + down(n)
