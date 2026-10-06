# A branch on a CONSTANT. The arm that cannot be taken still has to be laid
# out and still has to be proved unreachable rather than dropped, so this is
# the path where constant folding meets control flow.
def dead_branch(n):
    if 1:
        return n + 1
    else:
        return 0
