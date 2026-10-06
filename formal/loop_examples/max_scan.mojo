# MAX SCAN, the mirror of `min_scan.mojo`: same structure, `>` for `<`, and the
# same verdict — the counter's variant `6 - i` is synthesised and proved, the
# accumulator's is refused with the subscript named, and the value is UNKNOWN.
def max_scan(n):
    a = [7, 3, 9, 2, 8, 1]
    best = a[0]
    for i in range(1, 6):
        if a[i] > best:
            best = a[i]
    return best
