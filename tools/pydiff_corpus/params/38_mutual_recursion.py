def is_even(n: int) -> bool:
    if n == 0:
        return True
    return is_odd(n - 1)


def is_odd(n: int) -> bool:
    if n == 0:
        return False
    return is_even(n - 1)


def collatz_steps(n):
    if n <= 1:
        return 0
    if n % 2 == 0:
        return 1 + collatz_steps(n // 2)
    return 1 + collatz_steps(3 * n + 1)


def main():
    print(is_even(0))
    print(is_odd(0))
    print(is_even(7))
    print(is_odd(7))
    print(is_even(10) and is_odd(3))
    print(is_odd(4) or is_even(4))
    print(collatz_steps(1))
    print(collatz_steps(6))
    print(collatz_steps(7))
    print(collatz_steps(0))


main()
