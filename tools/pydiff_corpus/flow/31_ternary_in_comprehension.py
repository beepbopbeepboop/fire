def bucket(n: int) -> str:
    return "neg" if n < 0 else "zero" if n == 0 else "pos"


def main():
    vals = [-5, 0, 3, 12]
    print([bucket(v) for v in vals])
    print([v if v > 0 else None for v in vals])
    print([v or "empty" for v in [0, "", 4, None]])
    print([("odd" if v % 2 else "even") for v in range(4)])
    print([x * 2 if isinstance(x, int) else x.upper() for x in [1, "a", 3]])
    print([(v, "big" if v > 10 else "small") for v in [9, 11]])
    print(["yes" if c else "no" for c in [0, [], [0], ""]])
    print([n for n in range(6) if (n < 2 or n > 4)])


main()
