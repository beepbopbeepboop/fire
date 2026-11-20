def squares_upto(n):
    out = []
    i = 0
    while i <= n:
        out.append(i * i)
        i += 1
    return out


def evens_only(items):
    result = []
    for x in items:
        if x % 2 == 0:
            result.append(x)
    return result


def words_longer_than(words, limit: int):
    out = []
    for w in words:
        if len(w) > limit:
            out.append(w)
    return out


def main():
    print(squares_upto(4))
    print(squares_upto(0))
    print(squares_upto(-1))
    print(evens_only([1, 2, 3, 4, -6]))
    print(evens_only([]))
    print(evens_only([7]))
    print(words_longer_than(["a", "abc", ""], 0))
    print(words_longer_than(["a", "abc"], 5))
    print(len(squares_upto(9)))


main()
