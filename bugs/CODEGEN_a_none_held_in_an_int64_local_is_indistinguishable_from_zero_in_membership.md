# CODEGEN: a `None` held in a variable is the int 0 when it is a `in` needle

**State: PARTIAL, found 2026-10-31; partial fix 2026-10-31** (see Status at the end). While fixing the `1 in ["a", 1]` SIGSEGV (the int needle over a kind-mixed list).
A `None` LITERAL needle is now handled exactly (`None in ["a", None]` is True,
`None in [0, 1]` is False). A `None` held in a VARIABLE is not: the local is
lowered as an int64 word, and that word is the same as the int `0`.

Repro:

    def main():
        n = None
        print(n in ["a", None])
    main()

- CPython: `True`
- compiled: `False`

The generated C is `int64_t n; n = 0LL;` and the membership reads `_t6 = n;`
then `mojo_list_contains_mixed_int (_t1, _t6)`, so the needle is an int 0 by
the time the membership is lowered. Master also answers `False` here, so this
is not a regression from the int-needle fix; it is the same underlying gap.

Cause: the value ABI has no None word. `CODEGEN_a_bare_or_explicit_yield_of_none_prints_zero.md`
records the same representational fact for generator yields ("a None value
cannot be represented in the word at all"). The membership lowering can only
see the static type `int64_t`, so it applies the int meaning, which is the
right answer for `0 in ["a", None]` and wrong for a None variable.

Next step: the fix needs a None-typed local, not a membership change. Either
(a) the lowering records, per local, that it was last assigned `None`
(the same bookkeeping `_int_word_vals` uses) and lowers the membership against
the NULL needle when it is still that value, or (b) the None value gets a
tagged representation (the ABI change the yield doc describes). (a) is a
bounded codegen change; (b) is the owner-level one. Pin with
`test_gimple_matches_cpython` in `test_gimple_runner.py` for `n = None` used as
an `in` needle against a list with and without a None slot.

## Status

**2026-10-31, partial fix (option (a), narrowed).** Landed in
`mojo/backend_gimple/emit_exprs.py`: `none_only_locals(gen)` returns the locals
of the function being lowered whose EVERY binding is the literal `None` (no
other assignment, augmented/tuple/for/with/except/walrus target, parameter,
import, `global`/`nonlocal`, nested def name, or `match` anywhere in the
function). `is_none_needle(gen, node)` treats such a local as a `None` needle,
so `n in [...]` takes the NULL-needle path (`mojo_list_contains_str` with a NULL
needle, or `mojo_list_contains_none`), exactly as a `None` literal already did.
The per-function cache (`_none_only_names`) is reset in `_reset_func` and saved/
restored with the nested-function state in `emit_infra.py`.

Pinned by `test_none_bound_local_is_none_not_zero_in_membership` in
`test_gimple_runner.py` (registered in the late-test list): the repro, the
no-None-slot list, `not in`, and a second function whose `n = 0` must still be
an int.

**Still open.** A local that is `None` on one path and some other value on
another keeps the int path. Probe (CPython `True`, compiled `False`):

    def main():
        n = None
        if len("ab") > 5:
            n = 1
        print(n in ["a", None])
    main()

The flow-insensitive check cannot answer this, because the local has a
non-None binding. The next step is either (1) a flow-sensitive record of which
locals are None at the membership point, which needs the join points of `if`/
`while`/`try` lowered into the bookkeeping, or (2) the tagged None word the
yield doc (`CODEGEN_a_bare_or_explicit_yield_of_none_prints_zero.md`)
describes, which removes the ambiguity at the value level. Dict and set
membership of a None-held local are also still unaddressed: `x_is_none` only
reaches the list branch, and the `none_only_locals` answer is not consulted by
`_lower_in_dispatch`'s dict/set arms.
