# THE OUT-OF-RANGE SUBSCRIPT ROW, and the finding is NOT the one the first
# version of this comment claimed.
#
# First reading: "a[3] on a three-element list reads out of range with no
# bounds check".  That is WRONG, and the correction is the reason the row
# exists.  `formal/arm64_codegen.py`'s `_emit_subscript_addr` loads the blob's
# own count, applies Python's negative-index rule, and takes an `oob_label` arm
# unless `count > index` unsigned; the x86-64 emitter has the mirror of it.
# The check is there and it is correct.
#
# What actually happens, on both architectures, identically:
#
#     ./list_subscript_past_end.arm64 ; echo $?
#     10
#     30
#     1
#
# The image prints the two in-range lines and then stops with exit 1 having
# written NOTHING AT ALL -- not stdout, not stderr (measured: 0 bytes on
# stderr).  Every other bounded stop on this path calls
# `_emit_overflow_diagnostic` first and says which bound was hit; this one does
# not.  CPython answers the same program with `IndexError: list index out of
# range`, on stderr.
#
# Filed as `bugs/FORMAL_an_out_of_range_subscript_exits_1_with_no_message.md`.
# The row stays because a memcheck sweep reports it MATCH -- the answer and the
# exit status are both stable -- and a reader who takes the old comment at its
# word will go looking for a check that is already there.
def main(n: Int) -> Int:
    var a = [10, 20, 30]
    printf("%d\n", a[0])
    printf("%d\n", a[2])
    printf("%d\n", a[3])
    return 0
