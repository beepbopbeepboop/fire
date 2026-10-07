# SUM ACCUMULATOR.  The accumulator is stepped by the COUNTER, so the closed
# form is n(n-1)/2 — quadratic, and therefore outside this layer's deliberately
# LINEAR arithmetic.  Measured: NO affine invariant exists (the (total, i) block
# of A is [[1,1],[0,1]], whose only eigenvector for 1 has c.b = 1 > 0), the
# variant `n - i` is synthesised and PROVED, and the value is UNKNOWN with that
# reason.  This is the corpus's honest partial row.
def sum_acc(n):
    total = 0
    for i in range(n):
        total += i
    return total
