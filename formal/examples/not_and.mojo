# `not` applied to a parenthesised `and`: the negation of a two-operand
# short-circuit, so the flag the chain sets has to be read and inverted at the
# join.
def not_and(n):
    if not (n > 3 and n < 30):
        return 0
    return 1
