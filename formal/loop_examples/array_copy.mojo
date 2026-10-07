# ARRAY COPY.  The body reads one subscript and stores it through another, and
# the loop's test is `i != 3` — the same unprovable termination as
# `array_fill.mojo`, which is the point of having both: the row is not a
# one-program accident.
def array_copy(n):
    a = [3, 5, 8]
    b = [0, 0, 0]
    i = 0
    while i != 3:
        b[i] = a[i]
        i = i + 1
    return b[0] + b[1] + b[2]
