# CODEGEN: `hasattr(xs, "append")` on a list is False in the compiled binary

Found while probing statement-position builtins for `CODEGEN_bare_str_decode_call_statement_too_many_args` (2026-11-02).

## Measured

    xs = [3, 1, 2]
    print(pow(2, 3, 5), sorted(xs), hasattr(xs, "append"))

- CPython: `3 [1, 2, 3] True`
- `python3 fire.py build` binary: `3 [1, 2, 3] False`

The line is in value position (inside `print`), so it does not go through the statement path;
the bare-statement fix does not touch it. The `pow`/`sorted` parts of the same line are correct.

## Expected

`hasattr` on a list instance reports the list's methods as CPython does.

## Next step

1. Find the `hasattr` arm in `mojo/backend_gimple/emit_calls.py` (`fname_raw == 'hasattr' and len(node.args) == 2`)
   and see what it decides for a list-typed (`MojoList *`) first argument; it likely answers from
   the struct/field table only.
2. Fix it in that arm so a builtin container's method names answer True, rather than special-casing `append`.
3. Test: the probe above, compared to CPython, in a `test_*.py` next to the existing hasattr coverage;
   it prints `False` on the current tree, so it fails first and must print `True` after the fix.
