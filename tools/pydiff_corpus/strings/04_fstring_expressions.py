def double(x: int) -> int:
    return x * 2


def main():
    a = 3
    b = -4
    xs = [1, 2, 3]
    print(f"{a + b}")
    print(f"{a * b}")
    print(f"{double(a)}")
    print(f"{len(xs)}")
    print(f"{xs[-1]}")
    print(f"{xs[0] if a > 2 else 0}")
    print(f"{a == 3}")
    print(f"{a < b}")
    print(f"{'-'.join(['x', 'y'])}")
    print(f"{ {'k': 1}['k'] }")
    print(f"{(a, b)}")
    print(f"{a!r:>4}")
    print(f"{a=}")
    print(f"{[x * x for x in xs]}")


main()
