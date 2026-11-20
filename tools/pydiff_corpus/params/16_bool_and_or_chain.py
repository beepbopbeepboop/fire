def is_positive(n: int) -> bool:
    return n > 0


def is_small(n):
    return n < 10


def is_even(n):
    return n % 2 == 0


def check_all(n):
    return is_positive(n) and is_small(n) and is_even(n)


def check_any(n):
    return is_positive(n) or is_even(n)


def main():
    print(check_all(4))
    print(check_all(5))
    print(check_all(-2))
    print(check_all(12))
    print(check_any(-3))
    print(check_any(-4))
    print(check_any(0))
    print(0 or "fallback")
    print("" or [] or None)
    print(3 and "kept")
    print(0 and "never")
    print(None or False)
    print(check_all(2) and check_any(2))


main()
