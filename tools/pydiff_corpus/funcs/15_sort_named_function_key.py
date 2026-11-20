def by_last(s):
    return s[-1]


def neg_len(s):
    return -len(s)


def mod3(n):
    return n % 3


def main():
    words = ["ox", "cat", "a", "dog"]
    print(sorted(words, key=by_last))
    print(sorted(words, key=neg_len))
    words.sort(key=neg_len)
    print(words)
    print(sorted(range(7), key=mod3))
    print(sorted([-4, 4, -1, 1, 0], key=abs))
    print(sorted(words, key=None))
    print(max(words, key=neg_len))
    print(min(words, key=by_last))
    print(sorted([], key=mod3))
    print(words)


main()
