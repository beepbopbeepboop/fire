def half(n: int) -> float:
    return n / 2


def floor_half(n):
    return n // 2


def remainder(n, d):
    return n % d


def main():
    print(half(7))
    print(half(8))
    print(floor_half(7))
    print(floor_half(8))
    print(type(half(4)).__name__)
    print(type(floor_half(4)).__name__)
    print(remainder(7, 3))
    print(remainder(6, 3))
    print(remainder(0, 5))
    print(7 / 7)
    print(1 / 4)
    print(10 // 4 * 4 + 10 % 4)
    print(2 ** 10)
    print(int(7 / 2))


main()
