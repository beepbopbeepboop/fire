# `T if c else ~T` lowers to `cmp x0, #0 ; ... ; csinv x0, x0, x0, ne` (step 07b).
# `c` is a constant here on purpose: it proves with 0 sorries and the image still
# carries exactly one CSINV word. With an input-dependent condition
# (`return t if n > 5 else ~t`) the machine code is the same single CSINV but the
# generated proof ends in one `walk-terminal` leaf the generator cannot close (a
# proof-generator limit shared with the other two-branch examples, not a CSINV one).
def f(n):
    c = 1
    t = n
    return t if c else ~t
