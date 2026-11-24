"""Integer conversion inside a generator body: the `(int64_t)(x)` cast of `_cpx_call_ident`, and a
conditional expression, which the untyped path of `_cpp_expr_ex` lowers.
"""


def conv(n: int):
    txt = "3"
    for i in range(n):
        yield int(txt) + i
        yield int(i) * 2
        yield i if i > 1 else 0


def main():
    for v in conv(3):
        print(v)


main()
