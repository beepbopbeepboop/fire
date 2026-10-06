# A shift by a VARIABLE amount, in both directions: the variable-shift form has
# a register amount, and the two directions differ in whether carry-in matters.
def shift_by_var(n):
    a = n << 2
    b = a >> 1
    return b & 255
