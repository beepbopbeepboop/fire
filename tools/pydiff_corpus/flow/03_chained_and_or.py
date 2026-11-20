def classify(a: int, b: int, c: int):
    return a and b or c


def main():
    print(1 and 2 and 3)
    print(1 and 0 and 3)
    print(0 or "" or None or "last")
    print(None or 0 or [] or "found")
    print("a" and 0 or "fallback")
    print("a" and "b" or "fallback")
    print(classify(1, 2, 3))
    print(classify(0, 2, 3))
    print(classify("", "x", "y"))
    print(classify([1], [], "c"))
    print(1 or 2 and 3)
    print((1 or 2) and 3)
    print(not 0 and 4 or 5)
    print(0 and 1 or 2 and 3 or 4)
    print(None and None or 0)
    total = 0 or 2 or 5
    print("total", total)


main()
