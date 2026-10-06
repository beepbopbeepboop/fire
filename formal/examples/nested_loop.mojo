# Nested loops: the inner counter is re-initialised on every pass of the outer
# one, so the image carries two loop-invariant counters and one back edge into
# a body that is entered from two depths.
def nested_loop(n):
    total = 0
    i = 0
    while i != n:
        j = 0
        while j != i:
            total = total + 1
            j = j + 1
        i = i + 1
    return total
