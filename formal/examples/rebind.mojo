# A name bound twice in the same scope: the second store must overwrite the
# first in the same slot rather than allocate a second one.
def rebind(n):
    a = 1
    a = 2
    a = a + n
    return a
