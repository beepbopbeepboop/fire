# COMPILE_FAIL: Tools/scripts/summarize_stats.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/scripts/summarize_stats.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-09, 3 of 4 original functions now fixed by intervening work; last one confirmed structural)

Re-ran against current master (`c4340d2`). Real progress since the
2026-08-06 status: the refusal now lists only **one** function, down
from four — `iter_optimization_tables`, `iter_parts`, and
`iter_specialization_tables` all compile cleanly now (fixed as a side
effect of other generator-codegen widening work landed elsewhere this
session, not anything done in this pass). Only `iter_pre_succ_pairs_
tables` remains refused:

```
Error building: cannot compile module: function(s)
iter_pre_succ_pairs_tables (generator function(s), contain a `yield`/
`yield from`) — this codegen compiles every function into a single
straight-line C function and has no suspend/resume state-machine
transform for generators, nor an event loop / suspend-resume codegen
for async functions, yet, so these cannot be represented as compiled C
without emitting silently wrong or broken code; falling back to
interpreting this module from source instead
```

`MOJO_DEBUG=1` pins the exact cause:

```
generator 'iter_pre_succ_pairs_tables' not eligible for C++ coroutine
path (pass 2), falling back: unsupported expression in generator body:
LambdaExpr
```

The real source (`Tools/scripts/summarize_stats.py`, inside
`pre_succ_pairs_section()`):

```python
yield Section(
    opcode,
    f"Successors and predecessors for {opcode}",
    [
        Table(
            ("Predecessors", "Count:", "Percentage:"),
            lambda *_: pred_rows,  # type: ignore
        ),
        Table(
            ("Successors", "Count:", "Percentage:"),
            lambda *_: succ_rows,  # type: ignore
        ),
    ],
)
```

Two `lambda *_: <captured list>` literals passed as plain call
arguments inside the generator body — the exact same, already-
diagnosed gap as `bugs/hard/CODEGEN_generator_lambda_expr_unsupported.
md`: `_cpp_expr` (the coroutine `.cpp` emission path) has no
`LambdaExpr` case at all, and that doc's own investigation already
established this needs a new "callable value" declared-type category
(not a narrow widening — see that doc's "Why this is feature-sized,
not narrow" section for the full reasoning, which applies unchanged
here). Genuinely structural; not attempted here. No code change made
for this bug — the remaining blocker is a duplicate of an
already-tracked, already-assessed gap, not a new root cause.

(An older status further down used to show a stale raw GCC warning dump from a much earlier, pre-refusal-gate run — removed as no longer reflecting current behavior; the module now fails cleanly at the up-front generator-refusal gate above, before any C/C++ is ever handed to GCC.)
