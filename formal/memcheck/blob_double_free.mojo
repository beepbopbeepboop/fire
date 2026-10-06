from os._syscalls import str_alloc, fs_free

# THE DOUBLE-FREE ROW.  The malloc zone's own free list must notice the second
# `free` of the same pointer: measured 2026-10-05 on both architectures, the
# process aborts (SIGABRT, exit 134) with the first `fs_free` having printed 0.
# `MallocScribble` + `MallocErrorAbort` are what turn a detected corruption into
# that abort instead of a silent second release into the wrong bin, so this row
# is reported CRASH by every sweep -- and that is the verdict it exists to
# produce.  The companion that has to stay MATCH is `blob_alloc_free`, which is
# the same shape without the second free.
def main(n: Int) -> Int:
    var p: Pointer[UInt8] = str_alloc(64)
    p[0] = 65
    printf("first=%d\n", fs_free(p))
    printf("second=%d\n", fs_free(p))
    return 0
