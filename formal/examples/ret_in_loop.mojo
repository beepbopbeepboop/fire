# A RETURN out of the middle of a loop. The exit is a branch to the epilogue
# from inside the loop body, so the block that follows the loop is reachable
# from two predecessors and the proof has to carry the loop's live registers
# across both.
def ret_in_loop(n):
    i = 0
    total = 0
    while i != n:
        total = total + i
        if total > 20:
            return total
        i = i + 1
    return total
