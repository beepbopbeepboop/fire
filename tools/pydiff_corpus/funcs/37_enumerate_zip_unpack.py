def main():
    names = ["ann", "ben", "cy"]
    ages = [30, "x"]
    for i, n in enumerate(names):
        print(i, n)
    for i, n in enumerate(names, start=1):
        print(i, n)
    for n, a in zip(names, ages):
        print(n, a)
    print(list(zip(names, ages)))
    print(list(zip([], [1])))
    print(list(zip("ab", [None, False])))
    for idx, (n, a) in enumerate(zip(names, ages)):
        print(idx, n, a)
    pairs = [(0, ""), (-1, "neg")]
    for num, word in pairs:
        print(num, repr(word))
    print(list(enumerate([])))
    print(list(enumerate("", 5)))


main()
