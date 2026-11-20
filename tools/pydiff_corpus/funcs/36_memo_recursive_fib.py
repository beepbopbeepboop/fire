def fib(n, memo):
    if n in memo:
        return memo[n]
    if n < 2:
        result = n
    else:
        result = fib(n - 1, memo) + fib(n - 2, memo)
    memo[n] = result
    return result


def main():
    memo = {}
    print(fib(0, memo))
    print(fib(1, memo))
    print(fib(10, memo))
    print(fib(30, memo))
    print(len(memo))
    print(fib(5, {}))
    print(fib(2, memo))
    print(len(memo))
    print(sorted(memo.items())[:4])
    print(fib(30, memo) == 832040)


main()
