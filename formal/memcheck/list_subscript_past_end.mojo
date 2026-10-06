# THE OUT-OF-RANGE SUBSCRIPT ROW, and the finding is NOT the one the first
# version of this comment claimed.
#
# First reading: "a[3] on a three-element list reads out of range with no
# bounds check".  That is WRONG, and the correction is the reason the row
# exists.  `formal/arm64_codegen.py`'s `_emit_subscript_addr` loads the blob's
# own count, applies Python's negative-index rule, and takes an `oob_label` arm
# unless `count > index` unsigned; the x86-64 emitter has the mirror of it in
# `_emit_bounds_check`.  The check is there and it is correct.
#
# What it used to do instead, on both architectures, identically: stop.  The
# image printed the two in-range elements and exited 1 having written NOTHING
# AT ALL -- not stdout, not stderr (measured: 0 bytes on stderr) -- while every
# other bounded stop on this path called `_emit_overflow_diagnostic` first and
# said which bound was hit.  A program whose only symptom is that it stopped is
# the worst of the three answers this backend can give, and it is also the one
# a stdout/exit-status oracle cannot see: this row reports MATCH both before
# and after, which is exactly why the silence needed its own bug doc rather
# than a memcheck verdict.
#
# NOW IT SAYS SO, on both architectures and with the same bytes:
#
#     formal: subscript a[3] is out of range. This path reads the container's
#     own element count out of its blob header, ... and nothing has been read.
#     ... CPython answers the same program with `IndexError: list index out of
#     range` on stderr.
#
# `formal/model.py`'s `subscript_out_of_range_message` is the one text, so the
# two machines cannot name this limit differently, and
# `test_formal_run.py`'s `out_of_range_subscript_is_loud` /
# `out_of_range_negative_subscript_is_loud` rows assert it on both
# architectures byte for byte.  The row here stays because a reader who takes
# the OLD comment at its word will go looking for a check that is already there.
def main(n: Int) -> Int:
    var a = [10, 20, 30]
    printf("%d\n", a[0])
    printf("%d\n", a[2])
    printf("%d\n", a[3])
    return 0