def main():
    big = 2 ** 62
    print(big)
    print(big - 1)
    print(big * 2 - 1)
    print(-big)
    print(big // 3)
    print(big % 1000007)
    print((big - 1) + 1 == big)
    print(2 ** 62 + 2 ** 61)
    print(9007199254740993 - 1)
    print(9007199254740993 * 3)
    x = 1
    for _ in range(40):
        x = x * 3
    print(x)
    print(x // (3 ** 39))
    print(10 ** 18 + 10 ** 18 - 1)
    print(str(2 ** 63)[-5:])
    print(len(str(2 ** 100)))
    print(max(2 ** 62, 2 ** 61 * 3))


main()
