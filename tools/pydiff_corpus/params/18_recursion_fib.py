def fib(n):
    if n < 2:
        return n
    return fib(n - 1) + fib(n - 2)


def fib_pair(n: int):
    if n == 0:
        return 0, 1
    a, b = fib_pair(n - 1)
    return b, a + b


def main():
    print(fib(0))
    print(fib(1))
    print(fib(2))
    print(fib(7))
    print(fib(-4))
    print(fib(12))
    print(fib_pair(0))
    print(fib_pair(7))
    print(fib_pair(7)[0] == fib(7))
    print(fib_pair(20)[0])


main()
