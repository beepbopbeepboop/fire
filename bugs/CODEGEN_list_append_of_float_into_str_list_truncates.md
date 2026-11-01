# CODEGEN: `.append(<float>)` onto a str-typed list stores the truncated int

**State: OPEN, found 2026-10-31** while pinning the float-needle fix
(`gimple_double_in_mixed_str_list`). Not caused by the `in` lowering.

Repro (`.tmp/append_probe.py` in the finding worktree):

    def main():
        built = ["a"]
        built.append(2.5)
        print(built)
        print(2.5 in built, 2.0 in built, "a" in built)
    main()

- CPython: `['a', 2.5]` then `True False True`
- compiled (`gimple_matches_cpython`): `['a', 2]` then `False True True`

The float is stored into the list's `char *` slot as the truncated int `2`
(its value as a pointer), so the element is no longer a double at all. The
list has the `char *` element type from its first literal element, and
`append` lowers the double argument into that slot type without a conversion
or a kind record.

Expected: the element is the double `2.5` (a 'd' slot in the kinds row), so
`print` shows `2.5` and `2.5 in built` is True.

Next step: find the `append` lowering for a `char *` list receiver in
`mojo/backend_gimple/emit_exprs.py` (the `append` branch that calls the
list push helper) and make a `double` argument use the double push helper,
recording the 'd' kind the same way the list literal path does (see how
`mojo_list_contains_mixed_double`'s kinds row is produced for `["a", 2.5, 3]`).
Pin it in `test_gimple_runner.py` beside `gimple_double_in_mixed_str_list` with
the repro above as the CPython-oracle case.
