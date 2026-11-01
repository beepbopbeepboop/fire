# CODEGEN: a `None` held in a variable is the int 0 when it is a `in` needle

**State: OPEN, found 2026-10-31** while fixing the `1 in ["a", 1]` SIGSEGV (the int needle over a kind-mixed list).
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
