# `!=` as a loop's own test and as a branch: the corpus has `==` everywhere
# and one `!=` loop, so the negated comparison is pinned here as an
# expression too.
def cmp_ne(n):
    if n != 4:
        return 1
    return 0
