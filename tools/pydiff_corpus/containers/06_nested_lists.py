def make_grid(rows: int, cols: int) -> list:
    grid = []
    for r in range(rows):
        row = []
        for c in range(cols):
            row.append(r * 10 + c)
        grid.append(row)
    return grid


def main():
    grid = make_grid(3, 4)
    print(grid)
    print(grid[0][0])
    print(grid[2][3])
    print(grid[-1][-1])
    print(grid[1][-2])
    print(len(grid), len(grid[0]))
    print(grid[1][1:3])
    print(grid[0][-1] + grid[1][0])
    jagged = [[], [1], [2, 3]]
    print(jagged)
    print(len(jagged[0]))
    print(jagged[2][0])
    print([len(r) for r in jagged])
    print(make_grid(0, 5))


main()
