# DIAGNOSTICS trait conformance part 1: conditional conformance declarations and conditional RegisterPassable

Class: **mid** (this doc lives in `bugs/mid/`). It needs the shared parser/AST
work below, including the self-host field tables; it is not a one-line check.

Parent: `bugs/hard/DIAGNOSTICS_trait_conformance.md` (SPLIT into parts 1-7);
plan: `docs/diagnostics-missing-validation-plan.md` §2, sub-step 2a.

## Scope

The declaration-time half of conditional conformance, from
`mojo/test/mojo-parser/decls/struct_conditional_trait_conformance_errors.mojo`:

- `DiamondMissingExplicitBase` — an ancestor reached through two different
  conditional paths must be listed explicitly.
- `DerivedDoesNotImplyAncestor` — a derived trait's constraint must imply the
  explicitly listed ancestor's constraint.
- `UnconditionalDerivedConditionalAncestor` — an unconditionally listed derived
  trait whose ancestor is listed conditionally is inconsistent.
- `ConditionalTrivialRegPassable` — conditional conformance to
  `TrivialRegisterPassable` is not supported.
- `RPTraitWeakerConstraint` — a derived RP trait's weaker constraint does not
  imply the explicit `RegisterPassable` constraint.
- `bad_conditional_rp_origin` — returning `ref[x]` from a
  conditionally-`RegisterPassable` argument is rejected because `x` might
  expand to an RP type and the origin would dangle.

Positive controls that must keep compiling: `ConditionalRegPassable`
(conditional `RegisterPassable` is allowed), `NoExplicitRPConformsToRPTrait`
(canonical ancestor propagation), and `ok_conditional_rp_ref_origin` (`ref`
forces indirect passing, so the origin is stable).

## Current state (measured 2026-11-10)

All of these compile silently today. A reduced struct with
`Copyable where conforms_to(T, Copyable)` and an unsound call through a
`T: Copyable` bound produced 25,041 bytes of gimple with no diagnostic.
`ownership_check.py` already records the root cause for its own triviality
rule: "this parser drops the `where` clause and the `not` in the base soup, so
the clause is unobservable here" (`_struct_def_is_trivial`).

## Implementation notes

1. **Retain the base constraint.** `fire_compiler._parse_struct`'s base-list
   loop (`~4788-4841`) walks tokens only to collect the trailing name in
   `StructDef.bases`; a `where conforms_to(...)` after a base is discarded.
   `_parse_trait` (`~5118-5140`) skips the parenthesised trait list entirely,
   so trait ancestry is lost too.

   Keep `StructDef.bases` exactly as it is (list of base *names*) — it is read
   by `myinterpreter.execute_StructDef`, `gimple_codegen`, and the inheritance
   merge. Add a parallel field, e.g. `base_constraints: list[tuple[str, str]]`
   (one `(base_name, where_text)` per positional trait base, `where_text` empty
   when unconditional), and add `TraitDef.bases: list[str]` for the parent
   trait list. Do not encode the constraint in the base name string; name
   readers would then have to strip it everywhere.

   The constraint text is an expression (`conforms_to(T, Copyable)`,
   `conforms_to(T, Copyable) and conforms_to(T, Intable)`, `... or ...`).
   Preserve its source text as the parser already does for `where` clauses
   elsewhere; a full expression AST is not required for the implication rule
   below.

2. **Register the new fields for the self-hosted path.** `StructDef` and
   `TraitDef` field tables live in `mojo/backend_gimple/module_gen.py`
   (`self.struct_field_types['StructDef']` and `['TraitDef']`, ~6322). A new
   `MojoList *` field must be added there (and to `_field_elem_types` only if
   it is homogeneous), or `make bootstrap` compiles the compiler with a field
   table that disagrees with `fire_compiler.py`. Also add the same fields to
   the dataclass constructors in `fire_compiler.py`; do not give them a
   `__init__` ABI-changing position.

3. **One shared declaration check.** Add
   `check_conformance_declarations(struct_defs, trait_defs)` to `elaborate.py`,
   next to `check_conformance`/`check_bounds`, and call it once per module from
   the `all_struct_defs` pre-pass in `mojo/backend_gimple/module_gen.py`
   (immediately before/after `_merge_struct_inheritance`, ~6647). That is the
   one place that sees every struct after class-body conditionals are
   flattened, in both inline and link mode.

   Build the trait ancestor graph from `TraitDef.bases`; treat a built-in or
   unknown trait as having no known ancestors. The implication test is
   deliberately conservative and syntactic:

   - a conjunction implies each of its conjuncts (and a constraint implies
     itself);
   - `conforms_to(T, A)` does not imply `conforms_to(T, B)` unless `B == A` or
     `A` reaches `B` through the known trait ancestor graph;
   - `or` implies a conjunct only when every disjunct does;
   - anything the checker cannot parse is ACCEPTED (no diagnostic). The
     modular tests are all decidable by these rules; do not invent a solver.

   Emit the exact messages from the modular file, at the struct's line:
   - diamond: `ancestor trait 'X' is reached via multiple inheritance paths
     with different constraints; it must be explicitly listed in the
     conformance list with the desired constraint`
   - implication: `constraint for 'Derived' does not imply constraint for
     ancestor trait 'Base'; strengthen the derived constraint by adding the
     ancestor's constraint with 'and'`
   - conditional `TrivialRegisterPassable`: `conditional conformance to
     'TrivialRegisterPassable' is not supported`

4. **Conditional-RP origin rule.** `bad_conditional_rp_origin` returns
   `ref[x]` where `x` is a conditionally-`RegisterPassable` argument. Hook the
   function-signature/return check that already knows the return annotation
   and the argument's declared type; reject only when the argument's type has
   a conditional `RegisterPassable` conformance that is not provably false
   (a `ref` argument is exempt, which is `ok_conditional_rp_ref_origin`).
   Message: `cannot return 'x's origin, because it might expand to a
   RegisterPassable type`.

## Acceptance check

Add `test_conditional_conformance_declaration_diagnostic.py` (next to the
other `test_*_diagnostic.py` files; do NOT register it in `tools/suite.py`).
Use `gimple_codegen.compile_to_gimple` on reduced, self-contained sources
(local traits/structs only, no stdlib import), one case per bullet:

- the five declaration cases above each raise `RuntimeError` containing the
  exact message;
- `bad_conditional_rp_origin` raises with the origin message;
- the three positive controls still compile (no exception).

Run only that file, under the memory wrapper:

    python3 tools/memslot.py --gb 8 --label trait-conformance-p1 -- \
        python3 test_conditional_conformance_declaration_diagnostic.py

## Not in this part

Parts 2/3 (method requirement evidence and overload candidate selection),
part 4 (copy/move synthesis), part 5 (comptime member types), part 6
(defaulted trait methods), part 7 (downcast witness tables).
