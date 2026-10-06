# A negated expression passed as an ARGUMENT, so the negation happens in the
# caller's frame and the callee receives the result: the operand order at a
# call site, with a unary on top.
def negate_arg(a):
    return a + 1


def negate_arg_caller(n):
    return negate_arg(0 - n)
