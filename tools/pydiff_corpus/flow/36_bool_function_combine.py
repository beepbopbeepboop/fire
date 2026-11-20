def is_even(n: int) -> bool:
    return n % 2 == 0


def is_positive(n):
    return n > 0


def is_short(text: str) -> bool:
    return len(text) < 4


def check_all(n: int, text: str):
    even = is_even(n)
    positive = is_positive(n)
    short = is_short(text)
    print("even", even, "positive", positive, "short", short)
    both = even and positive
    either = even or positive
    print("both", both, "either", either)
    print("exactly one", even != positive)
    print("not short", not short)
    print("combined", (even or short) and not positive)
    return both


def main():
    r1 = check_all(4, "ab")
    r2 = check_all(-3, "abcdef")
    r3 = check_all(0, "")
    print(r1, r2, r3)
    print(r1 + r3)
    results = [is_even(x) for x in [-2, -1, 0]]
    print(results)
    print(sum(results))
    print(all(results), any(results))
    print(is_positive(0) == False)
    print(is_even(7) or is_short("x") and is_positive(9))


main()
