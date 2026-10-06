# A loop that keeps a RUNNING MAXIMUM, with the comparison inside the body
# deciding whether the accumulator is replaced: a conditional store to a slot
# the loop reads again at the latch.
def accum_max(n):
    best = 0
    i = 1
    while i != n:
        if i > best:
            best = i
        i = i + 1
    return best
