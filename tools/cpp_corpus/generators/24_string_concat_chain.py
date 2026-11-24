"""Chained string concatenation of two local strings inside a generator body: `mojo_str_cat` over
strings, the join of two locals and of a local with a literal.
"""


def joined(n: int):
    a = "left"
    b = "right"
    for i in range(n):
        yield a + b
        yield a + "-" + b


def main():
    for s in joined(2):
        print(s)


main()
