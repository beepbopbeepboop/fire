# DECREASING MEASURE, spelled `while i < n`.  The accumulator is stepped by the
# counter, so like `sum_acc` there is no affine invariant; the variant `n - i` is
# synthesised, its drop of 1 per iteration is proved from the body's equations
# alone, and its non-negativity is proved from the guard.
def while_lt_acc(n):
    i = 0
    total = 0
    while i < n:
        total = total + i
        i = i + 1
    return total
