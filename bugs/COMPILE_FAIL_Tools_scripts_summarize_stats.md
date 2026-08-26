# COMPILE_FAIL: Tools/scripts/summarize_stats.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/scripts/summarize_stats.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (re-verified 2026-08-26, wtRest19b): byte-identical, unchanged

Fresh repro against current tree: identical refusal, byte-for-byte the
same as 2026-08-25 — `iter_optimization_tables`/`iter_specialization_
tables` refused on unresolved callees `calc_histogram_table(...)`/
`calc_specialization_table(...)`, both nested `def`s local to the
enclosing `pre_succ_pairs_section()` capturing enclosing-scope locals.
Root cause and required fix (real closure compilation for nested
functions referenced as callees inside coroutine bodies) unchanged
from the prior analysis — genuinely feature-sized, shared scope with
this project's documented closure-machinery regression history. Not
attempted; no code change.

## Status (re-verified 2026-08-25 pm, branch fix/opencode-group1 — blocker SHIFTED again: the refusal set narrowed to the two nested-function-callee generators)

Fresh repro: the module now refuses at the eligibility gate on only
TWO functions, both on unresolved NESTED-function callees:

```
iter_optimization_tables: a call to unresolved callee
  'calc_histogram_table(...)' is not supported in a compiled
  generator/coroutine body ...
iter_specialization_tables: a call to unresolved callee
  'calc_specialization_table(...)' is not supported ...
```

Both `calc_*` helpers are sibling `def`s NESTED inside the same
enclosing function (`pre_succ_pairs_section()`) as the generators that
call them — so this is now precisely the "nested `def` local to the
generator body" closure-compilation family `_cpp_expr`'s own refusal
comment already names (importlib/metadata's identical shape), NOT any
of the previously-documented shapes: the LambdaExpr refusal (2026-08-09),
the Section___init__ extern-typing / bare-continue /
declaration-ordering C++ error set (2026-08-23) are all no longer
reached. Supporting it needs real closure compilation for nested
functions referenced as callees inside coroutine bodies (they capture
enclosing-scope locals: `pred_rows`/`succ_rows`/`part_iter`) — feature-
sized work on shared machinery with this project's documented
regression history. No code change; doc re-verified with the shifted
blocker precisely identified. Still open.

## Status (2026-08-23): error set SHIFTED twice over; old blockers all gone, new
## blocker is a fresh frontier of .cpp coroutine-stage mislowering. Still open.

Re-ran against current code (branch `fix/tools-misc` @ `c16c05c`, which includes
master's absorbed generator work plus this branch's tuple-target/_cname/Counter/
boxed-cast/AugAssign-dispatch fixes). Two distinct layers of progress since the
2026-08-09 note, verified by a pristine-HEAD side-by-side (`git archive HEAD`
build in a scratch dir):

1. **The `iter_pre_succ_pairs_tables` LambdaExpr refusal is GONE.** Master
   absorbed lambda-in-generator-body support (the emitted `.cpp` now contains
   IIFE lambdas inside `co_yield`, e.g.
   `co_yield [&]() -> Table * { ... }()`), so the module no longer fails at the
   up-front eligibility gate at all.
2. **All 13 client-`.c` errors that pristine HEAD still produces are gone.**
   Pristine HEAD (`736b349`'s parent content, same dylib) fails in
   `load_raw_data_0c85c9` / `OpcodeStats_get_specialization_failure_kinds` /
   `object_stats_section_calc_object_stats_table` /
   `optimization_section_calc_optimization_table` with exactly the four shapes
   fixed by this branch's commit `c16c05c`: `stats[key.strip()] += int(value)`
   stored through `mojo_list_set_int` with a `char *` value (4×),
   `lvalue required as left operand of assignment` on the enumerate-comprehension
   `index` target, and paren-fragment C syntax errors from naive nested-tuple
   target splitting (2 fns). With `c16c05c` the whole client `.c` compiles clean
   and the build advances to the LATER `.cpp` coroutine-companion stage.

**New blocker (52 hard C++ errors, all first reached today).** The generator
bodies for `iter_optimization_tables`/`iter_specialization_tables`/
`iter_pre_succ_pairs_tables` lower to broken C++:

- unresolved callees lowered as literal `0` and their results assigned to
  plain `int64_t`s (`opcode_stats = Stats_get_opcode_stats(base_stats,
  "opcode");` declared `int64_t`; `names = names &= 0;`);
- `Section___init__`'s extern signature types its list parameter `int64_t`,
  while call sites pass brace-init lists of `Table *` (the cpp-path sibling of
  `bugs/hard/CODEGEN_unannotated_init_param_field_type_defaults_int64.md`);
- a bare `continue;` emitted outside any loop (`iter_specialization_tables`),
  `yield_value(int64_t)` receiving `Section *`, `'OpcodeStats' does not name a
  type` (declaration ordering), and `_mojogen_iter_parts_impl` reading closure
  variable `part_iter` (captured from the enclosing `pre_succ_pairs_section()`)
  without it ever being threaded into the standalone impl function.

These are instances of the compiled-generator/async-codegen project scope
(unresolved-callee policy in coroutine bodies, cross-function closure capture,
cpp-side struct field typing) — not narrow fixes; not attempted here. The file
still does not compile; every previously documented blocker is nonetheless
verified fixed.

## Status (updated 2026-08-09, historical — superseded by 2026-08-23 above)

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
