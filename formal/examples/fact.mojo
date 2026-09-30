@spec(fact_spec; fact_spec 0 = 1; fact_spec (n+1) = (n+1) * fact_spec n)
@require(n >= 0)
@ensure(result >= 0)
def fact(n):
    if n == 0:
        return 1
    else:
        return n * fact(n - 1)
