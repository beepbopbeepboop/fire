def double(x):
    return x * 2


def negate(x):
    return -x


def shout(s):
    return s.upper() + "!"


def apply_once(fn, value):
    return fn(value)


def apply_to_all(fn, items):
    out = []
    for x in items:
        out.append(fn(x))
    return out


def main():
    print(apply_once(double, 5))
    print(apply_once(negate, 0))
    print(apply_once(shout, ""))
    print(apply_once(negate, -3))
    print(apply_to_all(double, [1, -2, 0]))
    print(apply_to_all(double, []))
    print(apply_to_all(shout, ["a", ""]))
    print(apply_to_all(negate, [True, False]))
    print(apply_once(apply_once, double) if False else "skipped")


main()
