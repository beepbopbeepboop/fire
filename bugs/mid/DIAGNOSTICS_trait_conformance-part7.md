# DIAGNOSTICS trait conformance part 7: downcast witness-table diagnostic

Class: **mid** (this doc lives in `bugs/mid/`). `downcast` currently survives
only as a text substitution in parametric aliases; the expression form
`rebind[downcast[T, Trait]](x)` has no elaboration path to report from.

Parent: `bugs/hard/DIAGNOSTICS_trait_conformance.md` (SPLIT into parts 1-7);
plan: `docs/diagnostics-missing-validation-plan.md` §2, sub-step 2d.

## Scope

`mojo/test/mojo-integration/invalid_downcast_error.mojo`:

- `Foo` declares `ImplicitlyCopyable` but not `Writable`;
- `invalid[T: ImplicitlyCopyable & Deinitable]` performs
  `print_foo_invalid(rebind[downcast[T, Writable]](x))` and is called with
  `Foo`;
- modular reports:
  - `error: function instantiation failed`
  - `note: struct 'invalid_downcast_error::Foo' does not have witness table for
    trait 'std::format::__init__::Writable'`

Positive controls: `downcast[T, Trait]` where the concrete type does declare
the trait compiles; `downcast[T, Trait]` where `T` is still a generic parameter
(no concrete witness can be decided) is accepted.

## Current state (measured 2026-11-10)

A reduced `rebind[downcast[T, LocalWritable]](x)` with a local trait compiled
silently (25,017 bytes of gimple). `downcast[...]` is recognised only in
`mojo/backend_gimple/elab_intu._eval_parametrized_aliases`
(`~3449-3453`), which strips it and keeps the first argument when evaluating a
parametric alias, and in `mojo/middle/iter_factory._downcast_sub`, which is a
string helper for iterator aliases. There is no witness-table check anywhere,
and no field or runtime witness table to consult.

## Implementation notes

1. **Recognise the expression form.** `rebind[downcast[T, Trait]](x)` is a
   call whose callee is a subscripted `rebind` over a subscripted `downcast`.
   Find where that call is lowered (the `rebind`/subscripted-call path in
   `mojo/backend_gimple/emit_calls.py`/`emit_exprs.py`, or the elaboration
   pre-pass that already rewrites `rebind_var[...]`) and get the two type
   arguments as source/type text. Do not add a second parser for
   `downcast[...]`; reuse the existing bracket-splitting helper.

2. **Decide conformance with the shared checker.** Once the first argument
   resolves to a concrete same-module struct, ask the conformance checker from
   parts 1-2 whether that struct declares or conditionally conforms to the
   second argument's trait. A concrete struct that does not declare the trait
   is the error case; a conditional conformance that is not provably satisfied
   is also an error (the witness is absent), but an undecidable/generic type is
   accepted.

3. **Report the modular wording.** Raise the compile error with:
   - `error: function instantiation failed`
   - `note: struct '<module>::<Struct>' does not have witness table for trait
     '<Trait>'`

   Use the best qualified names the unit has (`<filename stem>::Foo` is enough
   for the modular shape); the regression asserts the stable substrings
   `function instantiation failed` and `does not have witness table for trait`.
   Emit at the call's line.

4. **Keep alias evaluation unchanged.** Parametric aliases deliberately
   evaluate `downcast[X, Trait]` to `X` (`elab_intu` above). This part adds the
   check for the *expression* form; changing the alias path would break every
   stdlib iterator alias. If a witness check is wanted there too, it is a
   separate follow-up, and the acceptance here must not require it.

5. **No runtime witness table.** This is a diagnostic only; do not invent a
   vtable or change the `TraitDef_vtable` emission in `module_gen.py`.

## Acceptance check

Add `test_downcast_witness_diagnostic.py` (next to the other
`test_*_diagnostic.py` files; do NOT register it in `tools/suite.py`). Use a
local `trait LocalWritable` and a local `Foo(ImplicitlyCopyable)` so the test
does not import modular's stdlib:

- the negative case raises `RuntimeError` containing
  `function instantiation failed` and
  `does not have witness table for trait`;
- the concrete-conforming and generic-`T` positive controls compile.

Run only that file, under the memory wrapper:

    python3 tools/memslot.py --gb 8 --label trait-conformance-p7 -- \
        python3 test_downcast_witness_diagnostic.py

## Not in this part

Parts 1-6 (declaration constraints, method evidence, candidate selection,
copy/move synthesis, comptime member types, defaulted trait methods).
