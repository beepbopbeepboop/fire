def is_even(n: int) -> bool:
    if n == 0:
        return True
    return is_odd(n - 1)


def is_odd(n: int) -> bool:
    if n == 0:
        return False
    return is_even(n - 1)


def main():
    for n in [0, 1, 2, 7, 10, 15]:
        print(n, is_even(n), is_odd(n))
    print(is_even(0) and is_odd(0))
    print(is_odd(1) or is_even(1))
    print(not is_even(3))
    print(is_even(4), is_odd(4))
    evens = [n for n in range(9) if is_even(n)]
    print(evens)


main()
