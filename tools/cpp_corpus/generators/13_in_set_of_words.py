"""`in` and `not in` over a literal tuple of integers inside a generator body, the result kept as a
word (a bool yield is typed int64_t on the C++ path and refused, so the test feeds a conditional).
"""


def membership(n: int):
    for i in range(n):
        flag = 1 if i in (1, 3, 5) else 0
        yield flag
        yield 0 if i not in (0, 2) else 1


def main():
    for v in membership(4):
        print(v)


main()
