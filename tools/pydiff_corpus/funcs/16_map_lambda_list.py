def main():
    print(list(map(lambda x: x * x, [1, 2, 3])))
    print(list(map(lambda x: x, [])))
    print(list(map(lambda a, b: a + b, [1, 2, 3], [10, 20, 30])))
    print(list(map(lambda a, b: a + b, [1, 2, 3], [10])))
    print(list(map(str, [0, -1])))
    print(list(map(lambda s: s.upper(), ["a", ""])))
    print(list(map(lambda x: str(x) + "!", [1, "a", None])))
    print(list(map(lambda x: x == 0, [0, False, "", 0.0])))
    doubled = map(lambda x: x * 2, [5, 6])
    print(next(doubled))
    print(list(doubled))
    print(list(map(lambda x: -x, range(3))))


main()
