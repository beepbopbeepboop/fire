# GPU offload validation modular - part 2: compile_offload diagnostics

Parent: `bugs/hard/GPU_offload_validation_modular.md` (SPLIT). Depends on triage in `bugs/mid/GPU_offload_validation_modular-part1.md`.

## Scope

Cover the compile-time offload diagnostic cases that may be expressible without a full GPU backend:

- `compile_offload_unbound_param_error.mojo`
- `compile_offload_missing_symbol_error.mojo`
- `compile_offload_bundle_order.mojo`

## Work

1. Obtain or reference the canonical intent of each test (expected diagnostic/error condition) from Modular sources or part 1 triage notes.
2. Identify the compiler phase that should own each check (parsing, elaboration, semantic validation, or offload compilation pipeline stub) in this codebase.
3. Implement or wire up the minimal validation needed so each case fails for the right reason (not a crash, not a silent miscompile), or document precisely why it is blocked by missing GPU/offload infrastructure.
4. Add/update focused tests in the appropriate existing test area covering the diagnostic/validation behavior for these cases.

## Acceptance check

- For each of the 3 files, there is either: (a) a passing focused test demonstrating the expected error/diagnostic behavior in this compiler, or (b) a documented, concrete blocker in this doc referencing the missing infrastructure and the exact next code change required.
- No regressions to existing non-GPU compile/test paths introduced by the change.
- Behavior is validated with the narrowest relevant test command(s), recorded in the commit/report.

## Status

Open.
