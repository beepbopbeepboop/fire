class Rectangle:
    def __init__(self, width, height):
        self.width = width
        self.height = height

    def area(self):
        return self.width * self.height

    def perimeter(self):
        return 2 * (self.width + self.height)

    def scale(self, factor):
        self.width = self.width * factor
        self.height = self.height * factor


def main():
    r = Rectangle(3, 4)
    print(r.width)
    print(r.height)
    print(r.area())
    print(r.perimeter())
    r.scale(2)
    print(r.area())
    z = Rectangle(0, 5)
    print(z.area())
    n = Rectangle(-2, 3)
    print(n.area())
    print(n.perimeter())


main()
