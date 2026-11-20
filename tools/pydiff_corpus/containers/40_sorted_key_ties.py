def by_len(words: list) -> list:
    return sorted(words, key=len)


def main():
    words = ["bb", "a", "cc", "", "d"]
    print(by_len(words))
    print(sorted(words, key=len, reverse=True))
    print(max(words, key=len))
    print(min(words, key=len))
    print(sorted(words, key=lambda w: (len(w), w)))
    print(sorted([3, -3, 2, -2, 0], key=abs))
    print(sorted([3, -3, 2, -2, 0], key=abs, reverse=True))
    print(words)
    print(by_len([]))
    print(sorted([0, False, True]))
    print(sorted([(1, None), (0, "x")], key=lambda t: t[0]))
    print(max([2, 2.0, "b"][:2]))
    print(sorted(words)[0] == "")
    print(sorted(["b", "A", "a", "B"]))


main()
