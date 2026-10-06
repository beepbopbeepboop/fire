# Operator precedence in one expression: `*` and `//` bind tighter than `+`,
# which binds tighter than the comparison. A lowering that evaluates left to
# right answers a different number.
def precedence(n):
    x = 1 + 2 * n - 4 // 2
    if x > 5:
        return x & 255
    return (0 - x) & 255
