# A long straight-line arithmetic chain: the register allocator has to spill,
# so the frame layout and the spill offsets are what is under test.
def wide_expr(n):
    a = n + 1
    b = a * 2
    c = b + 3
    d = c - 4
    e = d * 5
    f = e + 6
    g = f * 7
    h = g - 8
    i = h + 9
    j = i * 10
    return j & 255
