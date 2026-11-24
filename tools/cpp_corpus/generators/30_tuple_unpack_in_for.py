"""Tuple unpacking in a generator's `for` loop: the element read of the tuple-target loop of `_cpp_for_stmt`.
"""


def pairs(n: int):
    items = [(1, 2), (3, 4)]
    for a, b in items:
        yield a + b


def main():
    for v in pairs(2):
        print(v)


main()
