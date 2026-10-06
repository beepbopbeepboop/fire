# WHERE THE RUN-TIME CHECK EARNS ITS KEEP.
#
# This contract is FALSE (`sum_to(3)` is 3, not 1000) and the bounded search
# CANNOT REFUTE IT, because `formal/contracts.py`'s `SourceRunner` does not
# model a `for` loop and reports UNKNOWN with that named.  So the build goes
# through under `--check-contracts` -- and the check, which is in the image,
# fires on the first run.
#
# That is the whole division of labour.  The theorem and the search reason
# about the MODEL over a FINITE set of inputs; the run-time check is about
# THIS run, and it is the only one of the three that needs no search to have
# covered the input it is looking at.
@requires(n >= 0)
@ensures(result >= 1000)
def sum_to(n):
    total = 0
    for i in range(n):
        total = total + i
    return total
