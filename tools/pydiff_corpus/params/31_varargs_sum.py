def total(*nums: int) -> int:
    s = 0
    for n in nums:
        s = s + n
    return s


def count_args(*args):
    return len(args)


def first_or_default(default, *args):
    if len(args) == 0:
        return default
    return args[0]


def main():
    print(total())
    print(total(5))
    print(total(1, 2, 3))
    print(total(-1, -1))
    print(total(0, 0, 0, 0))
    print(count_args())
    print(count_args(None))
    print(count_args([], "", 0))
    print(first_or_default("none"))
    print(first_or_default("none", 0))
    print(first_or_default("none", None))
    values = [4, 5, 6]
    print(total(*values))
    print(total(*[]))


main()
