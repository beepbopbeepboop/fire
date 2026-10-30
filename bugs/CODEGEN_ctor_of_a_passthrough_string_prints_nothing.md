# `list(ident("abc"))` prints nothing on the compiled path

**State: OPEN.** Surfaced 2026-10-29 when `test_gimple.py`'s `run_tests()` began
running every test to the end (it used to halt at the self-host signature check
before reaching this one). Pre-existing: the unmodified HEAD tree produces the
same failure once its crash is guarded.

## What I ran and what I saw

    python3 tools/memslot.py --gb 8 --label test_gimple -- python3 test_gimple.py

    FAIL  ctor_of_a_container_reaches_the_comprehension [single-TU]: compiled
      stdout '[1, 2, 3]\n(1, 2, 3)\n[1, 2, 3]\n6\nTrue\na,b\n2\n' != CPython
      "[1, 2, 3]\n(1, 2, 3)\n[1, 2, 3]\n6\nTrue\na,b\n2\n['a', 'b', 'c']\n"

(The `link-mode` variant of the same test is never reached: the first mode
fails and returns.)

The fixture is in `test_gimple.py`, `test_ctor_of_a_container_reaches_the_comprehension`.
Its final line is `print(list(ident("abc")))`, where `ident(x)` returns `x`. The
compiled program prints nothing for that line and exits without writing the
rest; every earlier line is correct.

## Expected

`list(ident("abc"))` prints `['a', 'b', 'c']`, the string-element counterpart of
the already-passing `list(ident([1, 2, 3]))`. The docstring names
`gen._passthrough_param_idx` as the mechanism that gives each call site the
parameter's own element type, so a string-typed passthrough should get the
`char *` access path.

## Next step

1. Compile the fixture alone (`def ident(x): return x`, `def main(): print(list(ident("abc")))`)
   with `gimple_codegen.compile_to_gimple` and read the generated `main`.
   Check whether the `list(...)` copy is emitted at all, and whether the
   element access is `char *` or `int64_t`.
2. Check the process exit status of the compiled binary for that one line; a
   silent stop there points at a crash or early return rather than a wrong
   value.
3. Fix at the passthrough element-type lookup for a `str` argument, then
   confirm the fixture's full output matches CPython in both modes.
