def countdown(n: int):
    i = n
    while i > 0:
        yield i
        i -= 1


def evens(limit):
    for i in range(limit):
        if i % 2 == 0:
            yield i


def main():
    for v in countdown(3):
        print(v)
    print("---")
    for v in countdown(0):
        print("never", v)
    print("empty ok")
    total = 0
    for e in evens(7):
        total += e
    print(total)
    for e in evens(-5):
        print("never", e)
    print([x for x in evens(4)])
    for a, b in zip(countdown(2), evens(10)):
        print(a, b)


main()
