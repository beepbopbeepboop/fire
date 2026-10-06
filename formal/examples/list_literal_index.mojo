# A list literal read at CONSTANT indices: the blob's layout is known at build
# time, so this is the subscript path that does not need a runtime index.
def list_literal_index(n):
    a = [3, 5, 7]
    return a[0] + a[1] + a[2]
