# DIAGNOSTICS trait conformance part 6: defaulted trait method conformance

Class: **mid** (this doc lives in `bugs/mid/`). It changes the trait
requirement checker's treatment of methods with bodies and the substitution
of their parametric return types; it is not a parser-only check.

Parent: `bugs/hard/DIAGNOSTICS_trait_conformance.md` (SPLIT into parts 1-7);
plan: `docs/diagnostics-missing-validation-plan.md` §2, sub-step 2b.

## Scope

`mojo/test/mojo-parser/decls/defaulted_trait_method_bad_conformance.mojo`:

- `Map[Strat: Strategy, Dest: Copyable, mapFn: def (Strat.Value) thin ->
  Dest](Strategy)` implements `value`, but relies on `Strategy`'s defaulted
  `map`. The default's return type is `Map[mapper]`, which supplies only one of
  `Map`'s three parameters. The struct therefore does not satisfy `Strategy`:
  - `error: 'Map[mapFn]' does not implement all requirements for 'Strategy'`

Positive controls: a defaulted method returning `Self` or a fully-applied
struct type (`Map[Self.Strat, Self.Dest, mapper]`) satisfies the trait; a
struct that implements `map` itself overrides the default and compiles.

## Current state (measured 2026-11-10)

A reduced `Strategy`/`Map` pair compiled silently (26,342 bytes of gimple).
`elaborate.extract_trait` returns every trait method's signature, and
`check_conformance` requires the struct to define every one of them — it does
not distinguish a defaulted body from an abstract `...` body, and it is only
consulted when a generic is instantiated, not when a conforming struct is
declared.

## Implementation notes

1. **Separate defaults from requirements.** A trait method is a *default*
   when its body is a real body (not only `...`/`pass`); modular's `Strategy`
   spells the default `map` with a `return`. Keep it in `TraitDef.methods`
   (the parser already stores it); mark it in the requirement checker rather
   than deleting it, because a struct may still call it and a struct may
   override it.

2. **Check declaration-time conformance.** Call the extended checker from the
   same `all_struct_defs` pre-pass as parts 1-5
   (`mojo/backend_gimple/module_gen.py`, near `_merge_struct_inheritance`),
   not only from `check_bounds`. For each trait base with no conditional
   constraint, every required (non-default) method must be supplied by the
   struct; a default method is inherited.

3. **Substitute the default into the struct.** For an inherited default, form
   its signature with the struct's type parameters in scope and instantiate
   the types the default mentions:
   - `Self` and `Self.<member>` resolve against the struct;
   - an application of the conforming struct must bind all of the struct's
     type parameters;
   - if the default's return type applies the struct to a subset (modular's
     `Map[mapper]` against `Map[Strat, Dest, mapFn]`), the requirement cannot
     be formed and the struct is non-conforming.

   Report `'<Struct>[<the parameters the default supplied>]' does not
   implement all requirements for '<Trait>'` at the struct's line, matching
   the modular `'Map[mapFn]'` spelling. The diagnostic is about the struct,
   not the default's declaration.

4. **Do not break ordinary defaults.** A default whose signature is
   instantiable must NOT produce an error, and a struct's own method of the
   same name must win over the default. Keep the existing signature comparison
   for non-default methods; only the default-substitution arm is new.

5. **Unknown stays accepted.** A trait from another module whose default bodies
   this unit cannot parse, and a default whose return type this checker cannot
   instantiate, are accepted (no false positives), consistent with parts 2-5.

## Acceptance check

Add `test_defaulted_trait_method_conformance_diagnostic.py` (next to the other
`test_*_diagnostic.py` files; do NOT register it in `tools/suite.py`). Use a
reduced, self-contained `Strategy`/`Map` pair copied from the modular shape
(the `map` default returns the partially-applied struct type):

- the negative case raises `RuntimeError` containing
  `does not implement all requirements for 'Strategy'` and the
  `'Map[mapFn]'` instantiation name;
- both positive controls compile.

Run only that file, under the memory wrapper:

    python3 tools/memslot.py --gb 8 --label trait-conformance-p6 -- \
        python3 test_defaulted_trait_method_conformance_diagnostic.py

## Not in this part

Parts 1-5 (constraint declarations, method evidence, candidate selection,
copy/move synthesis, comptime member types), part 7 (downcast witness tables).
