def main():
    records = [("bob", 3), ("al", 3), ("cy", 1), ("al", 0)]
    print(sorted(records))
    print(sorted(records, key=lambda r: r[1]))
    print(sorted(records, key=lambda r: (-r[1], r[0])))
    records.sort()
    print(records[0])
    print(records[-1])
    print(("a", 1) < ("a", 2))
    print((1, "z") < (2, "a"))
    print((1,) < (1, 0))
    print(() < (0,))
    print((1, 2) == (1, 2))
    print((1, 2) == [1, 2])
    pairs = [(0, ""), (0, "a"), (-1, "z")]
    print(max(pairs))
    print(min(pairs))
    print(pairs.index((0, "a")))
    print((0, "") in pairs)


main()
