def grid(rows: int, cols: int) -> list:
    return [[r * cols + c for c in range(cols)] for r in range(rows)]


def main():
    g = grid(3, 4)
    print(g)
    print([x for row in g for x in row if x % 5 == 0])
    print([[c for c in row if c % 2] for row in g])
    print(len([[0] * 3 for _ in range(2)]))
    table = [[i * j for j in range(1, 4)] for i in range(1, 4)]
    print(table)
    print(sum(sum(row) for row in table))
    flat = [y for x in [[1], [], [2, 3]] for y in x]
    print(flat)
    print([row[-1] for row in table])
    print([[] for _ in range(0)])
    print([(a, b) for a in range(2) for b in range(2) if a != b])
    print(grid(0, 5))


main()
