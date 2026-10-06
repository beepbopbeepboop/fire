# TWO module-level bindings where the second is COMPUTED from the first, and
# both are read inside the entry. The chain has to fold through the module's
# own order rather than through use-site order, and the entry sees the folded
# value rather than a load.
SEED = 3
LIMIT = SEED + 4
SCALE = LIMIT * 2


def toplevel_accum(n):
    if n > LIMIT:
        return SCALE
    return LIMIT + n
