SPLIT: DIAGNOSTICS_binding_deferrals-part2-part1, DIAGNOSTICS_binding_deferrals-part2-part2

# DIAGNOSTICS_binding_deferrals part 2: an unprovable signature binding reports `invalid bindings in signature: lacking evidence`

Parent: `bugs/hard/DIAGNOSTICS_binding_deferrals.md` (SPLIT). This part does
NOT fix the bug end-to-end.

Class: **mid** (this doc lives in `bugs/mid/`). Besides the declaration-time
hook that part 1 adds, this part needs a conservative evidence/implication
decision for a conditional conformance: `CondCopyable[U]` conforms to
`Copyable` only where `conforms_to(U, Copyable)`, and the enclosing signature
knows only `U: Movable & Deinitable`. Nothing in `elaborate.py` currently
distinguishes "unknown conformance, accept" from "unproven for this binding,
reject" — `check_conformance` returns `(True, [])` for any type name it cannot
find a struct for.

## Goal

A function DECLARATION whose parameter type is a generic struct instantiation
whose requirement is NEITHER provable NOR provably false fails to compile with
modular's wording,
`error: invalid bindings in signature: lacking evidence`, exactly once.

Modular source (`mojo/test/mojo-parser/failed_binding_deferrals.mojo`, lines
38-43):

```mojo
# CHECK: [[@LINE+3]]:{{[0-9]+}}: error: invalid bindings in signature: lacking evidence
# CHECK-NOT: error:
def successful_binding[U: Movable & Deinitable](
    x: NeedsCopyablePos[CondCopyable[U], 1]
):
    pass
```

`NeedsCopyablePos[T: Copyable, n: Int]` requires `CondCopyable[U]: Copyable`.
`CondCopyable` is declared as
`struct CondCopyable[T: Movable & Deinitable](Copyable where conforms_to(T, Copyable), Movable)`,
so the requirement holds only under `U: Copyable`, which this signature does
not have. `n == 1` satisfies `where n > 0`, so the binding fails on the
unproven `T: Copyable` requirement and nothing else.

**Measured 2026-11-12 on this tree:** the modular file compiles silently
through `driver.compile_program`. The existing
`test_satisfied_generic_binding_compiles` pins the BODY case
(`var a = NeedsCopyablePos[CondCopyable[U], 1]()`) as compiling; the earlier
2026-11-12 part-2 fix read "no deferred-constraint noise" as "this binding must
not report `lacking evidence` anywhere", but modular's second CHECK line is
itself a `lacking evidence` error for this binding. That half is re-opened
here for the signature shape the modular test actually uses.

## Scope

1. Build on part 1's declaration-time hook. Part 1 reports the provably false
   `where` clause; this part runs only when no clause was provably false and
   the binding has an unproven struct type-parameter requirement.
2. Decide the requirement conservatively from the struct template's parameter
   bounds (`parse_bounds`/`bind_type_args` in `elaborate.py`) and the argument
   type's own base list. A conditional conformance
   (`Copyable where conforms_to(T, Copyable)`) is provable only when the
   assumption is implied by the enclosing function's bounds; unprovable
   assumptions are what this part reports. A type the checker cannot inspect
   at all keeps the current accept behaviour (do not start rejecting imported
   or stdlib types on absence of evidence).
3. Report `error: invalid bindings in signature: lacking evidence` (optionally
   a note naming the requirement/type argument), exactly once per declaration.
   Do not also report a `where`-clause error for the same binding.
4. A provably false clause still reports only part 1's
   `error: violated constraint` (no `lacking evidence` noise on the `n == 0`
   binding).
5. Out of scope: body instantiations. `test_satisfied_generic_binding_compiles`
   stays as it is in this part; the body/signature difference is recorded in
   the parent doc's Status so it is a decision, not an accident.

The evidence/implication primitive is the one
trait-requirement conformance evidence (the former part 2 plan) covers
evidence at use sites. If that part lands first, reuse it; do not add a second
evidence evaluator.

## Acceptance

- `def successful_binding[U: Movable & Deinitable](x: NeedsCopyablePos[CondCopyable[U], 1])`
  fails to compile with `error: invalid bindings in signature: lacking evidence`,
  exactly one `error:` line, and no `violated constraint` text.
- Positive controls compile: `x: NeedsCopyablePos[Int, 1]` (provable
  `Copyable`, satisfied clause) and
  `def g[U: Movable & Deinitable & Copyable](x: NeedsCopyablePos[CondCopyable[U], 1])`
  (the conditional conformance's assumption is in the bound set).
- The part-1 test still passes unchanged, and so do the existing
  body-instantiation regressions.

## Done when

`test_binding_deferral_diagnostic.py::test_signature_unproven_binding_reports_lacking_evidence`
(added by the 2026-11-12 replan; it currently fails with
`an unproven binding in a signature compiled`; it also carries the
`NeedsCopyablePos[Int, 1]` positive control) passes:

```
python3 tools/memslot.py --gb 8 --label binding-deferral-p2 -- python3 -c "import test_binding_deferral_diagnostic as t; t.test_signature_unproven_binding_reports_lacking_evidence()"
```

then add the new function to the file's `__main__` list so
`python3 test_binding_deferral_diagnostic.py` covers it too.

## Not in this part

- `n == 0` / provably false clause (part 1).
- Body instantiations, and whether the same evidence rule should reach them
  (recorded in the parent's Status as a follow-up decision).
- Imported/precompiled structs whose base list is unavailable.
