# DIAGNOSTICS trait conformance part 3: overload candidate selection under conditional conformance

Class: **mid** (this doc lives in `bugs/mid/`). It is the three-valued
candidate rule over the evidence evaluator built by part 2; the "unprovable
candidate blocks selection" rule is the part that is easy to get wrong.

Parent: `bugs/hard/DIAGNOSTICS_trait_conformance.md` (SPLIT into parts 1-7);
plan: `docs/diagnostics-missing-validation-plan.md` §2, sub-step 2a (the
candidate-selection half).

## Scope

From `mojo/test/mojo-parser/decls/struct_conditional_trait_conformance_errors.mojo`:

- `AmbiguousUnconditionalAndConditional` — an unconditional `perform` and a
  conditional `perform` that is implied by the conformance are both valid
  candidates: `does not implement all requirements for
  'AmbiguousMethodTrait'`, with `ambiguous use of 'perform'` notes on both
  candidates.
- `AmbiguousBothConditional` — two conditional `run` methods, both implied by a
  stronger conformance (`Copyable and Intable`): same error for
  `MultipleConditionsTrait`.
- `UnprovableWithValidCandidate` — one candidate is provable, one is
  unprovable (`Intable` vs conformance `Copyable`). The unprovable candidate
  still blocks selection: `does not implement all requirements for
  'UnprovableCandidateTrait'`.
- `DisprovedWithWhereNot` — `where not conforms_to(Self.T, Copyable)` is
  disproved by the conformance and is therefore NOT a candidate. The
  requirement is unwitnessed: `does not implement all requirements for
  'ContradictingConstraintTrait'`, and the note lists the candidate with its
  clause.

Positive control: exactly one provable candidate and every other candidate
disproved selects the provable one and compiles; a single unconditional
candidate compiles.

## Current state (measured 2026-11-10)

The parser retains neither the struct conformance constraint nor the method
`where` clause, so every one of these structs compiles silently. A reduced
conditional-conformance struct with an unsound call produced 25,041 bytes of
gimple and no diagnostic.

## Implementation notes

1. **Reuse part 2's evaluator.** Part 2 adds `FunctionDef.where_clause` and the
   `where`-clause implication test in `elaborate.py`. This part adds a second
   output from that test: `PROVABLE`, `DISPROVED`, or `UNPROVABLE` for one
   candidate under the conformance assumptions. Do not duplicate the
   boolean/`conforms_to` parser.

2. **Candidate table.** For each trait requirement (name + arity), collect
   every struct method of that name with its `where_clause`. Evaluate each
   candidate under the struct's conformance constraint:
   - `DISPROVED` when the clause is the negation of an assumption (directly,
     or an `and` with a disproved conjunct);
   - `PROVABLE` when the clause follows from the assumptions by part 1's
     implication rules;
   - `UNPROVABLE` otherwise (including conditions this checker does not model,
     which stay unprovable rather than guessed).

   The selection rule is the one the modular test documents:
   - any `UNPROVABLE` candidate ⇒ error, even when another candidate is
     `PROVABLE` (`UnprovableWithValidCandidate`);
   - more than one `PROVABLE` candidate ⇒ error (`ambiguous use of '<name>'`);
   - no `PROVABLE` candidate ⇒ the requirement is unwitnessed
     (`DisprovedWithWhereNot`);
   - exactly one `PROVABLE` and all others `DISPROVED` ⇒ satisfied.

3. **Report where the declaration is.** Emit at the struct's line, from the
   same `all_struct_defs` pre-pass as part 1
   (`mojo/backend_gimple/module_gen.py`, near `_merge_struct_inheritance`).
   The modular notes point at the candidate declarations; add them as note
   lines when the location is available, but keep the `error:` line exact.
   Do not emit at a call site: the requirement is a property of the struct.

4. **Conservative default.** A trait whose requirements are not parsed (no
   local `TraitDef`, a builtin stdlib trait) produces no candidate error. A
   method with no `where` is unconditional and therefore `PROVABLE`; that is
   what makes `AmbiguousUnconditionalAndConditional` fire.

## Acceptance check

Add `test_conditional_conformance_candidate_diagnostic.py` (next to the other
`test_*_diagnostic.py` files; do NOT register it in `tools/suite.py`). Use
reduced, self-contained sources with local traits only:

- each of the four cases raises `RuntimeError` containing the exact
  `does not implement all requirements for '<Trait>'` line; the ambiguity
  cases also contain `ambiguous use of '<method>'` in a note;
- the two positive controls compile.

Run only that file, under the memory wrapper:

    python3 tools/memslot.py --gb 8 --label trait-conformance-p3 -- \
        python3 test_conditional_conformance_candidate_diagnostic.py

## Not in this part

Part 1 (declaration-time consistency), part 2 (single-candidate evidence),
part 4 (copy/move synthesis), part 5 (comptime member types), part 6
(defaulted trait methods), part 7 (downcast witness tables).
