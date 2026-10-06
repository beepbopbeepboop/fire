# A store that is never read, followed by a read of an EARLIER value: the
# image may or may not eliminate the store, and the proof has to agree with
# whichever it does.
def dead_store(n):
    a = n + 1
    a = 99
    return n
