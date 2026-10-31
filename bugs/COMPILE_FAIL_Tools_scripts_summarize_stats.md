# COMPILE_FAIL: Tools/scripts/summarize_stats.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/scripts/summarize_stats.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (2026-10-30, round 6 — str-returning factory closure fixed on the NON-coroutine path; the coroutine gates are untouched)

Round 5 stopped because the typed-callable change overlapped
`bug:CODEGEN_closure_str_return_is_lost`. The owner handed that bug to this
worker (2026-10-30), so this round did the closure-str fix first. It is
landed and documented in `bugs/CODEGEN_closure_str_return_is_lost.md`.

What it does and does NOT do for this file:

- It fixes a capturing closure RETURNED as `str` through the ordinary
  (gimple) pipeline, including `g = mk(...)` and `mk(...)(...)`. It does not
  touch `cpp_async.py`'s closure-factory gates (lines ~1568/1592), which are
  what refuses `calc_h(...)` inside a GENERATOR body. `calc_histogram_table`
  is a generator body, so the real file still takes the coroutine path and
  is still refused there.
- Plan steps 2-5 (typed `std::function<R(P...)>` slots, the two `int64_t`
  gates, and `cpp_core.py` typed dispatch) are NOT started. The next round
  owns them, and the closure-str owner's gate work is now this worker's.
- Untyped closure parameters still default to `int64_t` (see the closure-str
  doc). The real file's `calc(stats: Stats)` is annotated, so it is not that.

Next step is unchanged: plan step 2 (`types.py` `callable_ctype`), then the
coroutine-path gates. Measure with the one-module build on the real file
before editing `cpp_async.py`, since the round-3 probe table is the only
evidence for which bodies pass.

## Status (2026-10-29, round 5 — STOPPED at a claim boundary; no code change)

Next step is plan step 2 onward (`types.py` `callable_ctype`, `cpp_async.py`
closure-factory gates, `cpp_core.py` typed call dispatch). Steps 2-4 are one
change: a `str`/pointer-returning closure needs its typed `std::function` slot
AND its call-site dispatch together, or the value is read back as int64.
Landing step 2 alone changes no behaviour.

Stopped because that mechanism is the same one another worker holds:
`bug:CODEGEN_closure_str_return_is_lost` (`bugs/CODEGEN_closure_str_return_is_lost.md`,
"a closure that returns a `str` prints a decimal address"). Its return-type
carry-through at the call site is steps 3-4 here. Editing `cpp_async.py`'s
closure-factory gates or `cpp_core.py`'s callable dispatch from this worker
would collide with that claim. Next round needs the controller to either hand
the typed-callable model to this bug (and let the closure-str owner land the
call-site return type first) or to the closure-str owner. The choice is theirs.

## Status (2026-10-29, round 4 — plan step 1 MEASURED; no code change this round)

