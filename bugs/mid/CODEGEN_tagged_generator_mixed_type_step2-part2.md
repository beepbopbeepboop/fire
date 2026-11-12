# CODEGEN_tagged_generator_mixed_type_step2-part2: let a mixed tagged name hold a float

Class: **mid** (this doc lives in `bugs/mid/`).

## Parent

`bugs/hard/CODEGEN_tagged_generator_mixed_type_step2.md` (split), which is
step 2 of `docs/tagged_generator_mixed_type-plan.md`. Part 1 of the split pins
the runtime box contract in `test_ptr_registry.py`; this part uses it. Part 3
extends the same store arm to `str`.

## Current state (measured 2026-11-10)

A name bound to a tagged generator word (a generator whose yields are more
than one kind, so each yield travels as an `int64_t` box) *and* to a float is
refused by `MIXED_NAME_NON_INT64_REFUSAL` in `mojo/backend_gimple/emit_infra.py`.
The refusal is raised from the simple-name assignment arm of
`mojo/backend_gimple/emit_stmts.py` (the `if ((_tagged_bind and
ginf.is_non_int_c_type(...)) or (ginf.is_non_int_c_type(vtype) and
ginf.tagged_mixed_name(...)))` block). Both directions are refused:

| shape | source | result |
|---|---|---|
| float first, then a tagged copy | `x = 0.5; for v in g(): x = v` | `RuntimeError: 'x': a name bound to a tagged generator word ... cannot also hold a value of another C type (str or float): the box cannot carry it; refused` |
| tagged copy first, then a float | `x = 0; for v in g(): x = v; ...; x = 2.5` | same message |
| float first and after | same as row 1 with a later `x = 2.5` | same message |

Those are exactly the two fixtures at
`test_gimple_generator_runner.py`'s `run_tagged_for_target_bind_tests`
(`_mixed_float` and `_mixed_after`), which are currently
`test_generator_refused(...)` assertions. The refusal protects two different
C-slot problems at once: a bare float word stored into an `int64_t` box slot
loses the box (printing `1.0`/`0.0` for `1`/`None`), and a bare `int64_t` word
stored into a `double` slot is a C cast of an address. The box already solves
both (see part 1); this part makes the store side use it.

## The representation already in place

`MojoBox` (`runtime/fire_runtime.c`, the `kind` byte) plus:

- `mojo_box_from_double(double)` — a fresh kind-`'d'` box; `mojo_box_double`
  reads it back, `mojo_repr_boxed` renders it, `mojo_box_word` keeps the box
  (a float has no int64_t spelling).
- `mojo_box_int(int64_t)` — unwraps any non-float box to its word and
  truncates a double box to its integer; this is why a fresh float box must
  **not** be passed through the existing `mojo_box_int` arm below.
- `mojo_cstr_or_int_str` / `mojo_word_cstr_value` — the `print`/value
  consumers, both already spell a kind-`'d'` box by its value.
- The codegen's existing "tagged word" tracking:
  `gen._boxed_vals` (a value name that is a box), `gen._tagged_word_vals`
  (a tagged word of a mixed generator), `gen._dyn_word_locals` /
  `gen._dyn_word_vals` (a word whose kind only the runtime knows), and
  `ginf.tagged_mixed_name(gen, name)` (this name is bound to a tagged word
  *and* to a plain value, so `tagged_next_bind_name` answers False).

`ginf.tagged_mixed_name` is exactly the predicate this part needs: it already
answers True for every "tagged word + float" name, because the float binding
is a non-`IdentExpr`/non-`next` binding. It early-exits when the module has no
mixed-slot generator, and is already called on the int64 bind path, so using
it here adds no new body walk.

## Scope

In `mojo/backend_gimple/emit_stmts.py`'s simple-name assignment arm (the block
around the `MIXED_NAME_NON_INT64_REFUSAL` raise):

1. **Box a double store into a mixed tagged name.** When
   `ginf.tagged_mixed_name(gen, name)` is true and the lowered `vtype` is a
   scalar float type (`double`; cast `float` through `(double)`), replace the
   refusal with:
   - `v = gen._call_expr('int64_t', 'mojo_box_from_double', [('double', v)])`,
   - `vtype = 'int64_t'`,
   - `_keep_tagged_box = True`.
   The local is then declared `int64_t` and registered in `_boxed_vals` /
   `_tagged_word_vals` / `_dyn_word_locals` by the existing
   `if _keep_tagged_box:` arm, exactly as an `x = 0` mixed-int store is.
