from os._syscalls import str_alloc, str_put, fs_free

# THE CLEAN HEAP CASE.  Every program that has no `malloc` in it cannot be a
# memory-safety subject, so this one is the row the ledger needs: a program that
# allocates a buffer, writes through it by subscript, appends through the
# module's own writer, reads the bytes back, and frees.  It is the baseline
# against which every heap verdict below is read -- `LEAK` means "this differs
# from THIS", and there is nothing to differ from if this row does not exist.
def main(n: Int) -> Int:
    var p: Pointer[UInt8] = str_alloc(64)
    p[0] = 65
    p[1] = 66
    p[2] = 0
    print(p[0])
    print(p[1])
    print(p[40])
    print(str_put(p, 2, "ZZ", 2))
    print(p[0])
    print(p[1])
    print(p[2])
    print(p[3])
    print(fs_free(p))
    return 0
