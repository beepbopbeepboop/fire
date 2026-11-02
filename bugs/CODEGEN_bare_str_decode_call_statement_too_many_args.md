# CODEGEN: a bare `str(bytes, encoding[, errors])` expression statement fails to compile

Found while extending `test_glob_bytes_regress.py` (2026-11-02).

## Measured

    try:
        str(b"\xff", "ascii")            # value discarded: an expression statement
    except UnicodeDecodeError:
        print("refused")

Compiled with `python3 fire.py build`:

    error: too many arguments to function 'mojo_str', expected 1, have 2

The same call bound to a name (`_refused = str(b"\xff", "ascii")`) compiles and raises as CPython
does.

## Why

The two/three-argument `str(bytes, encoding[, errors])` decode is special-cased in
`mojo/backend_gimple/emit_calls.py` (the `fname_raw == 'str' and len(node.args) in (2, 3)` branch).
An expression statement is lowered on a different path (`mojo/backend_gimple/emit_stmts.py`, the
`ExprStmt` / call-statement arm), which does not reach that branch and falls through to the generic
one-argument `mojo_str` call.

## Next step

1. Find the expression-statement arm in `emit_stmts.py` that lowers a bare call and confirm it
   bypasses `emit_calls`' builtin dispatch for `str`.
2. Route it through the same builtin lowering as the value form (discard the result), rather than
   adding a `str`-specific special case there.
3. Test: the three-line block above in `test_glob_bytes_regress.py` (bare statement form), compared
   to CPython; it must fail on the current tree first.
