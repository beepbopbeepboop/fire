BASE = 4
LIMIT = BASE * 2


def scale(x, factor=BASE):
    return x * factor


def clamp(x, hi=LIMIT, lo=0):
    if x > hi:
        return hi
    if x < lo:
        return lo
    return x


def main():
    print(scale(3))
    print(scale(3, 1))
    print(scale(0))
    print(scale(-2))
    print(clamp(20))
    print(clamp(-5))
    print(clamp(5))
    print(clamp(5, 3))
    print(clamp(-5, lo=-10))
    print(clamp(100, hi=50, lo=60))
    print(LIMIT, BASE)


main()
