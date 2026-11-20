class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def __str__(self):
        return "(" + str(self.x) + ", " + str(self.y) + ")"

    def __repr__(self):
        return "Point(" + repr(self.x) + ", " + repr(self.y) + ")"


class Label:
    def __init__(self, text):
        self.text = text

    def __repr__(self):
        return "Label(" + repr(self.text) + ")"


class Plain:
    def __init__(self, v):
        self.v = v


def main():
    p = Point(1, -2)
    print(p)
    print(str(p))
    print(repr(p))
    print(str(Point(0, 0)))
    print(repr(Point("a", None)))
    print([Point(3, 4)])
    lab = Label("")
    print(repr(lab))
    print(str(lab).startswith("<"))
    print(lab)
    print(repr(Label("it's")))
    print("point is " + str(p))
    pl = Plain(5)
    print(str(pl).startswith("<"))
    print(repr(pl).startswith("<"))


main()
