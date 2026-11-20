def main():
    print(abs(-3), abs(3.5), abs(-0.0), abs(0))
    print(divmod(17, 5), divmod(-17, 5), divmod(17.5, 5))
    print(pow(2, 10), pow(2, 10, 1000), pow(3, -1 + 3))
    print(pow(2, 0.5) == 2 ** 0.5)
    print(round(-1.5), round(0.5), round(1.5))
    print(min(3, 1.5, 2), max(3, 1.5, 2))
    print(max(2, 2.0), min(2.0, 2))
    print(max([-1, -5, 0]), min([-1, -5, 0]))
    print(sum([1, 2.5, 3]))
    print(sum([0.5, 0.25]) == 0.75)
    print(max("abc", "abd"))
    print(min([3, 1], [2, 9]))
    print(abs(-2 ** 3))


main()
