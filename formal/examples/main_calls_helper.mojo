# THE SAME IMAGE as `call_helper`, with the CALLER as the entry. The two
# examples differ in one line -- which function the startup stub branches to --
# and they get opposite verdicts, which is the sharpest statement in the corpus
# of where the arm64 proof layer's frontier is.
#
# `call_helper` proves: its entry is the CALLEE, so the call in `call_helper`
# (the caller) is a call the CFG walk reaches from a block whose `x30` it
# already knows. Here the entry IS the caller, and the walk refuses:
#
#     universal theorem: the call at 0x... targets 0x..., a second function in
#     the same image. The machine model follows it -- every byte is present,
#     and the callee's `ret` returns through `x30` -- but the CFG walk is
#     per-function, and following the call means entering the callee's blocks
#     and then dispatching on `x30`, whose value is a property of the call
#     path rather than of the block.
#
# So "an entry that calls something" is refused and "a callee that is the
# entry" is not, and the corpus says so in two rows instead of one. See
# `bugs/FORMAL_arm64_the_universal_theorem_cannot_follow_a_call_into_the_same_
# image.md`, which measures the same refusal over the breadth census.
def helper(a):
    return a + 3


def main(n):
    return helper(n) + 1
