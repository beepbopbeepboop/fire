# CODEGEN: an element of a list that holds bytes words does not compare equal to a bytes literal

Found while working `CODEGEN_glob_bytes_pattern_returns_empty.md` (2026-11-01).

## Measured (compiled, this tree; CPython in brackets)

    r = fnmatch.filter([b'a.py', b'b.txt'], b'*.py')   # a MojoList built by the runtime
    print(r)                                            # [b'a.py']                   (correct)
    print(r[0] == b'a.py')                              # False                       [True]
    print(glob._listdir(root, None, False) == [b'a.py'])  # False                    [True]

Printing the same list is now right (the bytes slot kind, see the bytes-kinds commit), so the
element is stored correctly and the defect is in the read or the comparison.

## Why (not isolated)

Hypothesis, not yet measured: the subscript `r[0]` on a list whose element kind is not statically
known lowers to an `int64_t` read (`mojo_list_get_int`), which returns the raw pointer word, and the
`==` against a `MojoBytes *` literal is then an int-vs-pointer comparison. The boxed read
(`mojo_list_get_boxed`, which boxes a non-int slot with its kind) is what a kind-aware read
should use.

## Next step

1. Dump the generated C for `r[0] == b'a.py'` (the `client.c` under `.tmp/mojo_drv_*`) and confirm
   which read and which comparison are emitted.
2. Make the subscript of a word-kinded list go through `mojo_list_get_boxed` and the `==` of a
   word against a bytes literal go through `mojo_bytes_eq` on the registered bytes (or a generic
   word equality that dispatches on the kind), as the str case already does.
3. Test: a probe asserting `r[0] == b'a.py'` and `[b'a.py'] == [b'a.py']` as in CPython, added to
   `test_glob_bytes_regress.py`; fails on this tree first.
