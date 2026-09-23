@spec(sum_spec; sum_spec 0 = 0; sum_spec (n+1) = (n+1) + sum_spec n)
@require(n >= 0)
@ensure(result >= 0)
def sum(n):
    if n == 0:
        return 0
    else:
        return n + sum(n - 1)
