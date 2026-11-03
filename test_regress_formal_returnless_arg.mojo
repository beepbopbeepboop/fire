# Regression for FORMAL_a_function_with_no_return_yields_a_word_where_cpython_yields_None
# The observation position (print of g) and returned position (return g) are refused,
# but consuming the value as an argument of an ordinary call must still build (doc §0d).

def g(a, b):
    w = 1

def h(a, b):
    return a + b

def main() -> Int32:
    # These build; argument position is deliberately out of scope (§0c / §0d)
    h(g(1, 2), 3)
    # Print/return of a return-less call are refused by the observation rule (§0b / §0e)
    return 0
