def main():
    print(repr([]))
    print(repr({}))
    print(repr([1, "two", None, True]))
    print(repr([[1, 2], [3, [4, []]]]))
    print(repr({"a": 1, "b": [2, 3]}))
    print(str({"k": "v"}))
    print(repr([1.0, 0.5, -0.0]))
    print(str(["x", "y"]))
    print(repr({1: "one", "1": 1}))
    print(repr([{}, {"": ""}]))
    print(len(repr([])))
    print(repr({"outer": {"inner": [None]}}))
    print(str([[]]))


main()
