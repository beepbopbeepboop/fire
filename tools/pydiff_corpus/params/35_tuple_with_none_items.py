def lookup(key):
    table = {"a": (1, "one"), "b": (None, "none-val"), "c": (0, None)}
    if key in table:
        return table[key]
    return (None, None)


def first_of(pair):
    return pair[0]


def main():
    n, word = lookup("a")
    print(n, word)
    n, word = lookup("b")
    print(n is None, word)
    n, word = lookup("c")
    print(n, word is None)
    n, word = lookup("zz")
    print(n, word)
    print(first_of(lookup("c")))
    print(first_of(lookup("b")) is None)
    print(lookup("c") == (0, None))
    print(lookup("a") == (1, "one"))
    print(len(lookup("q")))
    print(lookup("b")[1] or "default")


main()
