def do_nothing():
    pass


def maybe_print(x, show=False):
    if show:
        print("showing", x)
        return
    return


def only_some(n):
    if n > 0:
        return n * 10


def main():
    r = do_nothing()
    print(r is None)
    print(r)
    print(maybe_print(1))
    print(maybe_print(2, True) is None)
    print(only_some(3))
    print(only_some(0))
    print(only_some(-4) is None)
    print(only_some(0) == None)
    print(bool(only_some(0)))
    print(type(only_some(1)).__name__)
    print(type(only_some(-1)).__name__)


main()
