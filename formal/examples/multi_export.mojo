# THREE exports, and the entry is the only one that CALLS anything: the startup
# stub branches to `main`, so `scale` and `shift` are reachable code the image
# must still emit and the run test must still execute. Two nested calls are two
# call SITES on one path, which is more than the arm64 CFG walk can follow --
# see `main_calls_helper` for the refusal this shape produces and
# `call_helper` for the one call site it can.
def scale(a):
    return a * 2


def shift(a):
    return a + 1


def main(n):
    return scale(shift(n))
