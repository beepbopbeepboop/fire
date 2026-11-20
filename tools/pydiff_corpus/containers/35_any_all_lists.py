def all_positive(xs: list) -> bool:
    return all(x > 0 for x in xs)


def main():
    print(any([]))
    print(all([]))
    print(any([0, "", None]))
    print(all([1, "a", True]))
    print(any([0, "", 3]))
    print(all([1, 0, 2]))
    print(all_positive([]))
    print(all_positive([1, 2]))
    print(all_positive([1, -1]))
    print(any(x is None for x in [1, None]))
    print(all(isinstance(x, int) for x in [1, True, 2]))
    print(any(isinstance(x, str) for x in [1, "a"]))
    print(all([[], {}]))
    print(any([[], {}]))
    print(all(()), any(()))


main()
