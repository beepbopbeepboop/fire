# THE LADDER REACHES THIS ONE.  `mini2`'s contract is discharged by the
# generated `f_contract` theorem, and `test_formal_contracts.py --lean` is what
# checks that it is discharged rather than merely emitted.
#
# It is here because a checker that is only ever run against contracts it
# cannot decide measures nothing about the ladder.  `mini.mojo` next to it is
# the other half: same shape, a clause written with the `min`/`max` builtins,
# and the ladder does NOT reach it -- so its verdict is UNKNOWN, loudly, which
# is the answer and not a failure of the file.
@requires(a <= b)
@ensures(result <= b)
def mini2(a, b):
    if a < b:
        return a
    else:
        return b
