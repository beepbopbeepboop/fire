# TWO exports and a call between them: the callee is a real BL to a defined
# symbol, so this is the smallest image with a call in it, and it PROVES.
#
# The entry is the CALLEE, not the caller -- `model.entry_function` takes the
# first `def` in source order when there is no `main`. That is deliberate here
# and it is the whole of the difference from `main_calls_helper`, which is this
# program with the two functions swapped: there the entry is the caller and the
# arm64 proof generator refuses, because the CFG walk that carries the entry's
# blocks cannot follow a call out of the entry. Read the two together.
def helper(a):
    return a * 3


def call_helper(n):
    return helper(n) + 1
