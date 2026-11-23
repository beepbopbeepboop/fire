"""`and`/`or` with a word left operand and a non-string right operand inside a generator body: the
word-pick lambda of `_cpx_binary_op`, which keeps the left word when its truth decides the result.
"""


def choose(n: int):
    for i in range(n):
        base = i + 1
        yield base or 9
        yield base and 4


def main():
    for v in choose(3):
        print(v)


main()
