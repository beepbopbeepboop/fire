@spec(count_spec; count_spec 0 = 0; count_spec (n+1) = count_spec n)
@require(n >= 0)
def count(n):
    if n == 0:
        return 0
    else:
        return count(n - 1)