# CODEGEN_stdlib_run_prints_elaboration_refusals: a clean-looking stdlib run prints refusal diagnostics to the console

**Class:** easy
**Found:** 2026-11-13. Reproduced on master `1889a7f69` by `compile_stdlib.py` from two checkouts (`mojo-reference` and `mojo-reference2`).

## Symptom

A `compile_stdlib.py` run that ends `610 passed, 0 failed` used to print, interleaved with the progress line:

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
tell which lines matter. This is the output-side symptom of two underlying problems, both now
fixed:

- The refusal itself was a false positive in `std/simd.mojo` (the SIMD exp StaticTuple `advance
  without converging` refusal), fixed 2026-11-14: only simple stepping operands (`i + 1` over
  names/literals) count as a progressing bracket argument, so a fixed comptime computation like
  `2 * Int(Self.length)` is no longer refused.
- The run used to count the module as PASSED despite the message; that verdict bug is fixed
  (2026-11-14) too, so a module built through a failed elaboration is a FAILED entry with its
  reason instead of a silent pass.

With both fixed, `std/simd.mojo` compiles cleanly and the two lines above no longer appear for it.
What remains is the output-side problem itself: `CAUGHT_IN_MAIN_LOOP:` and the per-module "NOT
being cached" block print unconditionally for ANY caught refusal, so the next one again lands in
the middle of a green run. The output should carry only what the reader must act on.

## Fix direction

1. Route `CAUGHT_IN_MAIN_LOOP` (and the per-module elaboration block) to the run's log file, not
   the console, unless the run is verbose. Keep a one-line count on the console instead.
2. The `std/simd.mojo` lines have already stopped on their own, so verify the routing against a
   refusal that still occurs rather than by waiting for this one to disappear. Do not silence
   refusals themselves; the count line keeps the signal visible.
3. The module-level verdict (a module built through a failed elaboration is FAILED) is already in;
   keep it in the same change so a silent console cannot hide a FAILED module.

## Acceptance

- A stdlib run that has no real failures prints no `CAUGHT_IN_MAIN_LOOP` or "NOT being cached" text
  on the console.
- Refusals are still written to the log, with module name and reason.
- The console shows a count of caught refusals, so the signal is not lost.
