# `//` FLOORS and `%` takes the sign of the divisor, and both of those are the
# floor CORRECTION rather than the divide: on a signed operand the emitted block
# is SDIV followed by EOR/CMP/CSET/CMP/CSET/AND and then either a SUB (for `//`)
# or a second SUB plus an MSUB (for `%`).  `udivmod.mojo` exercises `%` and the
# truncating `/`, so before this example existed nothing in the corpus proved the
# `//` correction's residual goal — the half of the fix with no proving case.
def floordiv(n):
    return (n // 7) + (n % 7)
