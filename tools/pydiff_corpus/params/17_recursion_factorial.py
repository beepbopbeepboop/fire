def factorial(n: int) -> int:
    if n < 0:
        return -1
    if n <= 1:
        return 1
    return n * factorial(n - 1)


def count_down(n):
    if n == 0:
        return []
    return [n] + count_down(n - 1)


def main():
    print(factorial(0))
    print(factorial(1))
    print(factorial(5))
    print(factorial(10))
    print(factorial(-3))
    print(factorial(20))
    print(count_down(3))
    print(count_down(0))
    print(len(count_down(6)))


main()
