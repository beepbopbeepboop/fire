# CODEGEN_stdlib_failed_elaboration_counted_as_pass: a module that fails elaboration is reported as PASSED

**Class:** easy
**Found:** 2026-11-13 on master `4c746595b`.

## Symptom

`compile_stdlib.py` reports `610 passed, 0 failed, 0 unexpected` while the same run prints:

    [compile_module_to_c_cached] .../std/simd.mojo: 2 generic struct elaboration(s) failed,
      so this module's C is NOT the program its source describes and it is NOT being cached

The module's own diagnostic says its C is wrong and was not cached, yet the harness counts it as a pass.

## Where

- `build_stdlib_dylib.py:611-612` prints the "NOT the program its source describes" message.
- The verdict in `compile_stdlib.py` (the `PASSED` / `FAILED` tally) does not read that
  condition, so a module that printed it still counts as passed.

Introduced by `5dfa758f6` (2026-10-02, "codegen: a module built through a failed elaboration
is not cached"), which added the message and the no-cache behaviour but not a failing verdict.

## Why it matters

The stdlib gate's green count is the signal the verification policy relies on. A module that
the compiler itself says is not correct, and that is not cached, must not count as a pass. Right
now the stdlib run can be green while the compiled path is wrong for a file.

## Fix direction

Make the per-module result carry the elaboration-failure condition, and count such a module as
FAILED (unexpected unless it is listed in `EXPECTED_FAILURES` with a reason). Then the
`CODEGEN_simd_exp_staticTuple_refusal.md` case shows as FAILED until that bug is fixed.

## Acceptance

- A module with a failed elaboration is counted in `FAILED`, not `PASSED`.
- Today's `std/simd.mojo` case appears as a FAILED line with its reason.
- No change in the count of modules that genuinely compile.
