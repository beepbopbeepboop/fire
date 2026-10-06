# A call on BOTH arms of a branch: two call sites for one callee, so the
# argument evaluation and the return-value merge are both exercised per path.
# `square` is the entry, so the two call sites are reached by the WALK's
# per-function coverage rather than by the entry's own path -- which is why
# this image proves where `main_calls_helper`, with the same two call sites on
# one path out of the entry, does not.
def square(a):
    return a * a


def call_both_arms(n):
    if n > 0:
        return square(n)
    return square(0 - n)
