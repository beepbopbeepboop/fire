SPLIT: DIAGNOSTICS_binding_deferrals-part2
# DIAGNOSTICS step 4: Binding deferral reporting

Part of the umbrella `bugs/hard/DIAGNOSTICS_missing_validation_modular.md`;
plan: `docs/diagnostics-missing-validation-plan.md` §4.

## Symptom
A failed struct binding must report only the error that failed it, not the constraints it deferred before failing.

## Modular tests
failed_binding_deferrals.mojo

## Files
The signature/declaration binding path: `mojo/backend_gimple/emit_funcs.py`
(signature lowering) and `mojo/backend_gimple/module_gen.py` (declaration
pre-pass), reusing `elaborate.py`'s `bind_type_args` / `check_where_clauses`.
The body-instantiation path (`mojo/backend_gimple/emit_resolve.py`,
`mojo/backend_gimple/elab_intu.py`) is already checked and tested.

## Test
Modular's two signature `CHECK` lines, in
`mojo/test/mojo-parser/failed_binding_deferrals.mojo`:

- `NeedsCopyablePos[CondCopyable[U], 0]` fails with
  `error: violated constraint`, and reports no second error;
- `NeedsCopyablePos[CondCopyable[U], 1]` fails with
  `error: invalid bindings in signature: lacking evidence`, and reports no
  second error (the conditional `Copyable` conformance is unproven for a
  generic `U`, so this binding is not satisfied either).

A provable binding of the same struct (`NeedsCopyablePos[Int, 1]`) compiles.

## Acceptance
`test_binding_deferral_diagnostic.py` covers both signature shapes
(`test_signature_failed_binding_reports_violated_constraint` for part 1,
`test_signature_unproven_binding_reports_lacking_evidence` for part 2), and the
existing body-instantiation regressions in that file stay green.

## Status
- **Replanned (2026-11-12) — the modular file still compiles silently.**
  The earlier body-path fixes landed (`22dfa22c4`: the struct's own `where`
  text is read from the declaration header and the `violated constraint`
  wording is shared; `a5daccf4e`: a body instantiation reports one error, no
  deferred noise) and `python3 test_binding_deferral_diagnostic.py` passes.
  But modular's file is a PARSER test whose bindings are parameter types in
  function signatures. Measured 2026-11-12: compiling the exact modular file
  through `driver.compile_program` succeeds (`COMPILED OK`, 0.4 GB peak),
  because a declaration's parameter annotations are resolved to C types and
  never turned into generic instantiations, so the landed check never runs.
  Part 1 (provably-false signature binding → `error: violated constraint`)
  is fixed: declaration-time checking rejects a signature parameter whose
  generic struct instantiation has a provably-false `where` clause.
  Remaining work is `bugs/mid/DIAGNOSTICS_binding_deferrals-part2.md`
  (unproven requirement → `error: invalid bindings in signature: lacking evidence`).
- **Note on the earlier part-2 interpretation.** The 2026-11-12 body fix read
  "only the error that failed it, not the constraints it deferred" as "this
  binding must not report `lacking evidence` anywhere". Modular's second
  `CHECK` line IS a `lacking evidence` error, for the `n == 1` binding, with
  `CHECK-NOT: error:` applying only to that binding. The signature half is
  re-opened as part 2. Body instantiations keep their current behaviour (the
  existing test pins `[..., 1]` as compiling); whether the same evidence rule
  should reach them is recorded as a follow-up decision in part 2, not
  silently settled here.
