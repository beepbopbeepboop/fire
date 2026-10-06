from os._syscalls import str_alloc, fs_free

# THE OVERRUN ROW, AND A MEASURED LIMIT OF THE INSTRUMENT.
#
# A store 4096 bytes past a 64-byte buffer -- past the page the allocation ends
# on, so `MallocGuardEdges` ought to fault if the buffer's guard were where it
# is claimed to be.  Measured 2026-10-05, both architectures, both plain and
# under `MallocGuardEdges=1 MallocScribble=1 MallocPreScribble=1
# MallocCheckHeapStart=1 MallocErrorAbort=1`: the store lands in the heap, the
# program prints 65, exit 0.  Nothing in the backend faults and nothing should:
# `MallocGuardEdges` guards a rounded-up region, and a 64-byte request does not
# get one.  So this row is in the corpus as the row that MEASURES THE LIMIT --
# without it, a sweep that reported "no overrun detected" would be ambiguous
# between "the backend is safe" and "the instrument cannot see a 64-byte
# overrun", and those are very different sentences.
#
# The `fs_free` is there so the row is not also the leak row.
def main(n: Int) -> Int:
    var p: Pointer[UInt8] = str_alloc(64)
    p[0] = 65
    p[4096] = 66
    printf("b=%d\n", p[0])
    printf("free=%d\n", fs_free(p))
    return 0
