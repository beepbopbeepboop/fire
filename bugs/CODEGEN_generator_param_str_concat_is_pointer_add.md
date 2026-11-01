# `root + str(k)` in a compiled generator with an unannotated `root` adds pointers

Found 2026-10-31 while closing item 2 of the (still open) dynamic-call-layer residue doc.

    # pkg/lib.py
    def walk(root, suffix=None):
        for k in range(3):
            yield root + str(k)
    # main.py
    from pkg import lib
    print(list(lib.walk("r")))      # CPython ['r0','r1','r2']; compiled ['43033668960', ...]

Same result in a single file (`fire` build of one module with `def walk(root)`).
`root` is an unannotated parameter typed `int64_t`; `root + str(k)` lowers to an
integer add of the string pointer and `str(k)`'s pointer, and the yielded word
prints as a decimal. Expected: the call site's argument type (`"r"`, a string) or
a runtime-dispatched `+` (`mojo_add_dyn`-style) decides concatenation.

Next step: look at how `_lower_BinaryOp` handles `int64_t + char *` for an
unsolved-param operand; the cross-module unannotated-param inference
(`test_cross_module_unannotated_param_takes_the_callers_literal_type`) already
takes the caller's literal type for plain functions and does not reach generators
(`<base>_start` slots). Quick test: the snippet above against CPython.
