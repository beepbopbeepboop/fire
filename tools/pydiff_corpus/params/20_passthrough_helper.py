def scale(value, factor):
    return value * factor


def scale_twice(value, factor):
    return scale(value, factor)


def scale_default(value, factor=3):
    return scale_twice(value, factor)


def wrap(text, *args, **kwargs):
    return describe(text, *args, **kwargs)


def describe(text, sep=":", count=1):
    return (text + sep) * count


def main():
    print(scale(2, 5))
    print(scale_twice(2, 5))
    print(scale_twice("ab", 2))
    print(scale_twice([0], 0))
    print(scale_default(4))
    print(scale_default(-1, -1))
    print(wrap("x"))
    print(wrap("y", "-", 2))
    print(wrap("z", count=0))
    print(wrap("", sep=""))


main()
