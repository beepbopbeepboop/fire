# An early return in the middle of a branch chain: the second test is only
# reached when the first one fails, so the image has a branch whose TARGET is a
# second compare rather than a join.
def early_ret(n):
    if n > 100:
        return 1
    if n > 50:
        return 2
    return 3
