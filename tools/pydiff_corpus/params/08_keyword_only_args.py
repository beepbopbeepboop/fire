def area(*, width, height=1):
    return width * height


def main():
    print(area(width=3))
    print(area(height=4, width=5))
    print(area(width=0, height=9))
    print(area(width=-2, height=3))
    print(area(height=2, width=2.5))
    print(area(width="ab", height=2))
    print(area(width=[1], height=3))
    try:
        area(3, 4)
    except TypeError:
        print("positional rejected")
    try:
        area(height=2)
    except TypeError:
        print("width missing")


main()
