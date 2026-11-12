# DIAGNOSTICS trait conformance part 2: trait method requirement evidence at use sites

Class: **mid** (this doc lives in `bugs/mid/`). It needs a parser/AST field for
method `where` clauses, the shared conformance model from part 1, and call-site
plumbing in both generic-instantiation routes.

Parent: `bugs/hard/DIAGNOSTICS_trait_conformance.md` (SPLIT into parts 1-7);
plan: `docs/diagnostics-missing-validation-plan.md` §2, sub-steps 2a (method
half) and 2e.

## Scope

The single-candidate evidence cases from
`mojo/test/mojo-parser/decls/struct_conditional_trait_conformance_errors.mojo`,
plus MOCO-4400:

- `UnconditionalWithConditionalMethod` — an unconditional conformance provides
  no assumptions, so a method with `where Self.x > 10` cannot be proven:
  `does not implement all requirements for 'UnconditionalConformanceTrait'`.
- `MismatchedConstraints` — conformance requires `T: Intable`, method requires
  `T: Copyable`: `does not implement all requirements for
  'MismatchedConstraintTrait'`.
- `WeakerConformanceStrongerMethod` — conformance requires `T: Copyable`,
  method requires `Copyable and Intable`: `does not implement all requirements
  for 'WeakerConformanceTrait'`.
- `ConditionalDefaultMethod` — calling a synthesized conditional default method
  from a context that only knows `T: Movable`:
  `lacking evidence to prove correctness`.
- `ZeroFieldConditional` — the same rule on a zero-field struct:
  `lacking evidence to prove correctness`.
- `Moco4214List` — a constrained comptime member used as a result type in an
  unprovable environment:
  `invalid bindings in signature: lacking evidence to prove correctness`
  (the modular note says `add a trailing 'where' clause`).
- MOCO-4400 (`moco_4400_no_crash_on_bind_parameter.mojo`) — `S[T]`
  conditionally conforms to `Iterator` only where `T: Movable`;
  `needs_iterator(S(NotMovable(1)))` must report
  `'S[T]' does not implement all requirements for 'Iterable'` and must not
  crash or hang.

Positive controls: a conformance constraint that implies the method's clause
(e.g. conformance `T: Copyable`, method `where conforms_to(Self.T, Copyable)`)
still compiles; a struct with no conditional methods still satisfies its trait;
the same `S` instantiated with a `Movable` element satisfies `Iterator`;
`compile_to_gimple` returns normally rather than raising
`RecursionError`/`MemoryError` on the MOCO source.

## Current state (measured 2026-11-10)

A reduced `Wrapper[T]` with
`Printable where conforms_to(T, Printable)` and an unsound
`needs_printable(x)` call compiled silently (25,041 bytes of gimple). A reduced
MOCO shape (`S[T]` with conditional `Movable`, `needs_movable(S(NotMovable))`)
also compiled silently. The parser currently discards every method `where`
clause: `_parse_funcdef` skips it at `fire_compiler.py:~4604`, and
`FunctionDef` has no field for it.

## Implementation notes

1. **Retain the method clause.** Add `FunctionDef.where_clause: str = ''` (or
   an expression node) and capture the text `_parse_funcdef` currently skips.
   Keep the field additive and register it in
   `mojo/backend_gimple/module_gen.py`'s `struct_field_types['FunctionDef']`
   table (`char *`) for the self-hosted build. Do not change `params` or the
   runtime signature.

2. **Extend the existing checker, do not add a second one.** `elaborate.py`
   already owns `extract_trait`, `type_methods`, `check_conformance`, and
   `check_bounds`; the last is called from the in-TU pre-pass
   (`mojo/backend_gimple/emit_resolve.py:~3196`) and the `.o` route
   (`mojo/backend_gimple/elab_intu.py:~3733`). Add one evidence evaluator
   there and call it from both routes:
   - build the conformance assumption set from the struct's base constraint
     (part 1's `base_constraints`);
   - for each required method, evaluate its `where_clause` against those
     assumptions with the same conservative implication rules as part 1
     (`and`/`or`/`conforms_to` only; unknown ⇒ accept);
   - a requirement with no clause, or a clause implied by the conformance, is
     satisfied; a non-implied clause yields the requirement diagnostic.

   `check_conformance` currently compares concrete method signatures only and
   requires every trait method to be defined by the struct. Keep its
   signature comparison, but route the requirement decision through the new
   evidence evaluator so `Self.T`/`Self.x` can be substituted from the
   instantiation.

3. **Report the modular wording.** The exact observable is the modular error
   line `does not implement all requirements for '<Trait>'`. Prefix it with
   the struct instantiation only if the existing diagnostic style already has
   one; the regression asserts the stable substring. For `Moco4214List` use
   the distinct signature-binding message and its `add a trailing 'where'
   clause` note.

4. **MOCO-4400.** This is the same evidence rule applied to a bound at a call
   site, not a new mechanism: `needs_iterator[I: Iterator]` requires the
   argument to conform to `Iterator`; the struct's conditional conformance is
   not satisfied for `NotMovable`. Follow the trait ancestor graph from part 1
   so the diagnostic names `Iterable` (the modular message) rather than the
   child trait. The no-crash half is a consequence of reporting before
   monomorphising the impossible instantiation; add a hard timeout watch in
   the regression so a future hang is a failure, not a stuck CI job.

5. **Do not report on unknown evidence.** A generic `T` whose conformance
   cannot be decided, a struct defined in another module whose base list this
   unit cannot see, and a trait with no parsed requirements all keep the
   current accept behaviour. Every diagnostic in this part is restricted to
   cases the checker can prove.

## Acceptance check

Add `test_trait_requirement_evidence_diagnostic.py` (next to the other
`test_*_diagnostic.py` files; do NOT register it in `tools/suite.py`). Use
reduced, self-contained sources with local traits only:

- the six `does not implement`/`lacking evidence` cases above each raise
  `RuntimeError` containing the exact modular message; the `Moco4214List` case
  also contains `add a trailing 'where' clause`;
- the MOCO source raises containing
  `'S[T]' does not implement all requirements for 'Iterable'`, and the call
  returns within the test's timeout (no hang, no crash);
- the four positive controls compile.

Run only that file, under the memory wrapper:

    python3 tools/memslot.py --gb 8 --label trait-conformance-p2 -- \
        python3 test_trait_requirement_evidence_diagnostic.py

## Not in this part

Part 1 (declaration-time unconditional/conditional consistency), part 3
(ambiguous/unprovable overload candidates), part 4 (copy/move synthesis),
part 5 (comptime member types), part 6 (defaulted trait methods), part 7
(downcast witness tables).
