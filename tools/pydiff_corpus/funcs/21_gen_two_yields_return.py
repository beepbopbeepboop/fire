def two_step(x):
    yield x
    yield x * 2
    return "finished"


def main():
    print(list(two_step(1)))
    print(list(two_step(0)))
    print(list(two_step(-4)))
    g = two_step(5)
    print(next(g))
    print(next(g))
    try:
        next(g)
    except StopIteration as stop:
        print("value:", stop.value)
    for v in two_step(3):
        print("got", v)
    print(sum(two_step(10)))
    print(len(list(two_step(None))) if False else "skipped")


main()
