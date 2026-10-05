# CODEGEN: `_mojo_repr_pair` fires on any registered TWO-ELEMENT list, so an ordinary inner list prints as a tuple

**Found 2026-10-04** while fixing the `*expr` spread in a list/tuple display
that SIGSEGVed (that doc is deleted with its fix; the four mechanisms behind it
are `mojo/middle/types.py::is_star_spread`, `emit_exprs.py`'s
`_literal_slot_kinds`, its `_emit_star_spread`, both lowerings lowering the
spread's OPERAND, and `resolve_shared.py::_infer_list_elem_type`). Its
`*args` case pins `sorted(a)` through a tuple and so runs straight into this.
Filed, not fixed: the repair is a runtime-side predicate in the generated
repr helper, which is `mojo/backend_gimple/*` territory and a different class
of change from the spread fix that exposed it.

## What I ran

That fix's own third shape (the `*args` case), reduced so the vararg packing is
not in the picture at all — an ordinary list holding an ordinary two-element
list:

```python
x = [1, 2]
print([x])
print(sorted([1, 2]))
print([sorted([1, 2])])
```

CPython vs this tree (compiled, linked, run, both pipeline modes):

| expression | CPython | compiled |
|---|---|---|
| `print([x])` | `[[1, 2]]` | **`[(1, 2)]`** |
| `print(sorted([1, 2]))` | `[1, 2]` | `[1, 2]` |
| `print([sorted([1, 2])])` | `[[1, 2]]` | `[[1, 2]]` |

and the case the spread fix has to pin, where it is visible through a
`*args` pack:

```python
def g(*a, **k):
    return len(a), sorted(a), sorted(k.items())

def main():
    print(g(1, 2, x=3))
```

    CPython   (2, [1, 2], [('x', 3)])
    compiled  (2, [1, 2], [4297912176])        <- ASLR-dependent decimal

Note the two `[...]` rows in the first table: the SAME value (`[1, 2]`) prints
correctly when the enclosing literal's compile-time element type is known and
wrongly when it is not, which is what makes this a heuristic rather than a
uniform mistake and why a whole-file test could easily have missed it.

## What I see

`_mojo_repr_list`, the generic walker emitted into every module
(`mojo/backend_gimple/emit_exprs.py`'s repr-helper preamble):

```c
char *_es = (_e > 65536 && mojo_is_registered_list(_e)
   && mojo_list_len((MojoList *)(intptr_t)_e) == 2)
    ? _mojo_repr_pair((MojoList *)(intptr_t)_e)
    : _mojo_generic_elem_repr(_e);
```

`_mojo_repr_pair` prints tuple brackets and overrides slot 0 (its own comment:
"_mojo_generic_elem_repr answers 'None' for a 0 slot … wrong for a pair"). It
was written for a pair that is a runtime-built `zip`/`dict.items()`/
`enumerate` result, and at that time a two-element list and a pair were the
same thing in this value model. They no longer are, and the test that made them
different is not there: `mojo_mark_as_tuple` IS called on real pairs
(`runtime/fire_runtime.c`: `mojo_list_repeat`/`mojo_list_concat` at 1737/1904,
`mojo_dict_items` at 8721/8749, `mojo_zip` at 10846), so
`mojo_is_tuple(_e)` distinguishes a genuine pair from `[1, 2]` — the marker is
already load-bearing for `mojo_require_mutable_list`, per that function's own
note that the marker "used to be purely decorative".

The `(0, *` string-spread shape is the same defect seen through the tuple
marker: `bugs/CODEGEN_a_star_spread_of_a_string_beside_its_own_slots_prints_its_int_zero_as_none.md`.

## Why the existing spread tests do not catch it

They were written to assert the SPREAD, not the inner list's brackets, so the
right answer for the spread (`g(1, 2, x=3)` binding `a` to `[1, 2]`) is
asserted through `len(a)` and `sorted(a)` rather than through the printed
tuple. That was deliberate — see the comment on
`gimple_call_star_args_collects_loose_arguments_once` in
`test_gimple_runner.py` — and it is what leaves this doc's first table
unpinned.

## The exact next step

1. Require the marker: `_mojo_repr_pair` is for a pair, and a pair is marked
   (or, more precisely, is not an ordinary list). The predicate to add is in
   the generated helper, in `mojo/backend_gimple/cpp_core.py` where the walker
   is emitted, and it must keep the `zip`/`dict.items()`/`enumerate` answers
   working — `print(list(zip([1, 2], [3, 4])))` currently prints
   `[4352276976, 4352277040]` for a DIFFERENT reason (a `mojo_zip` result read
   as plain ints, which `mojo_list_set_elem_repr`/pair-kind coverage in
   `mojo/middle/methods_shared.py` is the other half of), so step 1 alone will
   turn a wrong-bracket answer into a decimal one for `zip`. Measure both
   spellings before and after.
2. The stronger form, and the one that removes the heuristic instead of
   tightening it: record the pair-ness on the VALUE (`mojo_list_set_kinds` with
   a two-byte kind row, or the existing `repr_fn` slot on `_KindRow`) at the
   three `mojo_mark_as_tuple(pair)` sites, and have the walker ask the value
   instead of guessing from its length. That is the same bargain the element
   repr already makes, for the same reason: the information is known where the
   value is built and is unrecoverable at the walker.
3. `test_gimple_runner.py` cases for the first table's three rows plus
   `list(zip(...))` and `dict.items()`, all through
   `test_gimple_matches_cpython`, so a tightening that breaks a real pair is
   caught by the same assertion.

## Related

- The `*expr`-spread-in-a-display fix (doc deleted with it) — what made these
  shapes reachable enough to see.
- `bugs/CODEGEN_user_defined_dunder_repr_not_consulted_by_str_and_container_spellings.md`
  — the same generated walker's other known wrong answer.