# DIAGNOSTICS step 2: Trait conformance diagnostics

SPLIT: DIAGNOSTICS_trait_conformance-part1, DIAGNOSTICS_trait_conformance-part2, DIAGNOSTICS_trait_conformance-part3, DIAGNOSTICS_trait_conformance-part4, DIAGNOSTICS_trait_conformance-part5, DIAGNOSTICS_trait_conformance-part6, DIAGNOSTICS_trait_conformance-part7

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
