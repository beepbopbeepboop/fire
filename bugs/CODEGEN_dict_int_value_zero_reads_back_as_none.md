# A zero integer stored in a dict reads back as `None`

## Status: OPEN, filed 2026-10-03 on `work/merge-bugs3-r4` while fixing
## `**`-spread dict literals. PRE-EXISTING: measured identically at the
## commit before this session's four fixes, and it has no spread in it.

## What I ran

    def c() -> dict:
        return {'mid': 0}
    print(sorted(c().items()))

compiled with `test_gimple_runner.py`'s own
`compile_mojo_to_gimple_exe` and run, against CPython on the same text.

## What I saw

    compiled: rc=0 out="[('mid', None)]"
    cpython : rc=0 out="[('mid', 0)]"

`sorted(d.items())` reads each value back as `None`. A non-zero integer is
fine — `{'mid': 7}` prints `[('mid', 7)]`, and so is `{'q': 2}` in the same
program — so the shape is specifically the ZERO value, and it is silent: exit 0,
no diagnostic, one wrong value.

## Why it matters more than it looks

`0` and `None` are the two values a program cannot tell apart by accident,
because both are falsy — so this is the one member of the family that a
`if v:` guard silently swallows. Every other int is visibly wrong.

## Proven pre-existing, not this session's

`mojo/backend_gimple/emit_exprs.py`'s `_lower_dict_literal` was reverted to
`HEAD~4` and this program re-run: byte-identical output. That function is
where this session's `**`-spread fix went in, and `{'mid': 0}` has no spread,
so the two cannot be the same defect. (The same revert is also what
establishes that the spread fix was needed at all: at `HEAD~4` the two spread
programs died with `TypeError: unhashable type: 'dict'`, and with it they
print CPython's answer.)

## Exact next step

The store is `mojo_dict_set_int` (`_emit_dict_pair_store`'s int arm, which
`_lower_dict_literal` picks off `_quick_type(0)`), and the read is
`.items()`'s pair accessor. Two candidates, in order:

1. `_dict_val_types` is set to `'int64_t'` for this temp (the literal's
   value-type inference), so `.items()` should read slot 1 as an integer.
   Instrument `_lower_dict_method`'s `items` arm to print the `kind` it reads
   slot 1 with and the raw slot value: if the accessor is right and the slot
   is zero, the bug is in `mojo_dict_set_int`'s storage (a zero stored
   through a NULL-ish path); if the accessor is `str`/`none`, it is the
   value-type inference, and the fix is `_lower_dict_literal`'s
   `_quick_type(IntLiteral(0))`.
2. `runtime/fire_runtime.c`'s pair accessor. A `None` print means the value
   went through a string/`mojo_cstr_or_int_str` path that renders 0 as "None",
   or a NULL char* — `grep -n "None" runtime/fire_runtime.c` next to the
   `items` pair accessor.

Whichever it is, the check is a dict literal with a zero value read back
through `.items()` AND through `d['k']` (the two read paths are separate, and
the fix must land on both if both are wrong).