def main():
    pairs = [(2, "b"), (1, "z"), (2, "a"), (1, "a"), (0, "")]
    print(sorted(pairs))
    print(sorted(pairs, key=lambda p: p[1]))
    print(sorted(pairs, key=lambda p: (p[0], p[1]), reverse=True))
    print(sorted(pairs, key=lambda p: p[0]))
    print(sorted(pairs, key=lambda p: (-p[0], p[1])))
    triples = [(1, 2, 3), (1, 2), (0, 9, 9, 9), ()]
    print(sorted(triples))
    print(sorted(triples, key=len))
    print(sorted([(True, 1), (False, 5), (True, 0)]))
    print(max(pairs, key=lambda p: (p[1], p[0])))
    print(min(pairs))


main()
