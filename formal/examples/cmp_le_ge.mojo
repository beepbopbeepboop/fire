# `<=` and `>=` on two VARIABLES (the corpus pins them mostly against
# literals), so the comparison has to lower both directions.
def cmp_le_ge(n):
    a = n
    b = 3
    if a <= b:
        return 1
    if a >= b:
        return 2
    return 0
