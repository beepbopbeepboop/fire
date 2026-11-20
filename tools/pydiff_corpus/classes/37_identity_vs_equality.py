class Cell:
    def __init__(self, value):
        self.value = value


def same_value(a, b) -> bool:
    return a.value == b.value


def same_cell(a, b) -> bool:
    return a is b


def main():
    x = Cell(1)
    y = Cell(1)
    z = x
    print(x is y)
    print(x is z)
    print(same_value(x, y))
    print(same_cell(x, y))
    print(same_cell(x, z))
    z.value = 2
    print(x.value)
    print(y.value)
    print(same_value(x, y))
    n = None
    print(n is None)
    print(x is None)
    print(x is not None)
    cells = [x, y]
    print(cells[0] is x)
    print(cells[1] is x)
    print(cells.index(y) if y in cells else -1)
    empty = Cell(None)
    print(empty.value is None)
    print(empty.value == 0)


main()