2. **Do not re-box the box.** The existing mixed-name arm just below the
   refusal (`if not _keep_tagged_box and vtype == 'int64_t' and ...
   ginf.tagged_mixed_name(...)`) wraps a plain `int64_t` value in
   `mojo_box_int`. A fresh `mojo_box_from_double` box must never reach it:
   `mojo_box_int` on a `'d'` box returns the truncated integer (`1.5` -> `1`,
   `None` -> `0`). Setting `_keep_tagged_box = True` in the same block is the
   intended way past it; do not add an `_boxed_vals` entry for the temporary
   and rely on the later `elif ... mojo_box_word` arm either (that arm would
   unwrap a `str` box once part 3 lands, and `mojo_box_word` keeps only the
   float box unchanged).
3. **Keep every other kind refused for now.** A `str` store is part 3; a
   container/struct pointer is not in step 2's scope (the box has no
   constructor for an arbitrary live container at this site, and a `list`
   store into a tagged name is a separate shape). Keep the refusal for
   `char *` and other pointer `vtype`s exactly as it is, so part 3 is the
   only change that lifts the string case.
4. **The reverse guard.** The first half of the refusal
   (`_tagged_bind and ginf.is_non_int_c_type(gen.var_types.get(tname))`)
   protects a tagged value stored into a slot already declared `double`.
   After this part every mixed tagged name is declared `int64_t` by the
   `_keep_tagged_box` arm, so that arm should not fire; leave it as an
   internal-error guard rather than deleting it (deleting the whole refusal
   is step 4 of the plan, and is not this part).

No change is needed to the declaration arm at
`if tname not in gen.var_types:`: the `_keep_tagged_box` arm declares the
local `int64_t` for the *first* store as well, so a float-first name never
gets pinned to `double`. Verify that when you land it; if a shape still takes
the first-declaration arm before the box arm, gate that arm's
`_pin_to_ground_truth` on `ginf.tagged_mixed_name` as `_mixed` is gated --
do not add a second predicate that answers the same question.

## Files

- `mojo/backend_gimple/emit_stmts.py` — the store arm.
- `test_gimple_generator_runner.py` — `run_tagged_for_target_bind_tests`.

## Test

In `test_gimple_generator_runner.py`'s `run_tagged_for_target_bind_tests`,
replace the two float refusal fixtures with CPython-oracle cases (the helper
`test_generator_matches_cpython` runs the same text through CPython, so a
written-down expected string cannot drift):

1. `_mixed_float` becomes `tagged_for_target_copy_into_float`:
   ```
   def g():
       yield 1
       yield None
       yield 2
   def main():
       x = 0.5
       print(x)
       for v in g():
           x = v
           print(x)
           print(x == None)
       x = 2.5
       print(x)
       print(x + 1.0)
       print(x * 2)
       print(x > 1.0)
   main()
   ```
   CPython output: `0.5`, `1`, `False`, `None`, `True`, `2`, `False`,
   `2.5`, `3.5`, `5.0`, `True`.
2. `_mixed_after` becomes `tagged_for_target_plain_float_store_after_copy`:
   a plain `x = 0` first, the tagged copy, then `x = 2.5`, printing
   `1`, `None`, `2`, `2.5`.
3. Remove `tagged_for_target_copy_into_float_refused` and
   `tagged_for_target_plain_float_store_after_copy_refused`; they assert the
   refusal this part deletes for floats.
4. Keep `tagged_for_target_copy_into_str_refused` — the string case is still
   part 3.

The cpp escape hatch (`with coro.pinned('cpp')`) is a separate emitter; do
not pin these cases to it unless the cpp path already lowers the shape. If it
does, add the pinned twin; if it refuses, say so in this doc's Status instead
of making the A3 case pretend to cover it.

## Acceptance

```
python3 tools/memslot.py --gb 8 --label gemgen-float -- python3 test_gimple_generator_runner.py
```

The whole file is the registered `gimplegenerators` job, and is the narrowest
thing that covers the change (the other cases in it exercise the same
assignment arm). It must end with no failures; at minimum the three new
`tagged_for_target_*_float*` cases must print `PASS`, and
`tagged_for_target_copy_into_str_refused` must still `PASS`.

## Status

Not started. Depends on part 1 only for the runtime-contract test (the box
itself is already in `runtime/fire_runtime.c`).
