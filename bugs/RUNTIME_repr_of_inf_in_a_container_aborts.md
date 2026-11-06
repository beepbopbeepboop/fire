# RUNTIME: printing a list holding an infinity aborts (free of a string literal)

## What I ran

    cat > .tmp/infone.mojo <<'EOF'
    def main():
        print([999e9000])
    EOF
    python3 tools/memslot.py --gb 8 --label infone -- \
        python3 fire.py build -o .tmp/infone .tmp/infone.mojo
    .tmp/infone

## What I saw

`Abort trap: 6` (exit 134), no stdout/stderr.  `print([1.0, 2.0])` and
`print(999e9000)` both work, so the abort is specific to a NON-FINITE value
inside a container.  Before `_float_c_literal` landed, the program did not
compile at all, so this arm was unreachable from a literal; a NaN/inf produced
by arithmetic (`999e9000 - 999e9000`) reaches it too.

## Root cause (read off the code, not guessed)

`runtime/fire_runtime.c`'s `mojo_repr_float` returns the string LITERALS
`"nan"`/`"inf"`/`"-inf"` for the non-finite values and a fresh `strdup` for
everything else.  `mojo_repr_list_doubles` (and the other uniform list
walkers) assume the fresh-string arm and do:

    char *_s = mojo_repr_float(mojo_list_get_double(l, _i));
    _buf = mojo_str_cat_free(_buf, _s);
    free(_s);

so `free` of the literal aborts.  `mojo_cstr_or_int_str` also wraps the call
in `strdup`, which leaks the finite arm, and
`mojo/backend_gimple/emit_infra.py`'s `_OWNED_REPR_FNS` deliberately omits
`mojo_repr_float` for the same reason.

## Exact next step

Make `mojo_repr_float` own its return on EVERY path (`return strdup("nan")`,
etc.), delete the now-redundant `strdup` around it in `mojo_cstr_or_int_str`,
and add `mojo_repr_float` to `_OWNED_REPR_FNS` (removing its paragraph from the
"deliberately absent" list).  Then `print([999e9000, -999e9000])` must print
`[inf, -inf]`; add that as the pinning case beside
`gimple_nonfinite_float_literals` in `test_gimple_runner.py`, which already
has the `gimple_*_repr_is_released` / bounded-memory rows that will catch the
ownership change.
