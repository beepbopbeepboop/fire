class Vector:
    def __init__(self, x: int, y: int):
        self.x = x
        self.y = y

    def add(self, other):
        return Vector(self.x + other.x, self.y + other.y)

    def scaled(self, k):
        return Vector(self.x * k, self.y * k)

    def dot(self, other) -> int:
        return self.x * other.x + self.y * other.y

    def show(self):
        return "<" + str(self.x) + "," + str(self.y) + ">"


def main():
    a = Vector(1, 2)
    b = Vector(-3, 0)
    c = a.add(b)
    print(c.show())
    print(a.show())
    print(b.show())
    print(c is a)
    d = a.scaled(0)
    print(d.show())
    print(a.scaled(-1).show())
    print(a.dot(b))
    print(a.add(Vector(0, 0)).show())
    e = Vector(0, 0)
    f = e.add(e)
    f.x = 9
    print(e.x)
    print(f.x)
    total = Vector(0, 0)
    for v in [a, b, c]:
        total = total.add(v)
    print(total.show())


main()
