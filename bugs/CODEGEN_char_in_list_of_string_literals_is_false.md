# CODEGEN: `c in ["a", "c"]` is false for a character taken from a string, so the branch never runs

**State: OPEN, found 2026-10-31** while checking
`gimple_char_concat_never_frees_shared_character` in `test_gimple_runner.py`,
which is red on this branch's base commit (its last output line `acac` is missing; the
memory-bound check passes).

Minimal repro (`for c in "..."` over a string, `in` against a list literal of
string literals):

    def main():
        var seen = ""
        for c in "abcabc":
            if c in ["a", "c"]:
                print(c)
    main()

- CPython: `a`, `c`, `a`, `c`
- compiled: nothing printed

Expected: a one-character `char *` element tested against a list of string
literals compares by value. The compiled path answers False for every element.
The failing test then shows `(x[x{}x]) tokens` with no `acac` line.

Not reproduced: `if c == "a" or c == "c":` in the same loop works (it is the
`in`-against-a-list-literal lowering that is wrong).

Next step: find the lowering of `in` with a list-literal right-hand side on a
`char *` left operand (`gimple_codegen.py` / `mojo/backend_gimple/` `_lower_in`
or the `in`-operator path), check it compares the two `char *` by content
(`mojo_str_eq`-style) rather than by pointer or as a list-of-pointer lookup, and
pin it with `test_gimple_matches_cpython` next to `gimple_set_bytes_survive_rehash`
in `test_gimple_runner.py`.
