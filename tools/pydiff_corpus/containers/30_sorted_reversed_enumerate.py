def main():
    letters = ["c", "a", "b"]
    print(sorted(letters))
    print(list(reversed(letters)))
    print(letters)
    for i, ch in enumerate(letters):
        print(i, ch)
    for i, ch in enumerate(letters, start=1):
        print(i, repr(ch))
    for i, ch in enumerate(reversed(letters)):
        print(i, ch)
    print(list(enumerate([])))
    print(list(enumerate(["", 0, None])))
    print(list(reversed([])))
    print(list(reversed((1, "x"))))
    print(list(reversed("ab")))
    pairs = [(i, v) for i, v in enumerate([0, "", -1]) if v]
    print(pairs)
    print(sorted(enumerate([5, 1]), key=lambda p: p[1]))


main()
