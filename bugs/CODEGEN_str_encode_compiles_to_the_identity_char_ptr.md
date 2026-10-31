# CODEGEN: `str.encode(...)` on a `char *` compiles to the identity (a TODO stub), so the result is a str, not bytes

**State: OPEN, found 2026-10-31** while fixing
`CODEGEN_function_values_assigned_in_branches_then_returned_assignment_to_int_from_char_ptr`.

    s = "abc"
    b = s.encode()
    print(b)                # CPython: b'abc'      compiled: abc
    print(len(b), type(b))  # CPython: 3 <class 'bytes'>   compiled: 3 0

`mojo/backend_gimple/emit_methods.py` (the `char *` method table, near
`if method in ('encode', 'decode', 'readlink'): return gen._stub_result('char *',
cstr_ov, f'TODO: {method}')`) hands the receiver back unchanged typed `char *`;
the generated C even carries `/* TODO: encode */`. `decode` on a `MojoBytes *`
is the mirror question.

Next step: for `encode` on a `char *` return `MojoBytes *` via
`_coerce_to_bytes(gen, 'char *', ov)` (`mojo_bytes_from_str`, honouring the
encoding argument when it is a literal other than utf-8), register `encode` as
`MojoBytes *` in `_quick_type`'s `char *` method row so pre-passes agree, and
pin it with a build-and-run comparison against CPython in `test_gimple_runner.py`.
