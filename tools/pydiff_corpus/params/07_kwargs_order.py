def make_point(x: int, y: int, z: int = 0) -> tuple:
    return (x, y, z)


def main():
    print(make_point(1, 2))
    print(make_point(y=2, x=1))
    print(make_point(z=9, y=-2, x=0))
    print(make_point(3, z=-1, y=4))
    print(make_point(x=-5, y=0))
    print(make_point(0, 0, 0))
    print(make_point(y=7, x=7, z=7) == make_point(7, 7, 7))
    print(make_point(x=1, y=2) == make_point(y=2, x=1))
    print(make_point(1, 2, z=3) == make_point(1, 2, 3))


main()
