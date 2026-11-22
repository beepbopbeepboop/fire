"""Counted loop + `yield`: the smallest C++ coroutine unit the lowerer makes.

Exercises `_cpp_stmt`'s WhileStmt/AugAssignStmt arms and `_cpp_expr`'s
IdentExpr/IntLiteral/BinaryOp arms inside a generator body.
"""


def counter(n: int):
    i = 0
    while i < n:
        yield i * i
        i += 1


def main():
    total = 0
    for v in counter(4):
        total += v
    print(total)


main()
