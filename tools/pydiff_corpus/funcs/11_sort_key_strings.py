def main():
    words = ["pear", "Apple", "fig", "banana", "", "kiwi"]
    print(sorted(words))
    print(sorted(words, key=lambda w: w.lower()))
    print(sorted(words, key=lambda w: len(w)))
    print(sorted(words, key=lambda w: (len(w), w)))
    print(sorted(words, key=lambda w: w[-1:]))
    print(sorted(words, key=lambda w: w.lower(), reverse=True))
    mixed = ["b", "B", "a", "A"]
    print(sorted(mixed))
    print(sorted(mixed, key=lambda s: s.lower()))
    print(sorted(["10", "9", "100"]))
    print(sorted(["10", "9", "100"], key=lambda s: int(s)))
    print(words)


main()
