from os._syscalls import str_alloc, fs_free

# THE USE-AFTOR-FREE ROW, written as a CLASSIFICATION rather than as the byte.
#
# The first version printed `p[0]` after `fs_free(p)` and expected the memcheck
# sweep to report SCRIBBLE-DIVERGES -- plain reads 0, `MallocScribble` reads
# 0x55 -- which is true and is useless as a ledger row, because the byte is
# genuinely undefined and its value depends on whether `printf` happened to
# reuse the chunk: measured over four sweeps, `after=` came back 0 five times
# and 160 once.  A row whose verdict flips run to run cannot be a baseline, and
# a DRIFT report that fires on a coin flip teaches nothing.
#
# So the row answers the question it is actually about.  `freed_is_mine` is 1 if
# and only if the byte still holds the 65 that was stored in it, which means the
# read came from somewhere the program's write is still visible -- a cached
# value, an alias the compiler invented, anything that is not a read of freed
# memory.  Every instrument agrees that it is 0:
#
#     plain     the chunk reads 0
#     scribble  the chunk reads 0x55 (85)
#     poison    the chunk is on the HEAP, so the stack paint does not reach it
#
# and if the backend ever stops reading the freed chunk, this row says 1 on all
# three at once and the sweep reports a divergence against itself.  That is the
# regression worth having: the assertion lives in the program, so it survives
# the instrument being unavailable, and the instrument still gets to say so.
def main(n: Int) -> Int:
    var p: Pointer[UInt8] = str_alloc(64)
    p[0] = 65
    p[1] = 0
    printf("before=%d\n", p[0])
    printf("free=%d\n", fs_free(p))
    var still: Int = 0
    if p[0] == 65:
        still = 1
    printf("freed_is_mine=%d\n", still)
    return 0
