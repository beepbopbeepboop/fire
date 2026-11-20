def main():
    grid = {}
    grid[(0, 0)] = "origin"
    grid[(0, 1)] = "east"
    grid[(1, 0)] = ""
    grid[(-1, 0)] = 0
    print(len(grid))
    print(grid[(0, 0)])
    print(grid[(1, 0)] == "")
    print(grid[(-1, 0)])
    print((0, 1) in grid)
    print((1, 1) in grid)
    print(grid.get((5, 5), "none"))
    print(grid.get((-1, 0), "none"))
    grid[(0, 0)] = "changed"
    print(grid[(0, 0)])
    pairs = sorted(grid.keys())
    print(pairs)
    key = (2, 3)
    grid[key] = [key[0] + key[1]]
    print(grid[key])
    print(grid[(2, 3)][0])
    print(sorted(grid.items())[0])


main()
