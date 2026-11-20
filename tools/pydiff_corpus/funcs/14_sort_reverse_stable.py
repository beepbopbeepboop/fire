def main():
    records = [("a", 2), ("b", 1), ("c", 2), ("d", 1), ("e", 3)]
    print(sorted(records, key=lambda r: r[1]))
    print(sorted(records, key=lambda r: r[1], reverse=True))
    print(sorted(records, key=lambda r: r[1] % 2, reverse=True))
    print(sorted(records, key=lambda r: r[0], reverse=True))
    ordered = records[:]
    ordered.sort(key=lambda r: r[1], reverse=True)
    print(ordered)
    ordered.sort(key=lambda r: r[1])
    print(ordered)
    print(sorted([3, 1, 3, 1], reverse=True))
    print(sorted([], reverse=True))
    print(sorted(["x", "X"], key=lambda s: 0, reverse=True))
    print(records)


main()
