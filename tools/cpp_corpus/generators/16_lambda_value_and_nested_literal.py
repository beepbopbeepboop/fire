"""A lambda expression used as a value in a generator (`_cpx_lambda_expr`'s closure forms) and a nested
literal (`_cpp_boxed_list_literal_expr`): a tuple inside a list is stored boxed.
"""


def apply(n: int):
    k = 3
    g = lambda v: v + k
    pairs = [(1, 2), (3, 4)]
    for i in range(n):
        yield g(i)
        yield len(pairs) + i


def main():
    for v in apply(3):
        print(v)


main()
