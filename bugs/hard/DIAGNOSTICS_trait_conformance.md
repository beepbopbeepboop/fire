# DIAGNOSTICS step 2: Trait conformance diagnostics

SPLIT: the three sub-steps (their docs were deleted with their fixes; see Status 2026-11-14 below — part 6 was already recorded as fixed here)

Part of the umbrella `bugs/hard/DIAGNOSTICS_missing_validation_modular.md`;
plan: `docs/diagnostics-missing-validation-plan.md` §2.

## Symptom
Conditional conformance, defaulted trait method signature mismatch, enum `_enum_is_exhaustive` type check, downcast witness tables, and MOCO-4400 must all report diagnostics instead of being accepted.

## Modular tests
struct_conditional_trait_conformance_errors.mojo, defaulted_trait_method_bad_conformance.mojo, enum_exhaustive_errors.mojo, invalid_downcast_error.mojo, moco_4400_no_crash_on_bind_parameter.mojo

## Files
mojo/backend_gimple/emit_resolve.py, mojo/middle/funcs_shared.py, the trait registry

## Test
Each modular test's `error:` line is reproduced and no crash occurs.

## Acceptance
One regression per sub-step.

## Status
- **Open.**

## Status 2026-11-14: the sub-steps are landed; two residuals are measured, not guessed

The SPLIT below still names part1/part4/part5, but **all three of those docs
are gone from the tree** (deleted with their fixes, as this repo's convention
requires), and their regression tests pass:

- `test_defaulted_trait_method_conformance_diagnostic.py` — PASS
- `test_downcast_witness_diagnostic.py` — PASS
- `test_invalid_downcast_build.py` — PASS

Measured against the canonical Modular sources:

- `decls/struct_conditional_trait_conformance_errors.mojo` — emits
  `error: ancestor trait 'DiamondBase' is reached via multiple inheritance
  paths with different constraints; it must be explicitly listed in the
  conformance list with the desired constraint`. It carries no `CHECK:` line;
  it runs under `%parse-mojo-isolated -verify-diagnostics`, which the umbrella
  doc already records as harness-UNSUPPORTED.
- `decls/defaulted_trait_method_bad_conformance.mojo` — the CHECK wants
  `error: 'Map[mapFn]' does not implement all requirements for 'Strategy'`;
  we emit the same sentence but with the TRAIT METHOD's parameter spelling:
  `'Map[mapper]'`. The struct declares the parameter as `mapFn`
  (`struct Map[Strat: Strategy, Dest: Copyable, //, mapFn: def (Strat.Value)
  thin -> Dest]`), the trait's default method as `mapper`
  (`def map[To: Copyable, //, mapper: def (Self.Value) thin -> To] ->
  Map[mapper]`). Modular prints the CONFORMING STRUCT's spelling
  (`structDecl.getTypeDeclSelf()`, `lib/MojoParser/Traits.cpp:458`, printed at
  `:542`). Ours prints the application text found in the method's own
  signature (`elaborate._validate_inherited_default` -> `_collect_type_apps_in_text`).
  **This is the one open item**: the reported application must be re-spelled
  with the struct's own bracket-parameter names, not the trait method's. The
  existing regression only pins the coincidental case where both spell the
  parameter `mapFn`, so it cannot catch this.
- `enum_exhaustive_errors.mojo` — **does not exist** in the Modular tree
  (the "Modular tests" list above is stale on this entry).
- `mojo-integration/invalid_downcast_error.mojo` and
  `mojo-integration/moco_4400_no_crash_on_bind_parameter.mojo` — the two CHECK
  lines (`function instantiation failed` + the witness-table note; `'S[T]' does
  not implement all requirements for 'Iterable'`) are covered by the passing
  tests above.
