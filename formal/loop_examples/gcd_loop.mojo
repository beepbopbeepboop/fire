# GCD, the textbook DECREASING-MEASURE loop: `x + y` strictly falls, using
# `x mod y < y`.  Measured: NO candidate at all.  The body assigns `t = x % y`,
# and `%` is not a linear form, so `t` is outside the relation; `y = t` then
# reads a name whose value on this path is not a linear form, so `y` is outside
# it too, and `x = y` with `y` outside leaves nothing decreasing.  The report
# names the store — the missing ingredient is `x mod y < y`, a theorem about
# `Int.Mod` that this layer's arithmetic does not have.
def gcd_loop(a, b):
    x = a
    y = b
    while y != 0:
        t = x % y
        x = y
        y = t
    return x
