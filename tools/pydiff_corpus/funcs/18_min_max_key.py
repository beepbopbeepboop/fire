def main():
    words = ["kiwi", "fig", "banana", "apple"]
    print(min(words))
    print(max(words))
    print(min(words, key=len))
    print(max(words, key=len))
    print(max(["aa", "bb"], key=len))
    print(min(words, key=lambda w: w[-1]))
    print(min([3, -1, 2], key=abs))
    print(max([3, -1, 2], key=lambda x: -x))
    print(max([], key=len, default="none"))
    print(min([], default=0))
    print(max([(1, "b"), (1, "a"), (0, "z")]))
    print(min((2, 9), (2, 3), key=lambda t: t[1]))


main()
