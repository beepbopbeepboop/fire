def main():
    a = [1, 2, 3]
    b = [1, 2, 3]
    c = [1, 2]
    d = [1, 2, 4]
    print(a == b)
    print(a is b)
    print(a != c)
    print(a < d)
    print(c < a)
    print([] < [0])
    print([] == [])
    print(["a"] < ["b"])
    print(["", 0] == ["", False])
    print([None] == [False])
    print([0] == [0.0])
    print([[1]] == [[1]])
    print([1, [2, 3]] < [1, [2, 4]])
    print(a == (1, 2, 3))
    print(a == list((1, 2, 3)))
    print([] == [] and [0] != [False])


main()
