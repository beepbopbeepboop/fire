# LINEAR SEARCH.  The body RETURNS out of the loop on a subscripted read, so one
# iteration of this loop is not one iteration of the `for` shape the obligations
# are about — a candidate over it would be a claim about the leaving path.
# Reported UNREADABLE with that reason, which is the correct answer and is
# recorded rather than dropped.
def linear_search(n):
    a = [5, 8, 13, 21]
    i = 0
    while i != 4:
        if a[i] == 13:
            return i
        i = i + 1
    return 9
