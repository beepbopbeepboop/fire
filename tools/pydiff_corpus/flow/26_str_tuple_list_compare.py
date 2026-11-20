def main():
    print("apple" < "banana", "Zebra" < "apple")
    print("a" < "ab", "" < "a")
    print("10" < "9", 10 < 9)
    print("abc" == "abc", "abc" != "abd")
    print((1, 2) < (1, 3), (1, 2, 0) > (1, 2))
    print((2,) < (1, 99), () < (0,))
    print([1, 2] < [1, 2, 0], [3] > [2, 99])
    print([1, "a"] == [1, "a"])
    print([0] == [False], (1,) == (1.0,))
    names = ["bob", "Alice", "carol"]
    print(sorted(names))
    print(max(names), min(names))
    print(["b", "a"] < ["b", "a", ""])
    print(("x", 2) < ("x", 10))
    print(sorted([(2, "b"), (1, "z"), (2, "a")]))
    print("abc" > "abcd", "B" < "a")


main()
