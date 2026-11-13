# DIAGNOSTICS trait conformance part 5: trait comptime member types (including enum exhaustiveness)

Class: **mid** (this doc lives in `bugs/mid/`). It needs the trait-requirement
model extended to `comptime` members, plus retaining the annotation and
`where` clause the parser currently discards.

Parent: `bugs/hard/DIAGNOSTICS_trait_conformance.md` (SPLIT into parts 1-7);
plan: `docs/diagnostics-missing-validation-plan.md` §2, sub-step 2c.

## Scope

- `enum_exhaustive_errors.mojo`: an enum's `comptime _enum_is_exhaustive = 5`
  is not the `Bool` that `EnumLike` requires:
  - `error: 'Mistyped' does not implement all requirements for 'EnumLike'`
  - `note: comptime member '_enum_is_exhaustive' type 'IntLiteral[5]' does not
    conform to trait's required type 'Bool'`
  - `note: trait 'EnumLike' declared here`
- `CondAliasNotImpliedStruct` from
  `struct_conditional_trait_conformance_errors.mojo`: the struct's
  `comptime SIZE: Int where Self.n >= 10 = Self.n` is constrained by a clause
  the conformance constraint (`n >= 0`) does not imply:
  `'CondAliasNotImpliedStruct[n]' does not implement all requirements for
  'CondAliasNotImplied'`, with the `comptime member 'SIZE' type ... does not
  conform to trait's required type 'Int'` note.

Positive controls: `comptime _enum_is_exhaustive = True` satisfies a local
`EnumLike` requirement; a struct whose `where` clause is implied by the
conformance (`comptime SIZE: Int where Self.n >= 0 = Self.n` under conformance
`n >= 0`) compiles.

## Current state (measured 2026-11-10)

A reduced `__enum Mistyped(ImplicitlyCopyable): ... comptime
_enum_is_exhaustive = 5` compiled silently (25,145 bytes with the constrained
`CondAliasNotImpliedStruct` shape). The parser throws away exactly the two
pieces this part needs:

- `fire_compiler._parse_trait` (~5118-5140) keeps only `FunctionDef`s from a
  trait body, so a trait's `comptime NAME: Type` requirement is lost;
- `_parse_comptime` parses and `comptime_aliases` stores only `target -> value`;
  `ComptimeVarStmt` has no `type_ann` and no `where_clause` field, although the
  parser already parses the annotation and the trailing clause at
  `fire_compiler.py:~5309-5365` and discards both.

## Implementation notes

1. **Retain the member declaration.** Add `ComptimeVarStmt.type_ann` (str/None)
   and `ComptimeVarStmt.where_clause` (str/empty), populated from the tokens
   the parser already reads and throws away. Keep `StructDef.comptime_aliases`
   unchanged for its many value readers; add a parallel
   `comptime_member_types: dict[str, str]` (or a small member table) only if a
   separate reader is cleaner. Register the new `ComptimeVarStmt` fields in
   `mojo/backend_gimple/module_gen.py`'s `struct_field_types` table for the
   self-hosted build.

2. **Retain trait requirements.** `TraitDef` gets a `comptime_members` list of
   `(name, type_ann, where_clause)` and `_parse_trait` collects
   `ComptimeVarStmt`s as well as `FunctionDef`s. Register the new
   `TraitDef` field in the same table. Do not infer trait members from the
   struct side; the requirement has to come from the trait declaration.

3. **Enum member typing.** `__enum` is parsed by `_parse_struct` into a
   `StructDef` whose members are comptime aliases (`_build_enum_struct` /
   `_parse_enum`). For a member with no annotation, derive the note's type name
   from the literal value (`IntLiteral[5]`, `BoolLiteral`/`Bool` for
   `True`), so the mandatory `_enum_is_exhaustive` requirement can compare it
   to `Bool`. The diagnostic's decision is the comparison; the exact literal
   spelling in the note is cosmetic, but the modular note is the model.

4. **Shared check.** Extend the `elaborate.py` requirement checker from
   parts 2-3 (called from the `all_struct_defs` pre-pass) with a comptime-member
   arm:
   - the required member must exist;
   - its declared type must conform to the required type (`Bool`, `Int`,
     `AnyType`, ...);
   - its `where` clause, if any, must be implied by the struct's conformance
     constraint using the same conservative implication rules.

   A constrained member under an unprovable clause fails with the modular
   `does not implement all requirements` error, and the note names the member.
   Unknown types remain accepted.

5. **Trait ancestry for `EnumLike`.** `EnumLike` is a real trait with an
   implicit enum conformance in modular; this tree has no stdlib copy. The
   regression should declare a local `trait EnumLike` with the comptime
   requirement so the test does not depend on an external stdlib. The
   implementation must not hard-code the name `EnumLike`; it is just one trait
   with a comptime requirement.

## Acceptance check

Add `test_trait_comptime_member_conformance_diagnostic.py` (next to the other
`test_*_diagnostic.py` files; do NOT register it in `tools/suite.py`). Use
reduced, self-contained sources with local traits only:

- the enum case raises `RuntimeError` containing
  `does not implement all requirements for 'EnumLike'` and the note substring
  `comptime member '_enum_is_exhaustive'`;
- the `CondAliasNotImpliedStruct` case raises containing
  `does not implement all requirements for 'CondAliasNotImplied'` and
  `comptime member 'SIZE'`;
- both positive controls compile (including `comptime _enum_is_exhaustive =
  True`).

Run only that file, under the memory wrapper:

    python3 tools/memslot.py --gb 8 --label trait-conformance-p5 -- \
        python3 test_trait_comptime_member_conformance_diagnostic.py

## Not in this part

Parts 1-4 (constraint declarations, method evidence, candidate selection,
copy/move synthesis), part 6 (defaulted trait methods), part 7 (downcast
witness tables).
