def pick(a, b):
    return a and b


def main():
    print(0 or 5)
    print(0 and 5)
    print(7 and 9)
    print("" or "default")
    print("hi" or "default")
    print("" and "x")
    print(None or "fallback")
    print(None and [1])
    print([] or [9, 9])
    print([1, 2] and "nonempty")
    print([] and "never")
    print(False or 0)
    print(False or 0.0)
    print(pick("abc", "def"))
    print(pick("", "def"))
    print(pick([1], []))
    print(pick(None, 4))
    name = None
    print("hello " + (name or "stranger"))
    x = [] or None
    print(x)
    print(x is None)


main()
