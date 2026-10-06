# A three-argument call: the register/frame split for arguments, and the
# model's binding of all three at the call site. `add3` is the entry (first
# `def` in source order), so the startup stub hands it ten and two zeros and
# the run test crosses the three-argument frame directly.
def add3(a, b, c):
    return a + b + c


def call_three(n):
    return add3(n, 2, 3)
