def main():
    names = ["a", "b", "c"]
    ages = [1, 0, -1, 99]
    print(list(zip(names, ages)))
    print(list(zip([], ages)))
    print(list(zip(names)))
    for n, a in zip(names, ages):
        print(n, a)
    print(list(range(5, 0, -1)))
    print(list(range(10, 0, -3)))
    print(list(range(0, -5, -2)))
    print(list(range(3, 3, -1)))
    print(list(range(-1, -4, -1)))
    print(list(range(4)))
    print(list(range(-3, 0)))
    print(len(range(10, -10, -5)))
    print(range(0, 10, 2)[-1])
    print(list(zip(range(3, 0, -1), "xyz")))


main()
