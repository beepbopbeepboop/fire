def squares(n):
    for i in range(n):
        yield i * i


def main():
    print(list(squares(4)))
    print(list(squares(0)))
    g = squares(3)
    print(next(g))
    print(next(g))
    print(next(g))
    try:
        next(g)
    except StopIteration:
        print("exhausted")
    print(next(g, "default"))
    h = squares(1)
    print(next(h, "default"))
    print(next(h, "default"))
    print(list(g))
    print(sum(squares(5)))


main()
