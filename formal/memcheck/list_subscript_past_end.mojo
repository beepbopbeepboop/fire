# THE OUT-OF-RANGE SUBSCRIPT ROW, and the finding is NOT the one the first
# version of this comment claimed.
#
# First reading: "a[3] on a three-element list reads out of range with no
# bounds check".  That is WRONG, and the correction is the reason the row
# exists.  `formal/arm64_codegen.py`'s `_emit_subscript_addr` loads the blob's
# own count, applies Python's negative-index rule, and takes an `oob_label` arm
# unless `count > index` unsigned; the x86-64 emitter has the mirror of it
# (`_emit_bounds_check`).  The check is there and it is correct.
#
# What the row DID find, on both architectures identically, was that the stop
# said nothing:
#
#     ./list_subscript_past_end.arm64 ; echo $?
#     10
#     30
#     formal: a[3] is out of range -- index 3 is not below the 3 elements the
#     blob holds. CPython raises `IndexError: list index out of range` ...
#     1
#     2>&1 1>/dev/null | wc -c   ->   0
#
# and it does now:
#
#     ./list_subscript_past_end.arm64 2>&1 1>/dev/null
#     formal: `a[3]` is out of range for this list: the subscript asked for an
#     element at or past the end of what the list holds, ...
#
# `model.subscript_out_of_range_message` is the text and BOTH emitters print
# it through `_emit_overflow_diagnostic`, so the two architectures say the same
# sentence byte for byte; `test_formal_run.py`'s `STDERR_CASES` rows
# `subscript_out_of_range_is_loud` (read), `subscript_store_out_of_range_is_loud`
# (store) and `subscript_out_of_range_negative_is_loud` (`a[-4]`) are what keep
# it that way.
#
# The row STAYS, and the reason is the sentence above it: a memcheck sweep
# compares stdout and the exit status, so a bounds check that stops the program
# is indistinguishable from a correct one -- this row was reported `MATCH` while
# the stop printed nothing at all.  That is also why the message needs a suite
# that looks at stderr and not this one, and why a reader who takes the FIRST
# comment at its word will go looking for a check that is already there.
def main(n: Int) -> Int:
    var a = [10, 20, 30]
    printf("%d\n", a[0])
    printf("%d\n", a[2])
    printf("%d\n", a[3])
    return 0