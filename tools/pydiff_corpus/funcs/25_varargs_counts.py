def count_args(*args):
    return len(args)


def show(*args):
    print(args)


def first_or_none(*args):
    if len(args) == 0:
        return None
    return args[0]


def main():
    print(count_args())
    print(count_args(1))
    print(count_args(1, "a", None))
    print(count_args(*[]))
    show()
    show(0)
    show(1, 2, 3)
    print(first_or_none())
    print(first_or_none(False))
    print(first_or_none("", 9, 9))
    print(type(show()).__name__)
    print(count_args([1, 2], (3,)))


main()
