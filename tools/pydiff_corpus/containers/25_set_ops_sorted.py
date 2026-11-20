def show(s: set) -> list:
    return sorted(s)


def main():
    a = {3, 1, 2}
    b = {2, 3, 4}
    print(show(a))
    print(show(b))
    print(show(a | b))
    print(show(a & b))
    print(show(a - b))
    print(show(b - a))
    print(show(a ^ b))
    print(2 in a)
    print(7 in a)
    print(len(a | b))
    print(a.issubset({1, 2, 3, 4}))
    print(a.isdisjoint({9}))
    print(show(a.union([10, 1])))
    print(show(a.intersection(b, {3})))
    print(show(a.difference([1])))
    print(show(set()))


main()
