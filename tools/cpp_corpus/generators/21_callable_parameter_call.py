"""A call through a callable-valued PARAMETER inside a generator: the dynamic word call of
`_cpp_dyn_call_expr`. The call's result is stored before it is yielded (a yield of the call directly is
refused: the call sites must agree on the parameter's type).
"""


def apply(fn, n: int):
    for i in range(n):
        r = fn(i)
        yield r + 1


def double(x: int) -> int:
    return x * 2


def main():
    for v in apply(double, 3):
        print(v)


main()
