# ARRAY FILL.  The body stores a LITERAL through a subscript, and the loop's own
# test is `i != 4` — an EQUALITY, which bounds nothing.  Measured: the only
# decreasing affine functional is `- i`, and `var-nonneg` asks Lean to prove
# `i <= 0` together with `i != 4` gives `i + 1 <= 0`, which is FALSE and which
# omega refutes.  That is the finding: `while i != 4: i = i + 1` is not provably
# terminating, and the obligation that says so is the reason this corpus has one.
def array_fill(n):
    a = [0, 0, 0, 0]
    i = 0
    while i != 4:
        a[i] = 6
        i = i + 1
    return a[0] + a[1] + a[2] + a[3]
