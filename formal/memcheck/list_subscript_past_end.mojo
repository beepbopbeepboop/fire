# THE OUT-OF-RANGE SUBSCRIPT ROW, and the finding is NOT the one the first
# version of this comment claimed.
#
# First reading: "a[3] on a three-element list reads out of range with no
# bounds check".  That is WRONG, and it was wrong twice over.  The check was
# always there and always correct -- `formal/arm64_codegen.py`'s
# `_emit_subscript_addr` loads the blob's own count, applies Python's
# negative-index rule, and takes its `oob_label` arm unless `count > index`
# unsigned; the x86-64 emitter has the mirror of it in `_emit_bounds_check`.
# What was missing was the MESSAGE, so the arm called `exit(1)` having written
# nothing at all.
#
# What happens now, on both architectures, identically:
#
#     ./list_subscript_past_end.arm64 ; echo $?
#     10
#     30
#     formal: a[3] is out of range -- index 3 is not below the 3 elements the
#     blob holds. CPython raises `IndexError: list index out of range` ...
#     1
#
# and the message lands on STDERR, so the two in-range lines are all that
# reaches stdout and nothing is appended to them.  The row stays because a
# memcheck sweep reports it MATCH -- the answer and the exit status are both
# stable -- and a reader who takes the older comment at its word will go
# looking for a check that is already there.
def main(n: Int) -> Int:
    var a = [10, 20, 30]
    printf("%d\n", a[0])
    printf("%d\n", a[2])
    printf("%d\n", a[3])
    return 0
