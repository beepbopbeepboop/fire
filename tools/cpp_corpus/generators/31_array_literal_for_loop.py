"""A literal list of tuples iterated in a generator's `for` loop: the fixed-size array declaration and the
element reads of the literal-iteration form of `_cpp_for_stmt`.
"""


def rows(n: int):
    for x, y in [(1, 2.5), (3, 4.5)]:
        yield x + int(y)


def main():
    for v in rows(2):
        print(v)


main()
