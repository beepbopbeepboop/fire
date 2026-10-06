# The unary operators in one function: negation on an expression (not only on
# a literal), bitwise `not`, and unary plus.
def unary_ops(n):
    a = 0 - n
    b = ~n
    c = +n
    return (a + b + c) & 255
