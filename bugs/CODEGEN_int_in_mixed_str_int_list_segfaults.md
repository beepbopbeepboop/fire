# CODEGEN: `1 in ["a", 1]` segfaults — an int needle against a kind-mixed list is lowered to the string comparison

**State: OPEN, found 2026-10-31** while fixing the
"`c in ["a", "c"]` is always false" bug in the same list-membership branch of
`_lower_in_dispatch`.

Minimal repro:

    def main():
        print(1 in ["a", 1])
    main()

- CPython: `True`
- compiled: exit `-11` (SIGSEGV), no output

Pre-existing: identical crash on pristine `HEAD` (`git show
HEAD:runtime/fire_runtime.c`), so it is not a regression from that fix.

Cause: `["a", 1]` is a kind-mixed literal, so `_infer_list_elem_type` /
`_literal_slot_kinds` make `list_elem` `char *` and the literal records kinds
`"pi"`. In `_lower_in_dispatch`'s `rt == 'MojoList *'` branch
(`mojo/backend_gimple/emit_exprs.py`), the int64 needle `1` is therefore
cast to `(char *)1` by `_cast_for_list` and passed to
`mojo_list_contains_str`, which walks slot 0 (a real `char *`, kind `'p'`) and
`strcmp`s it against address 1 — a wild read. The generated call is:

    _t14 = mojo_list_contains_str (_t10, _t15);   /* _t15 == (char *)1 */

The same shape with a `char *` needle works (`"a" in ["a", 1]` is True), and
a uniform int list (`1 in [1, 2]`) uses `mojo_list_contains_int` and works;
only the int-needle-against-mixed case is wrong.

Expected: membership is defined per ELEMENT in Python, so a mixed list must
compare each slot in that slot's own domain (`'p'` -> strcmp, `'i'` ->
word equality, `'d'` -> bit equality).

Next step: in the `rt == 'MojoList *'` branch of `_lower_in_dispatch`, when
the list's recorded kinds are not uniform and the needle's domain does not
match a slot's, do not pick one accessor for the whole list. Add a runtime
helper beside `mojo_list_contains_str` (e.g. `mojo_list_contains_mixed_str` /
`mojo_list_contains_mixed_int`) that reads `mojo_list_slot_kind` per slot and
compares in that slot's domain, and call it from the mixed case. Pin it with
`test_gimple_matches_cpython` in `test_gimple_runner.py` next to
`gimple_str_in_list_of_string_literals`:

    print(1 in ["a", 1], 1 in ["a"], 0 in ["a", None])

(`0 in ["a", None]` is the edge the naive "compare the int word" answer gets
wrong: a NULL None slot compares equal to 0.) Then delete this doc in the same
commit and run `python3 tools/dangling_doc_refs.py --ratchet`.
