# `f"{a_list}"` and `str(a_list)` print the container's raw header bytes

**State: OPEN, diagnosed, not fixed.** Found 2026-09-27 while fixing
`bugs/hard/CODEGEN_struct_kwargs_and_inline_unpack.md`, where it turned up as
one of the ways a `struct.unpack` result was consumed. It is not a `struct`
bug and not a mixed-format bug, so it does not belong in that doc's queue; it
is recorded here so the finding is not lost.

## The symptom

    l = [1, 2, 3]
    print(f"{l}")
      CPython:    [1, 2, 3]
      compiled:   '\x10ڷ'          <- bytes, not text

    print(str(l))
      CPython:    [1, 2, 3]
      compiled:   'P�<\x05\x01'

Reproduced through the same path `test_gimple_runner.py` uses
(`compile_to_gimple` + gcc `-fgimple`):

    $ python3 -c "..."   # see the commands in the repro below

## It is not struct-specific, and not mixed-format-specific

Measured on this tree, all compiled, all against CPython 3.14:

| program | CPython | compiled |
|---|---|---|
| `f"{[1, 2, 3]}"` | `[1, 2, 3]` | `'\x10ڷ'` |
| `f"{[1.0, 2.0]}"` | `[1.0, 2.0]` | `'\t�D\x0b'` |
| `str([1, 2, 3])` | `[1, 2, 3]` | `'P�<\x05\x01'` |
| `f"{struct.unpack('<3i', b'...')}"` | `(1, 2, 3)` | `'pa�'` — a **uniform** format |
| `print([1, 2, 3])` | `[1, 2, 3]` | `[1, 2, 3]` — correct |

The last row is the point: `print` is right and the f-string is wrong, for the
same value in the same function.

## Root cause

`mojo/backend_gimple/emit_infra.py`'s `_stringify_value` has branches for
`char *`, `MojoBytes *`, `MojoMemoryView *`, `_Bool` and every integer and
float width — and then falls through to

    return gen._call_expr('char *', 'mojo_str', [(et, ev)])

for anything else, `MojoList *` included. The generated C for
`f"{struct.unpack(...)}"` is literally

    _t9 = (void *)_t7;
    _t8 = mojo_str (_t9);

`mojo_str` then reads the `MojoList` header as a C string, so the output is the
`len` field and whatever follows it in memory. The address printed differs run
to run, which is why the garbage looks different each time.

The `print` path is a different function (`_lower_print_args` and friends in
the same file) and it DOES have the container branch — it routes through
`_list_repr_fn`, which chooses between `_mojo_repr_list`,
`mojo_repr_list_ints`, `mojo_repr_list_doubles`, `mojo_repr_list_bytes` and
`mojo_repr_list_kinds`. That machinery is exactly what is missing on the
f-string/`%s` side.

## Why it is not a one-line fix

The obvious patch is a `MojoList *` branch in `_stringify_value` calling
`gen._list_repr_call(...)`. It does not work, and the reason is worth writing
down: the f-string interpolation site does not hand `_stringify_value` a
`MojoList *`. It lowers the expression, gets `(etype, evalue)`, and for a
call result the lowered type is `void *` with the list handle boxed into it
(see the `_t9 = (void *)_t7` above). `_stringify_value` has no way to recover
the static container type from `(void *, _t9)` — and the value-identity
side-tables the repr selection needs (`_elem_types`, `_nested_elem_types`,
`_struct_slot_kinds`) are keyed on the ORIGINAL value name, not on the cast
copy. So the fix has to be at the interpolation site, resolving the real type
the way the `print` path already does, and it has to be checked against the
same container-kind-coercion chokepoint rules as the rest of the backend
(`DESIGN.html` R2/R3, guarded by `test_no_new_container_casts.py`).

`%`-formatting's `%s` shares `_stringify_value`, so it is affected identically
and should be fixed in the same pass.

## Where

- `mojo/backend_gimple/emit_infra.py` — `_stringify_value` (the missing
  branch) and the f-string interpolation site in
  `mojo/backend_gimple/emit_exprs.py` that calls it (the type it passes).
- Reuse rather than re-implement: `gen._list_repr_call`, which already pairs
  the helper choice with its argument list.

## Coverage gap that let this survive

`test_gimple_runner.py` exercises `print` of every container shape it tests
and the f-string of scalars, but never `f"{list}"` or `str(list)`. A
`gimple_fstring_and_str_of_containers` case asserting `f"{[1, 2]}"`,
`f"{b'ab'}"`, `str({1, 2})` and `str({'a': 1})` against CPython would have
caught it, and should be added with the fix.
