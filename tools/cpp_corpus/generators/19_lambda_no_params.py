"""A zero-parameter lambda used as a value inside a generator: the no-parameter closure of
`_cpx_lambda_expr`, cast to the callable type.
"""


def constant(n: int):
    k = 5
    get = lambda: k
    for i in range(n):
        yield get() + i


def main():
    for v in constant(3):
        print(v)


main()
