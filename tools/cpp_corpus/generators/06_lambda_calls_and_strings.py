"""Lambdas, method calls and an interpolated string inside a generator body:
`_cpp_expr`'s LambdaExpr, CallExpr, MemberExpr and StringLiteral arms, and
`_cpp_string_literal_expr`'s interpolation walk.
"""


def labelled(n: int):
    tag = "item"
    scale = lambda v: v * 3
    for i in range(n):
        yield f"{tag}:{scale(i)}"


def main():
    for s in labelled(3):
        print(s)


main()
