# DIAGNOSTICS trait conformance part 4: copy/move construction under conditional conformance

Class: **mid** (this doc lives in `bugs/mid/`). It needs the conformance
evidence from parts 1-2 and a declaration-time field-type walk; it is not a
codegen-only change.

Parent: `bugs/hard/DIAGNOSTICS_trait_conformance.md` (SPLIT into parts 1-7);
plan: `docs/diagnostics-missing-validation-plan.md` §2, sub-step 2a (the
synthesized-constructor cases in the same modular file).

## Scope

From `mojo/test/mojo-parser/decls/struct_conditional_trait_conformance_errors.mojo`:

- `CopySynthFailsWithOR` — `Copyable where conforms_to(T, Copyable) or
  conforms_to(T, Intable)`; an OR-gated constraint is not definite enough to
  synthesize the copy constructor for field `value`:
  `cannot synthesize copy constructor because field 'value' has non-copyable
  type`.
- `CopySynthFailsMultiField` — the constraint covers `T` but not `U`; copy
  synthesis fails on `second`:
  `cannot synthesize copy constructor because field 'second' has non-copyable
  type`.
- `UnsatisfiedVariadicCopySynthesis` — a field of
  `NegativeVariadicCopyField[Int, T]`, whose conditional `Copyable` conformance
  (`Ts.all_conforms_to[Copyable]()`) is not implied by the enclosing struct:
  `cannot synthesize copy constructor because field 'field' has non-copyable
  type`.
- `UnsatisfiedVariadicMoveSynthesis` — the move counterpart:
  `cannot synthesize move constructor because field 'field' has non-movable
  and non-implicitly-copyable type`.

Positive controls: a struct whose `Copyable`/`Movable` conformance is
unconditional and whose fields are copyable/movable still synthesizes both
constructors; a struct whose conditional constraint covers every type
parameter used by the field still synthesizes.

## Current state (measured 2026-11-10)

A reduced `CopySynthFailsWithOR` struct compiled silently (25,107 bytes of
gimple). Copy construction is currently lowered in
`mojo/backend_gimple/emit_methods.py`'s `.copy()` fallback (synthesized
fieldwise copy, ~4453-4585); that path has no place to report a declaration
error and runs per use site. `ownership_check.py` has the closest existing
type walk (`_struct_def_is_trivial`, `_type_ann_is_trivial`) and already notes
that it cannot see the `where` clause.

## Implementation notes

1. **Diagnose at declaration time.** Add the check to the same
   `all_struct_defs` pre-pass as parts 1-3
   (`mojo/backend_gimple/module_gen.py`, near `_merge_struct_inheritance`), or
   to the shared `elaborate.py` checker that pass calls. Do not put the
   diagnostic in `emit_methods.py`: the fallback is emitted only for the uses
   the module happens to make, so a struct with no `.copy()` call would escape
   the check.

2. **Only conditionally-deferred fields are errors.** For each field, resolve
   its declared type against the module's structs. A field is a problem for
   synthesized `Copyable`/`Movable` only when:
   - the field's type has a conditional `Copyable`/`Movable` conformance (or a
     variadic helper such as `Ts.all_conforms_to[Copyable]()`), and
   - the enclosing struct's own conformance constraint does not imply that
     field type's condition for the instantiation being declared.

   A genuinely non-copyable field type (no `Copyable` conformance at all) is
   out of scope here: that is a different diagnostic and must not be invented
   in this part. An OR-gated constraint is specifically NOT definite enough
   (the modular comment explains why: the compiler cannot tell which disjunct
   holds).

3. **Use the evidence evaluator, conservative default.** Part 2's
   `PROVABLE`/`DISPROVED`/`UNPROVABLE` result applies here too. For copy
   synthesis, an OR constraint is `UNPROVABLE`; an unprovable field is
   rejected. For an unknown field type or an imported generic whose conformance
   this unit cannot see, accept (no false positives). This preserves the
   existing fieldwise-copy lowering for the cases that work today.

4. **Message and location.** Emit at the offending field's line with the exact
   modular text, including the field name. The move message has the longer
   `non-movable and non-implicitly-copyable type` spelling. Note that
   `Movable where False` is a real non-movable spelling; do not treat it as
   unknown.

5. **No duplicated type walk.** Reuse `ownership_check._type_ann_is_trivial`'s
   annotation resolution shape (or factor that helper) rather than adding a
   second field-type parser; the two checks must agree about what a field's
   declared type is.

## Acceptance check

Add `test_conditional_conformance_synthesis_diagnostic.py` (next to the other
`test_*_diagnostic.py` files; do NOT register it in `tools/suite.py`). Use
reduced, self-contained sources with local traits only:

- the four cases raise `RuntimeError` containing the exact `cannot synthesize
  ...` line (assert the field name in each);
- the two positive controls compile.

Run only that file, under the memory wrapper:

    python3 tools/memslot.py --gb 8 --label trait-conformance-p4 -- \
        python3 test_conditional_conformance_synthesis_diagnostic.py

## Not in this part

Parts 1-3 (constraint model, method evidence, candidate selection), part 5
(comptime member types), part 6 (defaulted trait methods), part 7 (downcast
witness tables).
