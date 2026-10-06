# `len` over a list literal: the count is a header read, and the image stores
# it, so the call is a load and an add rather than arithmetic on the elements.
def list_len(n):
    a = [1, 2, 3, 4]
    return len(a)
