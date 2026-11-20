class Temp:
    def __init__(self, degrees: int):
        self.degrees = degrees

    def __add__(self, other):
        return Temp(self.degrees + other.degrees)

    def __sub__(self, other):
        return Temp(self.degrees - other.degrees)

    def __eq__(self, other):
        return isinstance(other, Temp) and self.degrees == other.degrees

    def __str__(self):
        return str(self.degrees) + "C"


def main():
    a = Temp(20)
    b = Temp(-5)
    print(a + b)
    print(a - b)
    print(b - a)
    print(str(a + a))
    z = Temp(0)
    print(z + z == z)
    print(a + z == a)
    print(a + b == Temp(15))
    print(a is a + z)
    total = Temp(0)
    for t in [a, b, Temp(3)]:
        total = total + t
    print(total)
    print(str(a))
    print(a.degrees)
    print(b.degrees)


main()
