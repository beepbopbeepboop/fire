def divmod_pair(a: int, b: int) -> tuple:
    return a // b, a % b


def min_max(xs: list):
    if not xs:
        return None, None
    return min(xs), max(xs)


def main():
    q, r = divmod_pair(17, 5)
    print(q, r)
    print(divmod_pair(-7, 2))
    print(divmod_pair(0, 3))
    lo, hi = min_max([4, -2, 9])
    print(lo, hi)
    print(min_max([]))
    empty_lo, empty_hi = min_max([])
    print(empty_lo is None, empty_hi is None)
    result = min_max(["b", "a"])
    print(result)
    print(type(result).__name__)
    print(len(result))
    print(result[0] + result[1])
    print(divmod(-7, 2) == divmod_pair(-7, 2))
    first, _ = divmod_pair(9, 4)
    print(first)


main()
