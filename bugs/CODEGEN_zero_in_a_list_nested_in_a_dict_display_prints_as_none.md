# CODEGEN: a `0` in a list literal nested inside a dict display PRINTS as `None`

**Status: OPEN, measured 2026-10-07, exit 0, repr-only.** Narrowed from a
wider report (a zero in any dict value or derived container element printed
`None`) written on the round8 lineage; the dict-VALUE half and every
runtime-built list shape listed below were re-measured on current master and
are fixed. One shape is left.

## Reproduction

```python
def main():
    print({'k': [0, 1]})
main()
```

CPython: `{'k': [0, 1]}`. Compiled (`python3 fire.py build`): `{'k': [None, 1]}`.

Every VALUE is right (subscripting reads 0, `len`/`sum` are right); only the
text is wrong, which is why nothing downstream notices.

## What was re-measured and is fine

`[[0], [1]]`, `list((0, 1))`, `(0, 1)[:]`, `[0, 1][:]`, `sorted([1, 0])`, a
list a function returns, `[0] + [0, 1]`, and `{'k': 0, 'j': 1}` all print
CPython's text.

## Why

The nested list inside a dict display is not given the per-slot element kinds
that a top-level list literal records with `mojo_list_set_kinds`, so
`_mojo_repr_list` falls through to the generic walker, whose
`_mojo_generic_elem_repr` (emitted per module by
`mojo/backend_gimple/module_gen.py`) opens with `if (val == 0) return "None";`
-- the runtime's "0 means absent" convention leaking into text.

## Exact next step

Make the dict-display lowering (`mojo/backend_gimple/emit_exprs.py`, where a
list literal is recognised via `_list_literal_slot_kind` /
`_maybe_kinds_vals`) record kinds for a list literal that appears as a dict
VALUE the same way it does at the top level. Only when no container element
can be an unknown-kind zero may the `val == 0` line be narrowed; deleting it
first turns this bug into `0` where `None` belongs. A test belongs with the
fix: the reproduction above as a `test_gimple_stdout` case in
`test_gimple_runner.py`, asserted against CPython's text.
