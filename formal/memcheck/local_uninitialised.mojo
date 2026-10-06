# THE READ-BEFORE-STORE ROW, which is a REFUSAL now.
#
# `var a: Int` with no `=` gives `a` a home and no value, and reading it is
# CPython's `UnboundLocalError`.  Before 2026-10-05 this program built, ran,
# exited 0, and printed an UNDEFINED value -- 1709223448 on arm64, 306062552 on
# x86-64 -- because both readers of "does this statement define its name" in
# `formal/model.py` (`_cfg_block_defs` and `_definitely_stored`) counted a
# `VarDecl` as a definition whatever its initialiser, so the
# `read_before_store` fixpoint believed `a` was stored before this read.  The
# instruments found it, not the corpus: `tools/formal_memcheck.py`'s stack and
# register poison reported the program NONDETERMINISTIC, because two plain runs
# of a straight-line program that disagree are only ever state nobody wrote.
# Under the poison it printed 0xa5a5a5a5a5a5a5a5 + 0xa5a5a5a5a5a5a5a5.
#
# So this row is now a REFUSAL, and it is here as the regression: if the
# declaration ever starts counting as a definition again, the row builds, runs,
# prints garbage, and reports NONDETERMINISTIC instead of REFUSED.  The live
# demonstration that the POISON still catches a read-before-write -- which this
# path can no longer be asked to lower -- is `test_formal_memcheck.py`'s
# `harness` group, where a C program with a deliberate one has to be caught.
def main(n: Int) -> Int:
    var a: Int
    var b: Int
    printf("%d\n", a + b)
    return 0
