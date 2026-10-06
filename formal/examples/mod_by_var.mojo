# `%` by a VARIABLE divisor rather than a literal: the divisor is a word the
# program computed, so the divide block has a register operand.
def mod_by_var(n):
    d = 4
    return n % d
