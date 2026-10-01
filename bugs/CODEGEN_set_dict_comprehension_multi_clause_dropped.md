# CODEGEN: a set/dict comprehension with 2+ `for` clauses drops every clause after the first

## Status — OPEN. Compiled path only. Silent, exit 0.

`list` and generator comprehensions with multiple `for` clauses were fixed
(the commit that lands `_compr_pending_inner` in
`mojo/backend_gimple/emit_exprs.py` / `_gen_compr_append` in
`mojo/backend_gimple/emit_resolve.py`). **`set` and `dict` comprehensions were
deliberately left out**, and they still drop the extra clauses.

The fix extends each container kind by a different mechanism, so it is not a
matter of reusing the list path:

- `list`/`generator` share `mojo_list_extend` — both are list-backed, which is
  why they were fixed together and why the fix was contained.
- `set` needs a real per-element insert (`mojo_set_add_int` / `_str`) so an
  element is deduplicated, not concatenated.
- `dict` needs a per-pair merge, and its element is a `key`/`value` pair
  rather than a single expression.

Guessing at that from the list path is how the original bug got in, so it was
left visible rather than half-done.

## Measured repro

```python
def main():
    print({i + j for i in range(3) for j in range(3)})
    print({(i, j): i * j for i in range(2) for j in range(2)})
```

Expected:

```
{0, 1, 2, 3, 4}
{(0, 0): 0, (0, 1): 0, (1, 0): 0, (1, 1): 1}
```

Compiled (`python3 fire.py --jit`): the outer clause only, so the first
becomes a 3-element set `{0, 1, 2}` and the second a 2-element dict. Exit 0.

## Where to look

Same two files as the list fix.

- `mojo/backend_gimple/emit_exprs.py`, `_lower_comprehension`: the
  `if len(node.generators) > 1 and node.kind in ('list', 'generator')` guard
  is what excludes these kinds. Widening the guard is NOT the fix — the
  handler below it is a list extend.
- `mojo/backend_gimple/emit_resolve.py`, `_gen_compr_append`: the extend
  branch is guarded `if _inner is not None and node.kind in
  ('list', 'generator')`. The `elif node.kind == 'set':` arm further down is
  where a set's per-element add already happens for the single-clause case,
  and it is the natural place for a nested set: lower the inner comprehension
  to a set, then merge element-wise.
- For `dict`, the same shape against `mojo_dict_*`, keyed on the
  `Comprehension.key` attribute rather than `element`.

Two element-type maps must be carried across the merge for each kind, exactly
as the list path had to: `_elem_types` and `_tuple_slot_types`. Skipping
either reproduces the `[None, 1, 2, ...]` and `[(0, None), ...]` symptoms the
list fix already had — an int 0 read through the `char *` accessor is NULL.

## Next step

Mirror what the list path does, one kind at a time, starting with `set` since
it is the smaller of the two: park the remainder as today, and in the
single-clause set arm merge the lowered inner set into the outer one with
`mojo_set_add_*` per element instead of `mojo_list_extend`. Then add a
differential case to `test_runtime_diff.py` for the set shape (the list shape
already has `comprehension_two_clauses` and
`comprehension_three_clauses_with_filters` from the original fix), and only
then `dict`.

Keep the scalar-element constraint those cases use: a tuple/list element
inside a `range()` comprehension has its own pre-existing defect
(`CODEGEN_range_comprehension_tuple_slot_type_lost.md`), so a case that
absorbs it would be measuring two bugs at once.
