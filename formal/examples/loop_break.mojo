# `break` out of a loop: the exit edge is a branch to the block AFTER the loop
# from inside the body, beside the loop's own compare-driven exit.
def loop_break(n):
    i = 0
    while i != n:
        if i > 4:
            break
        i = i + 1
    return i
