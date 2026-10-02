# CODEGEN: a loop target over a list-of-lists gets the outer level's element type but never the inner one

**State: OPEN, reproduced 2026-09-29, next step located, not fixed.**

Found next to `bugs/hard/CODEGEN_coro_yield_kind_unresolved_callsite.md` item 8
while extending the cross-call container element-type contract; it is a
PRE-EXISTING gap in the loop lowering, not something that change introduced
(the bare-local spelling below fails identically with and without it).

## Symptom

```mojo
def show(rows):
    for row in rows:
        for cell in row:
            print(cell)

def main():
    m = [["a", "b"]]
    show(m)
```

    CPython:   a
                b
    compiled:   4367768768
                4367768776        (the strings' heap addresses), exit 0

The same program with integer elements is correct (`[[1, 2], [3, 4]]` prints
`1 2 3 4`), because the inner elements' `int64_t` is the default the loop
target already assumes.

## Mechanism (measured from the generated C, not inferred)

The OUTER half already works. `rows` inherits `('MojoList *', 'char *')` from
the cross-call contract (`_param_elem_types`, fed by
`_scan_container_elems`'s `note_list_literal`), so the outer loop declares

    void show_815e8f (MojoList * rows) {
      MojoList * row;      /* <-- correct */
      ...
      _t5 = mojo_list_get_int (rows, _t3);
      row = (MojoList *)_t6;

and `_nested_elem_types['rows'] == 'char *'` is seeded alongside it
(`emit_funcs.gen_func`'s `_pe` loop sets `_elem_types[bare] = e` AND
`_nested_elem_types[bare] = ne`).

The INNER half is missing: the loop target `row` never inherits
`_nested_elem_types['rows']`, so `_gen_for_list`'s `_elem_of('row')` finds
nothing in `_elem_types` and falls to `int64_t`:

      int64_t cell;                       /* <-- should be char * */
      ...
      _t11 = mojo_list_get_int (row, _t9);
      cell = (int64_t) _t11;

`note_list_literal` in `mojo/middle/infra_infer.py` already does exactly this
carrying for a list LITERAL bound to a local (`_lower_list_literal` in
`emit_exprs.py` does it too, at the `_homogeneous_literal_inner_elem` /
`gen._nested_elem_types[t] = _inner_ct` pair). What is missing is the same
step for a **loop target** whose iterable's element ctype is `MojoList *`.

## Next step

In `mojo/backend_gimple/emit_loops.py`, `_gen_for_list`'s non-tuple branch —
where it already computes `elem = gen._elem_of(it_val)` and declares the
target with it — also carry the iterable's NESTED element ctype onto the
target when `elem` is a container:

    if _as_str(elem) == 'MojoList *':
        _inner = gen._nested_elem_types.get(it_val)
        if _inner is not None:
            gen._elem_types[var] = _inner
            _deeper = gen._nested_elem_types.get(it_val)  # third level, if any

Placement matters: after `_declare_var(var, _fl_ctype, ...)` and before the
body is generated (`gen._gen_loop_body(node.body)`), so the inner `for` sees it.
Note the self-host constraints this file already documents — no comprehension,
no chained `setdefault` on a fresh dict, no tuple unpacking in a `for` target.

Regression test goes in `test_gimple_runner.py` beside
`gimple_for_over_nested_list_param_from_literal` (added 2026-09-29, the
integer-element spelling of this same program, which passes), with the string
spelling as the case that must change.

## Blast radius

Unknown and unmeasured: this touches the ordinary loop lowering that every
list iteration in the compiled path goes through, so it needs a full
`make gate` (`stdlib-syntax`'s unexpected-failure count and
`stdlib-dylib`'s skip count both have to be compared before/after, per
CLAUDE.md).
