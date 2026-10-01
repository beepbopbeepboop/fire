# CODEGEN: a range() comprehension of tuples loses per-slot element types

## Status — OPEN. Compiled path only; the interpreter is correct.

A comprehension whose element is a tuple or a list, iterating `range(...)`,
drops the element's per-slot element types. The first slot survives; every
later slot falls back to the `char *` accessor, so a slot holding **0** reads
back as NULL and renders as `None`.

Silent and exit 0 — the worst class. A non-zero int happens to print, because
a small integer is a pointer that prints as a number, so this only *looks*
right until a slot holds zero or a real pointer.

Found 2026-09-30 while fixing multi-clause comprehensions (see
`CODEGEN_selfhost_closure_inference_gaps`'s successor commit) — it is
**pre-existing and independent** of that fix, and reproduces on a
single-clause comprehension.

## Measured repro

```python
def main():
    print([[5, j] for j in range(3)])     # expected [[5, 0], [5, 1], [5, 2]]
    print([(5, j) for j in range(3)])     # expected [(5, 0), (5, 1), (5, 2)]
    ys = [7, 8, 9]
    print([[5, y] for y in ys])           # expected [[5, 7], [5, 8], [5, 9]]
```

Compiled (`python3 fire.py --jit`):

```
[(5, None), (5, 1), (5, 2)]
[(5, None), (5, 1), (5, 2)]
[[5, 7], [5, 8], [5, 9]]      <-- correct
```

The third line is the control that isolates the cause: iterating a real
`MojoList` is **correct**, iterating `range()` is not. So this is the
range path, not tuple rendering in general.

Note also the outer shape: a list element prints as a tuple `(5, None)`
where the interpreter prints a list `[[5, 0], ...]`. That is a second,
smaller divergence in the same lines and may share a root cause.

## Where to look

`mojo/backend_gimple/emit_resolve.py`, `_gen_compr_append`, the tuple carry:

```python
if et == 'MojoList *' and ev in gen._tuple_slot_types:
    gen._tuple_slot_types[res] = gen._tuple_slot_types[ev]
```

`_compr_range_loop` (`mojo/backend_gimple/emit_infra.py`) reaches
`_gen_compr_append` the same way `_compr_list_loop` does, but something on
the range path leaves the lowered element (`ev`) out of
`gen._tuple_slot_types`, so the guard is False and the slot map is never
populated. Compare the two loop helpers for what each does to declare and
type its loop variable, and for whether the range path's element lowering
loses the registration the list path performs.

The nested-list element type map is `gen._nested_elem_types`; check whether
the range path populates that one either.

## Next step

Instrument `_compr_range_loop`'s call into `_gen_compr_append` to print `et`
and `ev in gen._tuple_slot_types`, and the same two values on the
`_compr_list_loop` path for the control case. That single comparison
identifies which map the range path fails to register, and the fix is then
to register it in the same place the list path does.

Do not paper over it by special-casing zero: the wrong accessor is wrong for
every pointer-valued slot, and the zeros are just where it becomes visible.
