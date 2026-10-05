# `min` as a CLAUSE, not as a call.  `@ensures(result <= max(n, 3))` is a
# promise about the value the function returns, written with the builtin the
# reader would use to state it -- and `formal/contracts.py` renders that builtin
# as the selection `omega` can split, rather than as a call into a library
# function the tactic ladder cannot unfold.
@requires(n >= 0)
@ensures(result <= max(n, 3))
@ensures(result >= min(n, 3))
def mini(n):
    if n < 3:
        return n
    else:
        return 3
