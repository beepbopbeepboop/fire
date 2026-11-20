def in_range(lo: int, x: int, hi: int) -> bool:
    return lo <= x < hi


def main():
    print(1 < 2 < 3)
    print(1 < 3 < 2)
    print(3 > 2 > 1)
    print(2 == 2 == 2)
    print(2 == 2 == 3)
    print(1 < 2 == 2)
    print(0 == 0.0 == False)
    print(in_range(0, 0, 10))
    print(in_range(0, 10, 10))
    print(in_range(0, -1, 10))
    print(-1 < 0 < 1)
    print("a" < "b" < "c")
    print("b" < "a" < "c")
    print(5 >= 5 >= 4)
    print(1 != 2 != 1)
    print(1 != 1 != 1)
    a = [1, 2]
    print(a == [1, 2] == [1, 2])
    print(None == None == None)


main()
