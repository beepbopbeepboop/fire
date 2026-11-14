# CODEGEN_stdlib_run_prints_elaboration_refusals: a clean-looking stdlib run prints refusal diagnostics to the console

**Class:** easy
**Found:** 2026-11-13. Reproduced on master `1889a7f69` by `compile_stdlib.py` from two checkouts (`mojo-reference` and `mojo-reference2`).

## Symptom

A `compile_stdlib.py` run that ends `610 passed, 0 failed` still prints, interleaved with the progress line:

    CAUGHT_IN_MAIN_LOOP: cannot materialize instantiation of generic 'StaticTuple': its bracket arguments
    [compile_module_to_c_cached] .../std/simd.mojo: 2 generic struct elaboration(s) failed,
      so this module's C is NOT the program its source describes and it is NOT being cached:
        SIMD[exp.dtype, self.length] from .../std/simd.mojo: RuntimeError: cannot materialize
        instantiation of generic 'StaticTuple': its bracket arguments advance without converging,
        which would cause infinite recursion

The two lines are emitted from two places:

- `mojo/backend_gimple/module_gen.py:16496` prints `CAUGHT_IN_MAIN_LOOP:` to stderr, unconditionally,
  for every caught refusal in the main loop.
- `build_stdlib_dylib.py:612` prints the "NOT the program its source describes" block.

## Why it is a bug

The console is the first thing a reader of the stdlib run looks at. Refusal text printed next to
a `passed` line reads as a failure, or as noise nobody can act on. Either way the reader cannot
tell which lines matter. This is the output-side symptom of two underlying problems:

- The refusal itself is a false positive: `bugs/CODEGEN_simd_exp_staticTuple_refusal.md`.
- The run counts the module as PASSED despite the message: `bugs/CODEGEN_stdlib_failed_elaboration_counted_as_pass.md`.

Fixing the verdict alone (the second doc) would make the module FAILED and the output honest, but
the `CAUGHT_IN_MAIN_LOOP` line would still print on every run for a refusal that is a bug. The
output should carry only what the reader must act on.

## Fix direction

1. Route `CAUGHT_IN_MAIN_LOOP` (and the per-module elaboration block) to the run's log file, not
   the console, unless the run is verbose. Keep a one-line count on the console instead.
2. Once the refusal is fixed (first doc), the simd lines stop appearing by themselves. Do not
   silence them before then; the count line keeps the signal visible.
3. Confirm the module-level verdict change from the second doc is in the same change, so a silent
   console cannot hide a FAILED module.

## Acceptance

- A stdlib run that has no real failures prints no `CAUGHT_IN_MAIN_LOOP` or "NOT being cached" text
  on the console.
- Refusals are still written to the log, with module name and reason.
- The console shows a count of caught refusals, so the signal is not lost.
