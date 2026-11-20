def total(start, *nums):
    s = start
    for n in nums:
        s += n
    return s


def tagged(tag, *items):
    return [tag + str(i) for i in items]


def main():
    print(total(10))
    print(total(0, 1, 2, 3))
    print(total(-1, -1))
    print(total(0))
    print(total(0.5, 1, 2))
    print(tagged("t"))
    print(tagged("#", 0, -1, "x"))
    print(tagged("", *[None, False]))
    print(total(total(1), total(2, 3)))


main()
