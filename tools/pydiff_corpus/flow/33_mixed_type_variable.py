def describe(flag: bool):
    if flag:
        value = 42
    else:
        value = "forty-two"
    return value


def main():
    a = describe(True)
    b = describe(False)
    print(a)
    print(b)
    print(type(a) == int, type(b) == str)
    x = 0
    print(x)
    x = "now text"
    print(x)
    x = [x, 1]
    print(x)
    x = None
    print(x)
    x = 3.25
    print(x)
    box = [1, "two", 3.0, None, True]
    for item in box:
        print(item)
    total = 0
    for item in box:
        if isinstance(item, int) and not isinstance(item, bool):
            total += item
    print(total)


main()
