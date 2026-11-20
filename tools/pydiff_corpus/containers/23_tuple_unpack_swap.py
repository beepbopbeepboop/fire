def split(pair: tuple):
    first, second = pair
    return second, first


def main():
    a, b = 1, "two"
    print(a, b)
    a, b = b, a
    print(a, b)
    x, y, z = (0, "", None)
    print(x, repr(y), z)
    print(z is None)
    head, *rest = [1, 2, 3, 4]
    print(head)
    print(rest)
    *init, last = (5, 6, 7)
    print(init, last)
    print(split((0, "")))
    p = (9,)
    print(len(p), p[0])
    print(())
    print(len(()))
    n1, n2 = split(("a", -1))
    print(n1, n2)


main()
