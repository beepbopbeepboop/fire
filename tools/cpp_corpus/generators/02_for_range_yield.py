"""`for ... in range(...)` inside a generator: the CallExpr arm of `_cpp_expr`
and the ForStmt arm of `_cpp_for_stmt`, with a container built in `main`.
"""


def squares(n: int):
    out = []
    for i in range(n):
        out.append(i)
        yield out


def main():
    last = []
    for v in squares(3):
        last = v
    print(len(last))


main()
