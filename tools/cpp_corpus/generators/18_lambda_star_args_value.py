"""A lambda with a bare `*args` parameter used as a value inside a generator: the starred-parameter
closure of `_cpx_lambda_expr`. (A multi-parameter lambda value is refused on the C++ path.)
"""


def gather(n: int):
    pack = lambda *args: 0
    for i in range(n):
        yield pack() + i


def main():
    for v in gather(3):
        print(v)


main()
