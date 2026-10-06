# A DECREASING MEASURE THAT IS NOT A VARIANT, which is the row that says a
# decreasing measure is necessary and not sufficient.  The body steps `i` down by
# 2, so `i` strictly decreases, and the synthesised invariant `i + 2*s = n` is
# exact and proved.  But `i` leaves the loop at -1 when `n` is odd, so the
# variant's NON-NEGATIVITY obligation is FALSE and omega refutes it: no linear
# functional of (n, i, s) is both strictly decreasing and non-negative here, and
# `s = (n - i)/2` is not the loop's answer either.  UNKNOWN, with both reasons.
def dec_measure(n):
    i = n
    s = 0
    while i > 0:
        s = s + 1
        i = i - 2
    return s
