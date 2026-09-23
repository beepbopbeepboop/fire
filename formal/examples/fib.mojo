@spec(fib_spec; fib_spec 0 = 0; fib_spec 1 = 1; fib_spec (n+2) = fib_spec n + fib_spec (n+1))
@require(n >= 0)
@ensure(result >= 0)
def fib(n):
    if n <= 1:
        return n
    else:
        return fib(n - 1) + fib(n - 2)
