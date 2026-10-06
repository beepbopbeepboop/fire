# The augmented forms the corpus does not have: `//=` and `%=` write through
# the same compound-assign path as `+=`, and each one emits a divide with its
# own correction block.
def augassign_floordiv(n):
    a = n
    a //= 3
    a %= 7
    return a
