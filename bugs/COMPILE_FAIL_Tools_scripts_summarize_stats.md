# COMPILE_FAIL: Tools/scripts/summarize_stats.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/scripts/summarize_stats.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (2026-10-29 — PARTIAL: closure factories now compile; the real file still refuses)

LANDED (`mojo/backend_gimple/cpp_async.py`, `cpp_core.py`):

- A closure FACTORY (`def F(...)` whose body is some statements then `return C`,
  where `C` is the one nested `def`) called from a compiled generator now
  compiles to a `static int64_t F(...)` helper. It returns the closure as an int64
  `MojoBoundMethod` (fn = a per-factory trampoline, self = the heap-held `[=]`
  lambda), the same box a plain function value already is, so it is passed to an
  `int64_t` slot and called through `mojo_fnptr_call_N`. See
  `_closure_factory_parts` and `_try_compile_closure_factory`.
- `make(k)(x)` (a call through a factory's result) lowers to
  `mojo_fnptr_call_N((void *)(make(k)), x)`, restricted to factories.
- Fixed a dead check: `_walk_own_body` never yields a FunctionDef, so the
  "no further nested def" rule in `_try_compile` never fired. It now scans
  `_walk_ast`.
- Still refused: a closure that assigns through `nonlocal` (it needs a shared
  cell, not a by-value copy).
- Tests: `test_regress_codegen_generator_closure_factory.py`. Four positive tests
  fail on HEAD and pass now. The `nonlocal` negative refuses before and after.
  The value is checked by compiling and running the generated C++ against the
  runtime: `calc_hist(5,2)(10)` = 52 and `calc_hist(3,4)(10)` = 34, matching CPython.

DEVIATION from the plan below: no `F__env` struct and no `F__C` static function.
Plain C++ `[=]` capture copies each factory local at the `return`, which is exact
because `return C` is the last statement. So the "reassigned captured parameter"
refusal in the plan is unnecessary. The env is heap-allocated and never freed, the
accepted gap in `bugs/CODEGEN_closure_env_and_boxed_local_never_freed.md`.

NOT DONE: the real `Tools/scripts/summarize_stats.py` still refuses. A reproducer
(`iter_tables` calling `calc_hist(i + base, 2)`) hits two shapes outside this
change first. Both are pre-existing and neither is fixed here:

1. A tuple target in a generator's for loop, `for name, den in [(1, 2), (3, 4)]`,
   emits `for (auto name, den : ...)`, which is invalid C++.
2. A list literal as a constructor argument, `Section("sec", [Table(...)])`, emits
   a brace list where the extern signature wants `MojoList *`.

Next step: fix those two in the generator emitter, then re-run the real file with
`MOJO_DEBUG=1 python3 fire.py build <file>` (a stdlib-sized run, for the integrator)
and triage what remains. `calc_histogram_table`'s body (a `for`, a `while`,
`f"<= {k:,d}"`, a slice return) is unverified through this emitter.

## Status (2026-10-29 — planning round: the remaining blocker is a closure VALUE returned by a nested factory; implementation guide below, nothing landed for this file)

### Measurement (this round)

- **Minimal reproducer reproduces the exact refusal.** Saved as
  `.tmp/repro/factory_ctor.py` in the worktree (not committed); reproduced
  inline here:

  ```python
  class Table:
      def __init__(self, title: str, calc, mode: int):
          self.title = title; self.calc = calc; self.mode = mode

  class Section:
      def __init__(self, name: str, tables: list):
          self.name = name; self.tables = tables

  def outer():
      def calc_hist(key: int, den: int):
          def calc(stats: int) -> int:
              return stats * key + den
          return calc

      def iter_tables(base: int):
          for name, den in [(1, 2), (3, 4)]:
              yield Section("sec", [Table("t", calc_hist(name, den), 0)])

      for s in iter_tables(5):
          print(s.name, s.tables[0].title)

  outer()
  ```

  `MOJO_DEBUG=1 python3 fire.py build <file>` →
  `generator 'iter_tables' not eligible for C++ coroutine path ...: a call to
  unresolved callee 'calc_hist(...)' is not supported in a compiled
  generator/coroutine body`. Falls back to source.
- **The same generator with a plain module-level callee passes** (`Table("t",
  calc_plain, 0)` as the ctor argument): builds and prints `a t` / `b t`. So a
  callable as a ctor argument is NOT the blocker; the blocker is specifically
  the factory call (`calc_hist(...)`), whose result is a closure that captures
  the factory's parameters.
