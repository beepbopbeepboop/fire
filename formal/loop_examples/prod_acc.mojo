# PRODUCT ACCUMULATOR.  The accumulator's update is a product of two
# non-constant factors, so the accumulator is not affine in the loop's variables
# and no candidate may mention it.  Measured: the variant `n - i` is synthesised
# and PROVED — the loop's INDEX is bounded and terminates — and the value is
# UNKNOWN, and the `& 255` on the return is the second reason: a bitwise `and` is
# not a linear form either.
def prod_acc(n):
    acc = 1
    for i in range(n):
        acc = acc * (i + 2)
    return acc & 255
