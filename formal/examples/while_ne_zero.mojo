# `while x != 0` with the counter decremented to zero: the loop test is the
# non-negativity of a counter the program itself drives to zero, which is the
# shape `countdown`/`wge` get wrong.
def while_ne_zero(n):
    i = n
    total = 0
    while i != 0:
        total = total + i
        i = i - 1
    return total & 255
