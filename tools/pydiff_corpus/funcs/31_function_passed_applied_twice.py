def twice(f, x):
    return f(f(x))


def inc(x):
    return x + 1


def main():
    print(twice(inc, 0))
    print(twice(inc, -1))
    print(twice(lambda s: s + "!", "hi"))
    print(twice(lambda s: s + "!", ""))
    print(twice(lambda xs: xs + [0], []))
    print(twice(str, 5))
    print(twice(abs, -4))
    print(twice(abs, 0))
    print(twice(inc, 2.5))
    print(twice(lambda b: not b, False))
    print(twice(lambda b: not b, None))


main()
