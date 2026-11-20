def add3(a, b, c):
    return a + b + c


def label(name, sep=":", tail=""):
    return name + sep + tail


def main():
    args = [1, 2, 3]
    print(add3(*args))
    print(add3(*(1, 2), 3))
    print(add3(*[1], *[2, 3]))
    kwargs = {"a": 1, "b": 2, "c": 3}
    print(add3(**kwargs))
    print(add3(*[], **kwargs))
    print(label(**{"name": "x"}))
    print(label("n", **{"tail": "t"}))
    print(label(*["a", "-"], **{"tail": ""}))
    print(label("", ""))
    print(add3(0, *[0], **{"c": 0}))
    print(args)


main()
