def main():
    values = [0, -1, 1, 255, -1000, 10 ** 20]
    for v in values:
        print(str(v))
        print(repr(v))
    print(str(True + True))
    print(int("0"))
    print(str(-0))
    print(len(str(10 ** 20)))
    print(str(values))
    print(repr([v for v in values if v < 0]))
    print(str(-(2 ** 63)))
    print(repr(0 * -5))


main()