- **A factory call used as a plain local also works** (`f = pick(3); yield
  f(n)` with `pick` a top-level factory): builds, prints `12`. So the
  blocker is the sibling-nested factory shape used as a call argument inside
  the generator, not every closure factory.
- Real file, from the source (`Tools/scripts/summarize_stats.py`): the two
  refused callees are `calc_histogram_table(key, den=None)` (line 1224) and
  `calc_specialization_table(opcode)` (line 882). Both are sibling-nested in
  the enclosing `pre_succ_pairs_section()` / `iter_*` scope, both are factories
  whose body is `def calc(stats): ...; return calc`, and their results are
  passed as the `calc` argument of `Table(...)` inside generator bodies
  (`iter_optimization_tables` line 1282, `iter_specialization_tables` line 940).
  Caveat: a full `fire.py build` of the real file was started and stopped
  (the stdlib sweep is far too heavy for a light worker); the refusal chain is
  established by the reproducer and by reading the code, not by a completed
  build of the real file this round.

### Why the refusal happens (code path)

- `gimple_exprtypes`/`cpp_async.py:_cpp_compile_nested_sync_helpers` (line 1255)
  compiles a nested sync helper to a `static` C++ function only when it has
  no further nested `def` (`_try_compile`, line ~1378). A factory has one, so
  it is skipped and `calc_hist` is never registered in
  `gen._cpp_nested_helper_syms`.
- `cpp_core.py:_cpp_expr` CallExpr (line ~4271) then falls through to the
  honest unresolved-callee refusal.

### The value representation problem

- A callable VALUE in the coroutine path is `_CPP_CALLABLE_CTYPE`
  (`mojo/middle/types.py:2445`, `std::function<int64_t()>`), and a module
  function as a value is a bare function pointer (`mojo_fnptr_call_N`,
  `runtime/fire_runtime.h:232`). A bare function pointer has nowhere to keep
  captured values, which is the gap.
