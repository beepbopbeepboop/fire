# An ANNOTATED `var` declared inside a loop body: the declaration is executed
# on every iteration and its slot is the loop's, not the frame's.
def var_typed_loop(n):
    i = 0
    total = 0
    while i != n:
        var step: Int = i + 1
        total = total + step
        i = step
    return total
