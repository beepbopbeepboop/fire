# An `elif` chain whose TEST is a CALL: the call sits on a branch that is not
# the last one, so its result is live into the following compare. `scaled` is
# the entry, so the two calls are one per path -- the shape the walk can
# discharge, unlike `multi_export`'s two on one path.
def scaled(a):
    return a * 2


def elif_call(n):
    if scaled(n) > 20:
        return 3
    elif scaled(n) > 10:
        return 2
    return 1
