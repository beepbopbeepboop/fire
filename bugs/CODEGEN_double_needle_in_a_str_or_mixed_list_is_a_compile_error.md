# CODEGEN: a `float` needle over a str or kind-mixed list is a gcc error

**State: OPEN, found 2026-10-31** while fixing the
"`1 in ["a", 1]` segfaults" bug (fixed by the int-needle runtime helper `mojo_list_contains_mixed_int`).
That fix gave INT needles their own runtime helper (`mojo_list_contains_mixed_int`);
a FLOAT needle takes the other branch and is still lowered wrong.

Minimal repro:

    def main():
        print(2.5 in [2.5, "a"])
    main()

- CPython: `True`
- compiled: `gcc -fgimple` fails, no binary:

      incompatible type for argument 2 of 'mojo_list_contains_str'
      expected 'char *' but argument is of type 'double'

Pre-existing: the same error on pristine `HEAD` (checked by building a
`git archive HEAD` copy), so it is not a regression from the int-needle fix.

Cause: `_lower_in_dispatch`'s `rt == 'MojoList *'` branch
(`mojo/backend_gimple/emit_exprs.py`) picks `list_elem == 'char *'` for a
kind-mixed literal, and the `else` arm then calls
`mojo_list_contains_{suf}` with `suf` from `list_suffix('char *')` while the
needle is a `double`; `_cast_for_list` does not convert a double to `char *`.

Expected: membership is defined per ELEMENT with Python's `==`, so a double
needle matches an int-valued or double slot numerically (`2.5 in [2.5, "a"]`
is True, `2.0 in [2, "a"]` is True), and matches no str slot.

Next step: add a double-domain counterpart beside `mojo_list_contains_mixed_int`
in `runtime/fire_runtime.c` (e.g. `mojo_list_contains_mixed_double`: a 'd' slot
compares by value, an 'i' slot compares `(double)word == v` only when the int is
exactly representable, every other kind never matches), and route a
`double`-typed needle over a `char *` list to it in the same branch that now
handles the int needle. Pin it in `test_gimple_runner.py` next to
`gimple_int_in_mixed_str_int_list` with CPython as the oracle, including
`2.5 in [2.5, "a"]`, `2.0 in [2, "a"]` and `2.5 in ["a"]`.
