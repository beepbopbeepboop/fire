class Grid:
    def __init__(self, rows, cols):
        self.rows = rows
        self.cols = cols

    def cell_count(self):
        return self.rows * self.cols

    def is_empty(self):
        return self.cell_count() == 0

    def describe(self):
        if self.is_empty():
            return "empty grid"
        return str(self.rows) + "x" + str(self.cols) + " with " + str(self.cell_count()) + " cells"

    def widen(self, extra):
        self.cols = self.cols + extra
        return self.describe()

    def square(self):
        return self.rows == self.cols


def main():
    g = Grid(3, 4)
    print(g.cell_count())
    print(g.is_empty())
    print(g.describe())
    print(g.widen(2))
    print(g.square())
    e = Grid(0, 9)
    print(e.is_empty())
    print(e.describe())
    s = Grid(5, 5)
    print(s.square())
    print(s.widen(0))
    print(Grid(-1, 2).describe())


main()
