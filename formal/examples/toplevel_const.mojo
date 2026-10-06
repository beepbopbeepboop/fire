# A module-level CONSTANT read inside a function. The store folds, so the read
# is a literal at the use site and the program's only top-level statement is
# not a statement at all.
LIMIT = 12


def toplevel_const(n):
    if n > LIMIT:
        return LIMIT
    return n
