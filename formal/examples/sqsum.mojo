def sqsum(n):
    if n == 0:
        return 0
    else:
        return n * n + sqsum(n - 1)
