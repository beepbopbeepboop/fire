# `printf` with one integer argument and a newline: the call crosses into the
# runtime with a word argument and returns nothing, so the exit status has to
# come from a separate return.
def printf_int(n):
    printf("%d\n", n)
    return 7
