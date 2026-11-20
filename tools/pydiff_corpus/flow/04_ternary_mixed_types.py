def label(n: int):
    return "even" if n % 2 == 0 else n


def pick_value(flag: bool):
    return 42 if flag else "forty-two"


def main():
    print(label(4))
    print(label(7))
    print(pick_value(True))
    print(pick_value(False))
    values = [None if i == 2 else i * 10 for i in range(4)]
    print(values)
    x = 3.5 if len("ab") > 1 else 0
    print(x)
    y = 0 if len("ab") > 5 else 2.5
    print(y)
    z = [] if y else None
    print(z)
    w = "yes" if [] else "no"
    print(w)
    print(1 if None is None else 2)
    print(("a" if 0 else "b") * 3)


main()
