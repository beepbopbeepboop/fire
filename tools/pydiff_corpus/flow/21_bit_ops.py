def bits(n: int) -> str:
    return bin(n)


def main():
    print(12 & 10, 12 | 10, 12 ^ 10)
    print(-12 & 10, -12 | 10, -12 ^ 10)
    print(~0, ~5, ~-1)
    print(1 << 10, 1 << 0, 3 << 2)
    print(1024 >> 3, -16 >> 2, -1 >> 5)
    print(0 & 99, 0 | 99)
    print(255 & -256)
    print(bits(5), bits(-5))
    print(1 << 62)
    print((1 << 62) >> 61)
    print(7 ^ 7, 5 ^ 0)
    flags = 0
    flags |= 4
    flags |= 1
    flags &= ~4
    print(flags)
    print(True & False, True | 0, True ^ True)
    print(6 & 3 == 2)


main()
