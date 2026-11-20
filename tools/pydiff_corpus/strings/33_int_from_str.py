def parse(s: str) -> int:
    return int(s)


def main():
    print(int("42"))
    print(int("-17"))
    print(int("+8"))
    print(int("  12  "))
    print(int("007"))
    print(int("0"))
    print(parse("-0"))
    print(str(123))
    print(str(-45) + "!")
    print(len(str(-45)))
    print(int("1_000"))
    print(int("12") + int("30"))
    print(int(True))
    print(int(3.9))
    print(int(-3.9))
    print(int("9" * 20))


main()
