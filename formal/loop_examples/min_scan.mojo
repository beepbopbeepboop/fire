# MIN SCAN.  The accumulator's update is `a[i]` — a SUBSCRIPT — so it is not a
# linear form in the loop's scalar variables and the accumulator loses its
# candidate, while the COUNTER keeps one: `6 - i`, with the `6` derived from the
# guard's bound rather than written down.  Measured: the variant's drop and its
# non-negativity are both proved, and the value is UNKNOWN with the subscript
# named — the invariant that would say more is a quantifier over the array and
# this layer's obligation language has no quantifier.
def min_scan(n):
    a = [7, 3, 9, 2, 8, 1]
    best = a[0]
    for i in range(1, 6):
        if a[i] < best:
            best = a[i]
    return best
