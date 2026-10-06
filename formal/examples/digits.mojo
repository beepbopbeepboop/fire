# A divide-and-modify PAIR inside a loop: the classic digit loop, where one
# iteration needs both halves of the same division and the remainder feeds the
# next round.
def digits(n):
    count = 0
    v = n
    while v != 0:
        v = v // 10
        count = count + 1
    return count
