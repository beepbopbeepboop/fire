# COUNT ACCUMULATOR.  The shape the whole layer exists for: `for i in range(n)`
# with one accumulator stepped by 1, whose value at the end is therefore `n`.
# Measured: synthesised invariant `c - i = 0`, variant `n - i` (drop 1), exit
# consequence `c = n`, under the SYNTHESISED PRECONDITION `0 <= n` — and every
# one of those five obligations is closed by Lean.  The precondition is not
# decoration: `count_acc(-1)` is 0, not -1, so a theorem without it would be
# false.
def count_acc(n):
    c = 0
    for i in range(n):
        c = c + 1
    return c
