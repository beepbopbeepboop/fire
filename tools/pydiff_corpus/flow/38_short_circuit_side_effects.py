def noisy(label: str, value):
    print("eval", label)
    return value


def main():
    r = noisy("a", False) and noisy("b", True)
    print("r1", r)
    r = noisy("c", True) and noisy("d", "yes")
    print("r2", r)
    r = noisy("e", 0) or noisy("f", "")
    print("r3", repr(r))
    r = noisy("g", "") or noisy("h", None) or noisy("i", 7)
    print("r4", r)
    r = noisy("j", 1) or noisy("k", 2)
    print("r5", r)
    if noisy("l", []) or noisy("m", [0]):
        print("branch taken")
    if noisy("n", None) and noisy("o", 1):
        print("never")
    else:
        print("else taken")
    print(noisy("p", 5) > 3 or noisy("q", 9) > 3)


main()
