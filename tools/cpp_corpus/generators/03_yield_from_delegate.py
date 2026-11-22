"""`yield from`: `_cpp_yield_from` (the delegation unit) and the struct/extra
promise plumbing it emits, plus a value-carrying `return` read by the
delegating generator's consumer.
"""


def inner(n: int):
    for i in range(n):
        yield i
    return 100


def outer(n: int):
    yield from inner(n)
    yield 7


def main():
    total = 0
    for v in outer(3):
        total += v
    print(total)


main()
