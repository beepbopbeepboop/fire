def strip(s: str) -> str:
    return s.strip()


def double(s: str) -> str:
    return s + s


def shout(s: str) -> str:
    return s.upper() + "!"


def pipeline(s):
    return shout(double(strip(s)))


def compose3(f, g, h):
    return lambda x: f(g(h(x)))


def main():
    print(pipeline("  ab "))
    print(pipeline(""))
    print(pipeline("   "))
    print(pipeline("x"))
    p = compose3(shout, double, strip)
    print(p(" x "))
    print(p("Mo"))
    s = "  Hi  "
    for fn in [strip, double, shout]:
        s = fn(s)
        print(s)
    print(pipeline(pipeline("a")))


main()