- The runtime already has the shape needed. `MojoBoundMethod { void *fn;
  void *self; }` (`runtime/fire_runtime.h`, ~line 90) carries a callee plus one
  opaque pointer, and `mojo_fnptr_call_N` already dispatches on
  `mojo_is_bound_method` (see `fire_runtime.c`'s registry). A closure is the
  same thing with `self` = its captured environment.

### Decision (taken here, not asked)

Represent a returned closure as a `MojoBoundMethod*` whose `fn` is the lifted
closure body and whose `self` is a heap env holding the captured values by
value. Reuse the existing bound-method call path; add no new runtime type. Two
consequences, both accepted:

1. **By-value capture is correct only when the factory never reassigns a
   captured parameter after the nested `def`.** The factory must REFUSE (keep
   the honest refusal) when a captured name is assigned in the factory body.
   This is a checkable condition on the factory's own body.
2. **The env is never freed.** This is the same accepted leak as
   `bugs/CODEGEN_closure_env_and_boxed_local_never_freed.md`; do not invent a
   free path in this round.

### Implementation plan (exact files and functions)

1. `mojo/backend_gimple/cpp_async.py` — `_cpp_compile_nested_sync_helpers`:
   add a second helper class, a **closure factory**: a nested sync `def F(...)`
   whose own body contains exactly one nested `def C` and a final
   `return C`, and whose only other nested defs are none. Keep the existing
   no-nested-def rule for ordinary helpers. Compile `C` as a standalone
   `static` function `F__C(void *env, <C params>)` whose body is the ordinary
   coroutine-body lowering of `C`, with every captured free name of `C` (a
   name that is a parameter of `F`) rewritten to a read of
   `((F__env *)env)->name`. Emit a `struct F__env { <captured ctype> name; ... }`
   per factory. Apply the reassignment refusal from Decision 1 here.
2. `mojo/backend_gimple/cpp_core.py` — `_cpp_expr` CallExpr branch (near
   line 4184, the `_cpp_nested_helper_syms` lookup): when the callee names a
   closure factory, lower the call to
   `mojo_bound_method_new((void *)F__C, F__make_env(args...))`, where
   `F__make_env` is a `static` function that heap-allocates `F__env` and
   stores the factory's arguments, so the factory's by-value parameters are
   captured. Return type of the call is `MojoBoundMethod *`, declared in the
   coroutine body as `void *` to match the existing callable-slot convention.
3. Verify the stored value is accepted by a `Table` ctor field and by
   `mojo_fnptr_call_N`: it must be the same slot type a bare function pointer
   uses (the `calc_plain` case above already passes, so the bare-pointer slot
   convention is the one to match).
4. No change to `runtime/fire_runtime.h`, `fire_runtime.c`, or
   `gimple_codegen.py` should be needed; if one is, record why before making it.

### Tests that prove it

- **Failing first (write before the fix):** in `test_gimple.py` (or
  `test_regress_codegen_generator_frame.py`, which already pins a similar
  refusal at line 62), a `generator_closure_factory_as_ctor_arg_compiles`
  case: the reproducer above, compiled and run, expected output `a sec`-style
  lines matching CPython. It FAILS today with the refusal text. Run it with
  `python3 tools/memslot.py --gb 8 --label x -- python3 -m pytest <file> -k
  closure_factory` (the file's own runner, not the gate).
- **Negative:** the same factory with a captured parameter reassigned after
  the nested `def` must still refuse, with the refusal named.
- **Regression:** the `pick(3)` local-binding shape above still prints `12`.

### What is NOT claimed

- That the real `summarize_stats.py` compiles after this. Its
  `calc_histogram_table` body (a `for`, a `while`, `f"<= {k:,d}"`, a slice
  return) must also lower through the coroutine-body emitter; that is
  unverified and is the first thing to measure after the reproducer passes.
- That `iter_optimization_tables` / `iter_specialization_tables` have no
  further blocker. The 2026-08-23 entry below recorded other shapes in those
  generators (`Section___init__` extern typing, a bare `continue`, a
  declaration-ordering error); those were fixed or not reached since, and
  must be re-measured with the real file, not assumed.

## Status (2026-09-03 — nested non-capturing sync-helper coroutine codegen LANDED as shared infra; this file still refused, narrower reason)

Implemented real compilation of nested NON-capturing sync `def`s that are
referenced as callees inside a compiled generator/coroutine body
(`_cpp_compile_nested_sync_helpers` in `gimple_cpp_async.py`; `_cpp_expr`
CallExpr resolution + a `'helper'` `_cpp_emit_kind` for plain-`return`
lowering in `gimple_cpp_core.py`). Such a helper is emitted as a
standalone `static` C++ function ahead of the coroutine `{impl}` when it
captures nothing from the enclosing scope, takes only scalar/string/
container params (annotation → call-site inference → body-usage
inference), has an agreeing statically-inferred scalar/string/container
return type, and contains no further nested `def`. Verified end-to-end
(gcc `.c` + g++ `.cpp`) by `test_gimple.py`'s new
`generator_nested_noncapturing_helper_compiles_via_cpp_path`.

This file is NOT closed by that: `calc_histogram_table` /
`calc_specialization_table` (the two remaining unresolved callees) each
have the shape `def calc_X(...): def calc(stats): ...; return calc` —
they RETURN a nested closure that captures their own params. That is the
genuinely feature-sized "callable value / closure compilation" case the
new helper compiler deliberately excludes (a helper whose body contains a
further nested `def` is skipped). So the generator stays honestly refused
on those two callees. No regression — `fire.py build` behaviour on this
file is byte-identical to before.

## Status (re-verified 2026-08-26, worktree-agent-a01a24fff53233531 @ master `43fb291`): byte-identical refusal, unchanged

Fresh `python3 fire.py build .../Tools/scripts/summarize_stats.py`
against this worktree (fast-forwarded to master `43fb291`): identical
refusal naming exactly `iter_optimization_tables`
(`calc_histogram_table(...)`) and `iter_specialization_tables`
(`calc_specialization_table(...)`) — both unresolved NESTED-function
callees local to the enclosing `pre_succ_pairs_section()`, capturing
enclosing-scope locals. Real closure compilation for nested functions
referenced as callees inside coroutine bodies is feature-sized, shared
machinery with a documented regression history. Not attempted; no code
change.

## Status (re-verified 2026-08-26, wtOpencode_ctypesutil2): byte-identical refusal, unchanged

Fresh safety-wrapped repro against current tree past d3e758a: identical
refusal naming exactly `iter_optimization_tables`
(`calc_histogram_table(...)`) and `iter_specialization_tables`
(`calc_specialization_table(...)`) — both unresolved NESTED-function
callees local to the enclosing `pre_succ_pairs_section()`, capturing
enclosing-scope locals. Supporting them needs real closure compilation
for nested functions referenced as callees inside coroutine bodies —
feature-sized work on shared machinery with this project's documented
closure-machinery regression history. Not attempted; no code change.

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
  `“the constructor-call-site field-typing pass understood only scalars”`);
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