Plan step 1 from round 3 (how a `Callable[...]` annotation reaches the emitter)
was run with `MOJO_DEBUG=1 python3 tools/memslot.py --gb 8 -- python3 fire.py build`
on two probes (saved under the worker's `.tmp/p1/`, not committed):

- `def use(f: Callable[[int], int], n: int) -> int` called from a generator
  (`yield use(dbl, n)`, `dbl` a module-level `int -> int`): **builds**
  (memcap peak 0.5 GB, child exit 0). So a `Callable` PARAMETER with an int64
  signature is already accepted by the coroutine path. The output was not
  executed against CPython in this round.
- The sibling-nested factory `calc_h(key)` returning `calc(stats: int) -> str`,
  called from a generator (`yield calc_h(name)(5)`): **refused** with the same
  `unresolved callee 'calc_h(...)'` message as round 3. The refusal is the
  factory-returns-str gate in `cpp_async.py:_try_compile_closure_factory`
  (lines ~1568/1592), as the round-3 analysis said.

Consequence for the plan: step 1 confirms the int64 callable-parameter path is
live, so the typed-callable work only has to widen the RETURN/PARAM gates and
the factory's value slot. Steps 2-5 are unchanged and not started. Next round
starts at step 2 (`types.py` `callable_ctype` helper). Note that each
single-module probe here costs minutes of CPU, so batch the probes.

## Status (2026-10-29, worker bug-compile-fail-tools-scripts-summarize, round 3 — the two shapes named as next step are MEASURED FIXED; the real blocker is the callable VALUE model; planning guide below)

Supersedes the "NOT DONE (next step)" paragraphs further down: the tuple-target
loop and the list-literal ctor argument both build now (see the list-literal
entry below), and the factory call itself is no longer the refusal.

### Measurement (this round, light worker, one module each, `MOJO_DEBUG=1 python3 fire.py build`)

Probe shape: `outer()` with a sibling factory `calc_h(key, den)` returning a
nested `calc`, called from `iter_tables` (a generator) as
`yield Section("sec", [Table("t", calc_h(name + base, den), 0)])`, where only
the BODY of `calc` varies:

| `calc` body | result |
|---|---|
| `return hist + key` (int in, int out) | compiles (no refusal) |
| `for x in range(hist): d += x` | compiles |
| `while s < hist: s += 1` | compiles |
| `s = f"<= {hist:,d}"; return len(s)` | compiles |
| `r = [1, 2, 3]; return len(r[hist:key])` | compiles |
| `return f"<= {hist:,d}"` (str return) | REFUSED: `unresolved callee 'calc_h(...)'` |
| `r = [1, 2, 3]; return r[hist:key]` (list return) | REFUSED: same |

So the f-string, the `while`, the slice and the `for` are all fine. The refusal
is the RETURN TYPE of the closure. The real file's `calc` also takes a non-int
parameter (`calc(stats: Stats) -> Rows`), which the same gate refuses.

Measured on the real file only by reading it, not by a completed build (a whole
module build is the integrator's job): `RowCalculator: TypeAlias =
Callable[["Stats"], Rows]` (summarize_stats.py:32), `Rows: TypeAlias = list[tuple]`
(line 30). The real `calc_histogram_table` (line 1224) therefore has the
same two gates the probe hits.

### Why (code path)

- `mojo/backend_gimple/cpp_async.py:1568`: `if len(params_C) > 1 or any(ct !=
  'int64_t' for _, ct in params_C): return False` — a closure parameter must be
  one int64.
- `cpp_async.py:1592`: `if _helper_return_ctype(C.body, hC) != 'int64_t': return
  False` — a closure must return an int64.
- `cpp_async.py:1602`: `callable_ct = (_CPP_CALLABLE_CTYPE_1ARG if params_C else
  _CPP_CALLABLE_CTYPE)`, and `mojo/middle/types.py:2445-2446`:
  `_CPP_CALLABLE_CTYPE = 'std::function<int64_t()>'`,
  `_CPP_CALLABLE_CTYPE_1ARG = 'std::function<int64_t(int64_t)>'`. Every callable
  VALUE in the coroutine path has this one signature. There is no slot for a
  `Callable[[Stats], list]`.
- The consumer side is also typed-blind: `calc_rows: RowCalculator` is called
  as `calc_rows(stats)` in a non-generator body, and nothing carries
  `Rows`/`Stats` from the alias to that call's result. Boxing the return as
  int64 pointer bits (the convention struct pointers already use in lists)
  would make the bits, but the caller would not know to unbox them.

### Decision (taken here, not asked)

Typed callable values, scoped to what the real file needs: a callable value
carries its signature (`(param ctypes) -> return ctype`) in the type system, and
its slot is `std::function<R(P...)>` for that signature, not the fixed int64
one. Params and returns that are pointer-shaped (struct, list, dict, str) cross
the boundary as their own C pointer type. This is a type-model change and
touches `types.py`, `cpp_async.py`, `cpp_core.py`'s `mojo_fnptr_call_N`
dispatch, and the alias resolution for `Callable[[...], ...]`. It is feature
sized and is NOT attempted in this round, because the call-site dispatch and the
alias resolution each need a measurement first (below).

### Implementation plan (for the next round, exact places)

1. Measure, don't assume: how `Callable[[A], B]` in an annotation reaches the
   coroutine emitter today. Probe: a module-level `def use(f: Callable[[int], int]) -> int`
   and a generator calling it; and the same with `-> str`. Record where the
   alias is erased (`types.py` / `gimple_exprtypes.py`) and what ctype a
   `Callable` parameter gets.
2. `types.py`: a `callable_ctype(params, ret)` helper returning
   `std::function<R(P...)>`, keeping `_CPP_CALLABLE_CTYPE` and
   `_CPP_CALLABLE_CTYPE_1ARG` as the int64 special case so existing callers are
   unchanged (no duplicate implementation: the two constants become calls to the
   one helper).
3. `cpp_async.py:_try_compile_closure_factory`: drop the two `int64_t` gates
   (lines 1568, 1592) for params/returns that are pointer-shaped; build
   `callable_ct` from the closure's own signature instead of lines 1602-1603.
   Keep the `nonlocal` refusal (line ~1573) and the captures check.
4. `cpp_core.py` call site (around line 4346 / 4969): a call to a typed callable
   local uses that signature's dispatch (a typed `std::function` call), not
   `mojo_fnptr_call_N` with int64 args; `mojo_fnptr_call_N` remains the int64 path.
5. `test_regress_codegen_generator_closure_factory.py`: the new pin
   `test_closure_factory_with_non_int64_return_still_refused` (added this round)
   flips to a compile check when step 3 lands; the `nonlocal` negative stays.

### Tests that prove it (for the next round)

- Flip the pin above into "compiles", and add a value test: a `str`-returning
  factory called through the generator, printing `<= 5` and matching CPython.
- The real file: `MOJO_DEBUG=1 python3 fire.py build` on
  `Tools/scripts/summarize_stats.py` is the acceptance test, and it is a
  whole-module build, so it is the integrator's to run (not a light worker's).

### NOT claimed

- That the real `summarize_stats.py` compiles after the typed-callable step. It
  has further shapes (`Section___init__` typing, the `Stats` struct param, the
  `Rows` list of tuples) that are unmeasured on the real file.

## Status (earlier round) (2026-10-29, worker bug-compile-fail-tools-scripts-summarize — list-literal call argument LANDED; real file still NOT verified)

LANDED (`mojo/backend_gimple/cpp_core.py`):

- A struct-instance element in a list-literal ARGUMENT of a struct constructor
  (`Section("sec", [Table("t", ...)])`) used to lower to a raw C++ brace list
  `{[&]() -> Table * {...}()}` at a `MojoList *` extern parameter, which g++
  rejects. It now lowers to a real `MojoList*` through the boxed-element builder
  (`_cpp_boxed_list_literal_expr`), the same pointer-bits-in-an-int64 convention
  every struct pointer in a list already uses.
- The argument lowering is one helper, `_cpp_call_arg_expr`, used by both the
  generic CallExpr argument list and `_cpp_emit_generator_start_expr` (which had
  its own inline copy of the same ListExpr branch).
- `_cpp_is_struct_pointer_elem` recognises a struct constructor call (honouring
  the same local-shadowing rule as the constructor branch) and struct-typed
  expressions.
- Test: `test_generator_list_literal_of_structs_ctor_arg_is_valid_cpp` in
  `test_regress_codegen_generator_closure_factory.py`. It FAILS before the fix
  (brace-list text present) and PASSES after (g++ `-fsyntax-only` clean).

MEASURED, NOT A BLOCKER: the tuple-target loop named in NOT DONE below
(`for name, den in [(1, 2), (3, 4)]` inside a generator) does NOT reproduce on
this tree. It lowers to an indexed loop (`for (int64_t _mg_i_1 ...)`) and
syntax-checks. The doc's full reproducer (factory + tuple target + struct-list
argument, `calc_hist(name, den)` inside `Table(...)` inside `Section(...)`) now
passes `g++ -std=c++20 -fsyntax-only` (rc 0; only pre-existing
`-Wwrite-strings` warnings remain).

Scope and verification: quick tests only. `test_regress_codegen_generator_closure_factory.py`
6/6 and `test_regress_codegen_generator_frame.py` 8/8 pass. `test_gimple.py`'s
real test cases pass; its three `test_c_shape`/`test_gimple_body`/`test_raises`
are helper functions with required args, not tests. NOT run: the gate, and the
real `Tools/scripts/summarize_stats.py` build. The generic call-argument change
affects every compiled-body call with a list literal argument, so the integrator
gate (stdlib-dylib skip count, stdlib-syntax U count) is what decides it.

NOT DONE (next step): build the real file once, for the integrator, with
`MOJO_DEBUG=1 python3 fire.py build <Tools/scripts/summarize_stats.py>`, and
triage what it still refuses. The first thing to measure is
`calc_histogram_table`'s body (a `for`, a `while`, `f"<= {k:,d}"`, a slice return),
which has not been through the coroutine-body emitter.

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
diagnosed gap as `the (since-fixed) compiled-generator lambda-expression bug`: `_cpp_expr` (the coroutine `.cpp` emission path) has no
`LambdaExpr` case at all, and that doc's own investigation already
established this needs a new "callable value" declared-type category
(not a narrow widening — see that doc's "Why this is feature-sized,
not narrow" section for the full reasoning, which applies unchanged
here). Genuinely structural; not attempted here. No code change made
for this bug — the remaining blocker is a duplicate of an
already-tracked, already-assessed gap, not a new root cause.

(An older status further down used to show a stale raw GCC warning dump from a much earlier, pre-refusal-gate run — removed as no longer reflecting current behavior; the module now fails cleanly at the up-front generator-refusal gate above, before any C/C++ is ever handed to GCC.)
