"""`continue` inside a generator's `for` loop: the `continue;` statement line of the generator printer.
"""


def odd(n: int):
    for i in range(n):
        if i % 2 == 0:
            continue
        yield i


def main():
    for v in odd(5):
        print(v)


main()
