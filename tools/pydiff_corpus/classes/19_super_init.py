class Shape:
    def __init__(self, name, sides):
        self.name = name
        self.sides = sides

    def info(self):
        return self.name + "/" + str(self.sides)


class Square(Shape):
    def __init__(self, side):
        super().__init__("square", 4)
        self.side = side

    def info(self):
        return super().info() + "/side=" + str(self.side)


class Blob(Shape):
    def __init__(self):
        super().__init__("blob", 0)


def main():
    s = Square(3)
    print(s.name)
    print(s.sides)
    print(s.side)
    print(s.info())
    t = Square(-1)
    print(t.info())
    b = Blob()
    print(b.name)
    print(b.sides)
    print(b.info())
    print(hasattr(b, "side"))
    print(isinstance(s, Shape))
    print(Shape("generic", 1).info())


main()
