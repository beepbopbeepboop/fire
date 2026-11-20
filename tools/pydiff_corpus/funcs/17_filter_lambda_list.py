def main():
    vals = [0, 1, -2, "", "x", None, False, 7]
    print(list(filter(lambda x: x, vals)))
    print(list(filter(lambda x: isinstance(x, int), vals)))
    print(list(filter(lambda x: isinstance(x, str), vals)))
    print(list(filter(lambda x: x is None, vals)))
    print(list(filter(lambda x: x is not None and x > 0 if isinstance(x, int) else False, vals)))
    print(list(filter(lambda x: x, [])))
    print(list(filter(lambda s: len(s) > 1, ["a", "bb", "", "ccc"])))
    print(list(filter(lambda n: n % 2 == 0, range(-4, 5))))
    print(len(list(filter(lambda x: False, vals))))
    print(vals)


main()
