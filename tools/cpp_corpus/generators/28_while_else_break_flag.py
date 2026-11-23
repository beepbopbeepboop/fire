"""A `while` loop with `break` and an `else` clause inside a generator body: the `bool` break flag the
printer declares before the loop (the `while`/`else` lowering of the generator printer).
"""


def count(n: int):
    i = 0
    while i < n:
        i += 1
        if i == 2:
            break
        yield i
    else:
        yield 99


def main():
    for v in count(4):
        print(v)


main()
