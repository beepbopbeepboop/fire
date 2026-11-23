"""An assignment expression (`:=`) inside a generator body: the `(name = value)` form of `_cpp_expr_ex`.
"""


def walk(n: int):
    for i in range(n):
        if (k := i + 1) > 1:
            yield k


def main():
    for v in walk(3):
        print(v)


main()
