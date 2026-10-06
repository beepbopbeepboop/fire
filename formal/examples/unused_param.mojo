# A parameter that is never read, in a function that also returns a computed
# value: the argument register is written by the caller and never consumed.
def unused_param(n, m):
    return n + 1
