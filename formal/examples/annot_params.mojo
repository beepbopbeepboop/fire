# Annotated parameters and an annotated return: the entry's own signature is
# the one the startup stub calls through, and every parameter here is typed.
def annot_params(n: Int, m: Int) -> Int:
    return n * m + 1
