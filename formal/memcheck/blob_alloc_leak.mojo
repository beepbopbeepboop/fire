from os._syscalls import str_alloc

# THE LEAK ROW.  64 round trips through the runtime dylib's allocator with no
# `fs_free`, so the process exits holding 64 buffers and `leaks --atExit`
# reports 64 root leaks.  Nothing here is a miscompile: the program simply never
# frees.  It is in the corpus because a memcheck tool whose LEAK verdict has
# never fired is a tool whose LEAK verdict is untested, and this is the row that
# fires it.
#
# `printf("%d", p[0])` rather than `print(p[0])`: a bare `print` of a subscript
# through a `Pointer[UInt8]` is REFUSED by name on both architectures ("cannot
# tell whether SubscriptExpr is a string or a number"), which is correct -- it
# genuinely cannot tell -- so the corpus says which it is.
#
# EVERY LOCAL IS INITIALISED, and that is not style.  `var i: Int` with no
# initialiser is an UNBOUND local on this path, and a program that reads one in
# a loop condition does not get a wrong answer -- it does not terminate: the
# first version of this row was `while i < 64:` over an uninitialised `i`, and
# it allocated until the machine ran out of memory (15 GB RSS measured, killed).
# A runaway is the most expensive thing this corpus can do and it is one
# uninitialised word away, so the corpus initialises.
def main(n: Int) -> Int:
    var i: Int = 0
    var total: Int = 0
    while i < 64:
        var p: Pointer[UInt8] = str_alloc(64)
        p[0] = 65
        printf("b=%d\n", p[0])
        total = total + p[0]
        i = i + 1
    printf("total=%d\n", total)
    return 0
