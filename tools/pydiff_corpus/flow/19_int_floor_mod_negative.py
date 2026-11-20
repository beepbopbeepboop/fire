def main():
    pairs = [(7, 2), (-7, 2), (7, -2), (-7, -2), (0, 5), (5, 5), (-1, 3)]
    for a, b in pairs:
        print(a, b, a // b, a % b)
    print(divmod(-17, 5))
    print(divmod(17, -5))
    print(-17 // 5, -17 % 5)
    print(-(17 // 5), (-17) // 5)
    print(-7 % -3)
    print(2 ** 10, 2 ** -1, (-2) ** 3, -2 ** 2)
    print(10 ** 0, 0 ** 0)
    print(3 ** 40 % 1000)


main()
