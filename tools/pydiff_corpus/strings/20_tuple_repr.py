def make_pair(a: int, b: str) -> tuple:
    return (a, b)


def main():
    print(repr(()))
    print(repr((1,)))
    print(repr((1, 2)))
    print(repr(("a",)))
    print(repr((None,)))
    print(str(make_pair(3, "x")))
    print(repr((1, (2,), [3])))
    print(len((5,)))
    print(len(()))
    t = (1,)
    print(type(t).__name__)
    print(t * 3)
    print(str(((),)))
    print(repr((True, 2.5)))
    print(make_pair(0, "") == (0, ""))


main()
