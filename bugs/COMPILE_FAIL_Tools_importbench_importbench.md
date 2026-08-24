# COMPILE_FAIL: Tools/importbench/importbench.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/importbench/importbench.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (2026-08-23): refusal list shrank 6 → 1; the one survivor is the
## already-documented non-plain-assignment-target gap. Still open.

Re-ran against current code (branch `fix/tools-misc` @ `c16c05c`). The up-front
refusal now names ONLY `from_cache`:

```
Error building: cannot compile module: function(s) from_cache (generator
function(s), contain a `yield`/`yield from`) — ...
```

The LambdaExpr gap (2026-08-09's blocker for 5 of the 6 functions) is FIXED by
master's absorbed lambda-in-generator-body support — `benchmark_wo_bytecode`,
`builtin_mod`, `source_using_bytecode`, `source_wo_bytecode`, and
`using_bytecode_benchmark` all now pass the eligibility gate, which also makes
the note's gap-3 (`sys.dont_write_bytecode` elision widening) moot for this
file's outcome, exactly as that note predicted. `from_cache` remains refused
for the documented reason only: `module.__file__ = '<test>'` /
`module.__package__ = ''` on a real, later-read `types.ModuleType` instance —
`bugs/hard/CODEGEN_generator_non_plain_assignment_target_refused.md`'s
unfixed case, correctly still refused rather than silently elided. No new root
cause; no code change made.

## Status (updated 2026-08-09, historical — superseded by 2026-08-23 above)

Re-ran against current master (`c4340d2`); still an honest up-front
refusal, not a GCC error:

```
Error building: cannot compile module: function(s) benchmark_wo_bytecode,
builtin_mod, from_cache, source_using_bytecode, source_wo_bytecode,
using_bytecode_benchmark (generator function(s), contain a `yield`/
`yield from`) — this codegen compiles every function into a single
straight-line C function and has no suspend/resume state-machine
transform for generators, nor an event loop / suspend-resume codegen
for async functions, yet, so these cannot be represented as compiled C
without emitting silently wrong or broken code; falling back to
interpreting this module from source instead
```

`MOJO_DEBUG=1 python3 mojo.py build importbench.py` pins down each of
the 6 refused functions to one of two ALREADY-TRACKED, deliberately-
deferred structural gaps in the coroutine (`.cpp`) generator-body
codegen — no new root cause found, and this file doesn't reveal any
narrow, safe-to-land fix (see below):

1. **`unsupported expression in generator body: LambdaExpr`** —
   `builtin_mod`, `source_using_bytecode`, and the closure-nested
   `using_bytecode_benchmark` (defined inside `_using_bytecode`) all do
   `yield from bench(name, lambda: sys.modules.pop(name), repeat=...,
   seconds=...)` — a `lambda` literal passed as a plain call argument.
   This is exactly `bugs/hard/CODEGEN_generator_lambda_expr_unsupported.
   md`'s tracked gap (`_cpp_expr` has no `LambdaExpr` case at all);
   that doc already investigated and confirmed this is feature-sized
   (needs a new "callable value" declared-type category), not a narrow
   fix — nothing new to add here.
2. **`only a plain identifier assignment target is supported`** —
   `from_cache` does `module.__file__ = '<test>'` /
   `module.__package__ = ''` where `module` is a real
   `types.ModuleType(name)` local (later read via `sys.modules[name] =
   module`) — a non-`self`, non-`sys.{stderr,stdout,stdin}` `MemberExpr`
   assignment target. This is `bugs/hard/CODEGEN_generator_non_plain_
   assignment_target_refused.md`'s remaining unfixed case: writing into
   a REAL object's attribute has no representation in this model, and
   silently eliding it (the way `sys.stderr = val` is elided) would be
   actually wrong here since `module` is a real, later-read object —
   correctly still refused.
3. **New narrow sub-detail found in this pass**: `source_wo_bytecode`
   and the closure-nested `benchmark_wo_bytecode` (defined inside
   `_wo_bytecode`) both do `sys.dont_write_bytecode = True` /
   `= False` — a `sys.<member>` target, but `dont_write_bytecode` isn't
   in the `('stderr', 'stdout', 'stdin')` tuple the existing elision
   fix (`gimple_codegen.py` ~line 24284) checks. Confirmed via `grep`
   that `dont_write_bytecode` has NO backing value anywhere else in
   `gimple_codegen.py` either (same "sys has no real backing value
   ANYWHERE in this model" rationale the stderr/stdout/stdin fix relies
   on) — widening that tuple to include it would be safe by the exact
   same reasoning already established and gated. **Not applied**,
   because it wouldn't change this file's outcome either way: both
   `source_wo_bytecode` and `benchmark_wo_bytecode` ALSO independently
   contain the SAME `yield from bench(name, lambda: ..., ...)` shape as
   gap 1 above, so they'd remain refused on the LambdaExpr gap even
   with the assignment-target check widened. Noted here for whoever
   next touches the `sys.stderr` elision list, not implemented.

**Net: all 6 refused functions are blocked by one of the two
already-documented structural/feature-sized gaps (3 by gap 1, 1 by gap
2, 2 by BOTH gap 1 and the new gap-3 sub-detail which doesn't matter on
its own).** No combination of narrow fixes gets this file compiling —
it needs real progress on the feature-sized LambdaExpr-in-generator-body
work first. Part of the separate, already-tracked compiled-generator/
async-codegen project scope; not attempted here. No code change made
for this bug.

(An older status further down used to show a large raw GCC warning
dump from a stale, pre-refusal-gate run — removed as no longer
reflecting current behavior; the module now fails at the up-front
Python-level refusal above, before any C/C++ is ever handed to GCC.)
