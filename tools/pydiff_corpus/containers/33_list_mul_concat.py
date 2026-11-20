def main():
    a = [0] * 3
    print(a)
    b = [None, ""] * 2
    print(b)
    c = [1, 2] + [3]
    print(c)
    print([] + [])
    print([1] * 0)
    print([1] * -2)
    print(["x"] * 2 + ["y"])
    grid = [[0] * 2] * 2
    grid[0][0] = 9
    print(grid)
    fixed = [[0] * 2 for _ in range(2)]
    fixed[0][0] = 9
    print(fixed)
    d = [False] * 2
    print(d)
    s = [1, 2] * 2 + [3] * 1
    print(s, len(s))
    print(c + c == c * 2)
    print(len([0] * 1000))
    print(sum([2] * 5))


main()
