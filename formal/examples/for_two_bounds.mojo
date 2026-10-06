# A two-argument `range` with a NEGATIVE step's counterpart: the counter runs
# up to a bound and the loop's exit is the comparison against it.
def for_two_bounds(n):
    total = 0
    for i in range(1, n):
        total = total + i
    return total
