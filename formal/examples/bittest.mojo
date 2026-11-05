# An `if` whose condition is a BIT TEST — the two instructions, one each.
#
# `if n & 8:` lowers to a single TBZ and `if not (n & 4):` to a single TBNZ, so
# the branch that carries this program's whole control flow writes no register
# and sets no flags. That is why proving it was a separate piece of work from
# encoding it: a conditional branch's source-level proposition used to be read
# out of the CSET that wrote the tested register, and there is no CSET here, so
# the generator refused with `unsupported: branch condition value flow
# (frame/flag unavailable)` — the correct failure, and the wrong stopping point.
# Both spellings are here because the polarity is the whole of the difference:
# the bit CLEAR is TBZ's test and TBNZ's is the bit SET.
#
# **The third shape the doc's example had, `if 16 & n:` — the mask written the
# other way round — is not here, and the reason is not the bit test.** It emits
# the same TBZ as the first branch (`&` is commutative in Python and the
# lowering accepts either order, `arm64_codegen.py`'s `_bit_test_mask`), but
# adding a third conditional branch to a function of this shape puts the
# WHOLE-PROGRAM certificate over Lean's bound: measured on this tree, two
# branches prove and three do not, and the control is that the same three
# branches spelled as ordinary COMPARISONS (`n > 8`, `not (n < 4)`, `16 < n`)
# fail the same way — `lean exceeded 1500s wall`. So the limit is a property of
# the certificate's size and not of the instruction, and it is written down in
# `bugs/FORMAL_a_three_branch_certificate_exceeds_the_lean_bound.md`.
def bittest(n):
    x = 0
    if n & 8:
        x = x + 1
    if not (n & 4):
        x = x + 2
    return x
