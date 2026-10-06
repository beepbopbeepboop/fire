# SPECIFICATION REFINEMENT.  Every other theorem this build emits compares the
# machine with the generator's OWN model of this source, so all of them are
# self-consistency theorems: code and model are two readings of this file.
# The `@refines` annotation below asks for the stronger claim -- that the
# machine computes the HAND-WRITTEN specification of the absolute value, read SIGNED in
# `lib/Specs.lean`, which is defined over Lean's own Nat and has no
# reference to this file, to `mojo`, or to `ProofLib`'s machine model.  It
# produces `main_refines_spec`, and the range is the author's because a word
# reading is `UInt64.ofNat` of a mathematical value and the equation is false
# wherever that value does not fit in a word.
@refines(Specs.abs64; 64)
def absval(n):
    if n > 0:
        return n
    else:
        return 0 - n
