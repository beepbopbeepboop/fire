def make_counter():
    count = 0

    def tick(step):
        nonlocal count
        count += step
        return count

    return tick


def main():
    c = make_counter()
    print(c(1))
    print(c(1))
    print(c(0))
    print(c(-1))
    print(c(5))
    d = make_counter()
    print(d(0))
    print(c(0))
    print(d(-3))
    print(c(-10))


main()
