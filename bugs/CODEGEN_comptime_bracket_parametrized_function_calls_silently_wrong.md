# CODEGEN: comptime bracket-parametrized function calls (`f[N](...)`) silently compile to a placeholder instead of the real computation

## Discovery context

Found while scoping Group 1 of the compiled-async-codegen follow-on
project (`test/runtime/test_asyncrt.mojo`/`test_locks.mojo`/
`test_raising_asyncrt.mojo`/`test_tracing.mojo`, all currently refused
whole-module because of `@parameter async def f[N: Int](...)`-shaped
nested async functions — see `_async_quick_eligible`'s "no parameters"
restriction). The plan's own first prerequisite step was "parametric
`@parameter async def` support" — before starting that, a hand-verified
repro was built to establish ground truth for how this codegen ALREADY
handles a comptime bracket parameter on an ordinary (non-async) function,
since `FunctionDef.comptime_params` (a name-only list, separate from
`.params`) is a pre-existing field with no obvious dedicated resolution
path anywhere the async-specific code touches.

## Repro

```python
def add_const[lhs: Int](rhs: Int) -> Int:
    return lhs + rhs

def main() raises:
    print(add_const[1](10))
    print(add_const[2](20))
```

Real Mojo/CPython-equivalent semantics: prints `11` then `22`.

Compiling this through `gimple_codegen.py` (via
`build_stdlib_dylib.compile_module_to_c_cached`) produces, for `main`'s
body:

```c
  _t1 = 0;
  ...
  sprintf (_t2, _t4, _t1);   /* prints "0" */
  ...
  _t6 = 0;
  ...
  sprintf (_t7, _t9, _t6);   /* prints "0" */
```

Both calls to `add_const[N](rhs)` — a comptime-bracket-parametrized call to
a plain top-level function — are folded straight to the constant `0`.
`lhs` is never bound to `1`/`2`, `rhs` is never even read, and
`add_const`'s body (`return lhs + rhs`) is never actually invoked or
inlined anywhere in the output. This is not a refusal (no exception is
raised, no honest fallback message) — it is a **silent**, wrong result
that happens to be syntactically valid C and passes `-fgimple
-fsyntax-only` cleanly, so it would never show up as a `compile_stdlib.py`
failure on its own; it only surfaces once something (like this test's own
real output) is actually run and checked.

A structurally different but same-root variant, using a comptime FUNCTION-
typed bracket parameter on a STRUCT METHOD instead of a plain Int on a
free function, was also confirmed broken (see
`bugs/CODEGEN_device_context_captured_function_parameter_closures_broken.md`'s
Repro 1) — there, instead of folding to `0`, the bracket parameter's NAME
is emitted as a bare, unresolved C identifier call. Different failure
mode, same underlying gap: comptime bracket-parameter BINDING (whatever
concrete value/function was supplied at a specific call site) is not
actually threaded through to the callee's body in either shape.

## Why this blocks Group 1

`test_asyncrt.mojo`'s very first real test (`test_runtime_task`) opens
with:

```python
@parameter
async def test_asyncrt_add[lhs: Int](rhs: Int) -> Int:
    return lhs + rhs
```

then calls it as `test_asyncrt_add[1](a)` / `test_asyncrt_add[2](b)`.
Two of the four Group 1 test files' `@parameter async def` bodies depend
on this exact mechanism — comptime bracket parameters correctly bound per
call site — for correctness: `test_asyncrt.mojo` itself (also
`return_value[value: Int]`) and `test_tracing.mojo`
(`test_tracing_add[enabled, 1]`/`[enabled, 2]` and
`test_tracing_add_two_of_them[enabled]`). The other two Group 1 files,
`test_locks.mojo` and `test_raising_asyncrt.mojo`, do NOT use comptime
bracket parameters on their async functions at all — they are blocked
instead by `create_task`/`Task`/`TaskGroup`/`RaisingTask` having no
codegen support whatsoever yet (a real, substantial, not-yet-started
feature, not a bug — see compile_stdlib.py's EXPECTED_FAILURES entries for
those two files for the accurate, separate reason). Even with
full async-eligibility widening and real coroutine-body `CallExpr` support
(the two prerequisites already identified for the `device_context.mojo`
line of work), building `@parameter async def` support on top of this
gap would just be a NEW, async-flavored instance of the same silent-`0`
miscompilation demonstrated above — not a real fix, and a direct violation
of this project's own standing "never silently miscompile" rule.

## Why this isn't fixed in the same pass

Like the two closure-capture bugs in
`bugs/CODEGEN_device_context_captured_function_parameter_closures_broken.md`,
this lives entirely in the GENERAL (non-async) codegen's handling of
comptime/generic parameters — used PERVASIVELY across the compiled stdlib
for essentially every generic/parametric function and method (SIMD width
parameters, dtype parameters, comptime integer parameters, etc.), not
something specific to async or to these four test files. Confirmed via two
independent repros, in two different contexts (struct method, free
function), both showing genuinely broken — not merely unsupported —
codegen for comptime-bracket-parametrized calls. Fixing this correctly
means building real per-call-site monomorphization (or an equivalent
binding mechanism) for comptime bracket parameters generally, which is a
substantial, independent, high-blast-radius project of its own — touching
the same shared, high-risk machinery CLAUDE.md's quality gate exists to
protect — not a narrow, safely-scoped addition to the async/coroutine
codegen this project has been extending. This is exactly the class of
"correctness question that can't be reasoned through safely in the
current scope" this project's standing rules call out as a legitimate
reason to stop and leave an honest, documented refusal.

## Update — top-level free-function case FIXED (this session)

The root cause was narrower than it first looked: `gimple_codegen.py`
already has a complete, working monomorphization pipeline for bracket-
parametrized calls to TOP-LEVEL functions/structs imported from another
module (`_imported_generics`/`_elaborate_generic_call`, backed by
`elaborate.py` + `monomorphize.py`'s purely-textual `\bTP\b` substitution),
and `gen_module` already self-registers a module's OWN top-level
`def f[...]`-shaped functions into that exact same mechanism (see the
"Local generic free functions" block in `gen_module`) — so same-module
calls were *supposed* to go through it too. They didn't, because
`GimpleGen._type_expr_to_ann` (which turns a bracket argument's AST node
into the string `elaborate.py` substitutes textually) only handled
type-shaped nodes (`IdentExpr`/`SubscriptExpr`/`MemberExpr`) and returned
`''` for literal VALUE nodes (`IntLiteral`, `BoolLiteral`, negative-int
`UnaryOp`) — so `_is_concrete_type_arg('')` rejected every value-typed
bracket argument, `_elaborate_generic_call` bailed out with `None`, and
the call fell through to `_lower_call`'s final `if not isinstance(node.func,
IdentExpr): return 'int', self._new_val('int', '0')` catch-all.

Fix: `_type_expr_to_ann` now also renders `IntLiteral`/`BoolLiteral`/
negative-int-`UnaryOp` nodes as their literal text (`"1"`, `"True"`, ...).
`monomorphize.py`'s substitution was already value-agnostic (plain
`re.sub(r'\bTP\b', str(concrete), src)`), so no other change was needed —
`add_const[1](10)` now really monomorphizes to a genuine `add_const_1`
function body with `lhs` substituted to `1`, compiles it via the same CAS-
backed `elaborate.Elaborator`/`monomorphize.instantiate` path any other
local generic uses, and calls it. Verified with a real compile+link+run
(not compile-only) via `test_comptime_bracket_params.py`: the exact repro
above now prints `11`/`22`, plus two more shapes (distinct bracket-value
bindings each getting their own specialization; a `Bool`-typed comptime
param, matching `test_tracing.mojo`'s own parameter shape).

## Update — nested async comptime-bracket functions FIXED too (continued this session)

Landed on top of `device_context.mojo`'s async-closure work (see
`bugs/CODEGEN_device_context_captured_function_parameter_closures_broken.md`'s
own "Update" sections): a NEW `gen_module` pass ("Async closures/functions
NESTED INSIDE A TOP-LEVEL FUNCTION") discovers a nested `async def` with
its OWN comptime bracket parameters — `test_asyncrt.mojo`'s
`test_asyncrt_add[lhs: Int](rhs: Int)`/`return_value[value: Int]()` — and
compiles it via `_gen_cpp_async_unit`, threading EVERY comptime bracket
parameter through as an ordinary trailing runtime parameter, regardless of
its annotated type (Int, Bool, ...): this codegen's async-unit compiler
never does any compile-time folding/specialization on a parameter's VALUE
at all, so `test_asyncrt_add[1](10)`/`test_asyncrt_add[2](20)` calling the
SAME compiled coroutine with `lhs` passed as an ordinary 1/2 argument is
exactly equivalent, for this codegen's purposes, to real per-call-site
monomorphization — unlike the general (non-async) paths, which DO need
real elaboration because their bodies CAN observe comptime-ness
(`@parameter if`, static array sizes). A new `_lower_call` branch (and an
`asyncio.run(...)`-composed variant, sharing a new `_emit_asyncio_run_drive`
helper factored out of the existing top-level-async-function bridge)
recognizes a bracket call to such a nested function and forwards the
bracket arguments as extra positional args at the call site. Verified
end-to-end (compile+link+run): `test_asyncrt_add[1](10)`/`[2](20)`, driven
via `asyncio.run(...)`, print `11`/`22`.

A real, PRE-EXISTING bug surfaced while landing this (independent of
whether the nested function is async): stripping a top-level local
generic function from `stmts` (the "Local generic free functions" block)
never cleaned up nested async/generator defs INSIDE it from `_async_fns`/
`_generator_fns` — those dicts are populated by a deep `_walk_ast(stmts)`
scan that runs BEFORE the strip, so a nested async/generator def's `id()`
stayed in the tracking dicts forever, un-poppable by anything (since no
later pass ever sees it once its parent is stripped), always surfacing in
the final "still unsupported" error regardless of whether it was actually
compiled via the SEPARATE per-call-site-elaborated instance. Fixed by
walking each stripped generic's own body and popping its nested
async/generator ids too.

Confirmed via the real stdlib file: `test_asyncrt.mojo` now fails ONLY on
`build_message`/`run_as_group`/`test_asyncrt_add_two_of_them` — all three
need `create_task`/`await ... + await ...` composition (root cause #3, a
separate, not-yet-landed feature) — `test_asyncrt_add`/`return_value`/
`compute` (the comptime-bracket-parametrized ones this fix targets) no
longer appear in the unsupported-function list at all.

`test_tracing.mojo` needs the identical fix (also confirmed working) but
hits a SEPARATE, harder problem on top: `test_tracing_add` is nested
inside `test_tracing[level: TraceLevel, enabled: Bool]()` — itself a
comptime-bracket-parametrized (non-async) function, elaborated via the
EXISTING cross-module-style textual monomorphizer
(`elaborate.py`/`monomorphize.py`) whenever bracket-called
(`test_tracing[TraceLevel.ALWAYS, True]()`). That monomorphizer substitutes
`level`/`enabled` textually across the WHOLE extracted block — including
inside `test_tracing_add`'s own nested bracket declaration, which
re-declares an UNRELATED comptime parameter also named `enabled` — with no
notion of nested-scope shadowing, and no support for compiling a fragment
that itself needs its own SEPARATE `.cpp` coroutine translation unit
(`monomorphize.instantiate`'s `build()` only ever compiles the `.c` side,
silently discarding `gen.generated_cpp`). Hand-verified: elaborating
`test_tracing` this way threw internally, was silently caught by
`_elaborate_generic_call`'s broad `except Exception`, and the call site
fell through to `_lower_call`'s final "not an `IdentExpr` callee"
catch-all — compiling `test_tracing[...]()`'s ENTIRE body to a bare
placeholder `0` (a genuinely NEW silent-miscompile risk, of exactly the
class this bug report exists to describe, freshly exposed by this
session's own nested-async work interacting with the pre-existing
elaboration pipeline). Fixed with an honest, upfront refusal instead:
`_elaborate_generic_call` now detects a nested `async def` inside the
generic being elaborated (via a cheap textual pre-scan of the extracted
template) and raises a clear `RuntimeError` before ever attempting textual
substitution, rather than risking the silent fallback. `test_tracing.mojo`
itself still cannot compile until monomorphize.py genuinely supports dual
C/C++ output for an elaborated fragment (a real, separate,
not-yet-started feature) — but it no longer risks silently miscompiling
in the attempt.

## Current status

Free top-level functions: FIXED and verified (`test_comptime_bracket_
params.py`). Nested async functions with their own comptime bracket
parameters (not themselves inside an ALSO-generic enclosing function):
FIXED and verified (`test_async_void_return.py`, hand-verified repros
matching `test_asyncrt.mojo`'s exact shape). `device_context.mojo`'s
Repro 1 (a comptime FUNCTION-TYPE bracket parameter on a struct METHOD) —
a structurally different, ALSO now-fixed shape — see
`bugs/CODEGEN_device_context_captured_function_parameter_closures_broken.md`.

Remaining honest whole-module refusals in `compile_stdlib.py`'s
`EXPECTED_FAILURES`: `test_asyncrt.mojo`/`test_tracing.mojo` (both now
blocked ONLY by `create_task`/`Task`/`TaskGroup` composition — root cause
#3 — plus, for `test_tracing.mojo` alone, the separate elaborated-generic-
with-nested-async gap just described), and `test_locks.mojo`/
`test_raising_asyncrt.mojo` (blocked by the same `create_task`/`Task`/
`TaskGroup`/`RaisingTask` gap, no codegen support at all yet — see their
own `EXPECTED_FAILURES` entries in `compile_stdlib.py`).

## Update — root cause #3 (create_task/await-composition) landed for `test_asyncrt.mojo`

Three narrow, related gaps in `gimple_codegen.py`'s compiled async/await
codegen, all in the SAME family (composing `create_task`/`await` inside a
compiled coroutine's own body, or via `_create_task`'s affinity-hinted
variant at ordinary call sites), fixed together and verified end-to-end
(real compile+link+run, not just `gcc -fsyntax-only`):

1. **`await create_task(<call>)` used directly in an expression** (no
   intermediate `var` — `test_asyncrt_add_two_of_them`'s `return await
   create_task(test_asyncrt_add[1](a)) + await create_task(
   test_asyncrt_add[2](b))`). `GimpleGen._cpp_expr`'s `AwaitExpr` case now
   unwraps a `create_task(...)`/`create_raising_task(...)` wrapper around
   the awaited call before the existing composition checks — semantically
   identical to awaiting the inner call directly (the same equivalence
   `_inline_single_use_task_composition`'s docstring already established
   for the `var`-bound shape).

2. **`await <call to a SIBLING comptime-bracket-parametrized nested async
   def>`** (`test_asyncrt_add[1](a)`, `return_value[1]()` — a `CallExpr`
   whose `func` is a `SubscriptExpr`, not a bare `IdentExpr`). Neither
   `_cpp_expr`'s `AwaitExpr` composition case nor `_await_call_ctype`
   (return-type unification) nor `_async_quick_eligible` (the cheap
   pre-filter) had ever handled this shape — all three now resolve it via
   `self._async_closure_api`, keyed by `(enclosing top-level function
   name, callee name)`. The tricky part: this coroutine-body emitter path
   never sets `self.current_func_name` (unlike ordinary `gen_func`/
   `gen_stmt` compiles), so the enclosing name is threaded through a new
   `self._cpp_async_enclosing_scope` side channel (mirroring
   `self._cpp_gen_self_fields`'s identical technique), set by
   `_gen_cpp_async_unit`'s new `enclosing_scope` parameter. A second,
   independent bug in the SAME family:
   `_inline_single_use_task_composition` (the `var X = create_task(f());
   ...; await X` -> `await f()` rewrite) only ever recognized a bare-
   `IdentExpr` inner callee, so `var t0 = create_task(return_value[1]())`
   (`run_as_group`'s own shape) was silently left un-rewritten, making the
   whole function look ineligible — widened to also accept a
   `SubscriptExpr`-based inner callee.

3. **`_create_task(f(), desired_worker_id=<hint>)`** (`test_
   create_task_with_affinity_runs_coroutine`) — real Mojo's affinity-
   hinted variant of `create_task`, whose hint is documented as purely
   advisory. `_lower_call` now normalizes this shape (lowering the hint
   expression for its side effects, then dropping it) onto the existing
   `create_task(...)` handling — an honest, documented simplification (no
   worker-affinity concept exists in this codegen's scheduler), not a
   correctness gap, since the hint's own contract permits ignoring it.

A separate, PRE-EXISTING bug surfaced while verifying end-to-end (a real
`g++` link failed with "`mojo_async_schedule_ready` was not declared"):
one of gen_module's several near-duplicate "does this module need
`#include <mojo_async_runtime.h>` in the generated `.cpp`?" gates (the one
guarding the `.cpp`-side `_mojoasync_SleepAwaiter`/sock-recv-awaiter
preamble) checked `self._supported_async or self._supported_async_gen or
self._supported_async_closures` but — unlike the other, sibling gates a
few hundred lines away in the SAME file — never checked
`self._nested_async_api`. Invisible to every existing test because they
always paired a plain nested async closure with something else that also
populated one of the checked dicts; `test_create_task_with_affinity_runs_
coroutine` (a single nested `async def compute()` with no comptime params,
no top-level async sibling, and no struct-method closure) is the first
real shape to hit this gate with `_nested_async_api` as the ONLY populated
dict, so the `.cpp` silently omitted the header and failed to link. Fixed
by adding `self._nested_async_api` to that one gate, matching its
siblings.

**Verified via a real compile+link+run** (not just this project's
`gcc -fsyntax-only` check): `test_runtime_task` prints `33`,
`test_runtime_taskgroup` prints `6`, and a hand-reduced repro of
`test_create_task_with_affinity_runs_coroutine` prints `affinity task
result: 42` — all exactly as expected.

**Not fixed, and intentionally not attempted this round**:
`test_runtime_unified_async_memory_result_raises`'s `build_message`
(`async def build_message() raises {mut prefix} -> String: return prefix +
String(" world")`) still cannot be compiled to a real C++20 coroutine —
its return type is `String`, and this codegen's coroutine-body emitter
(`_gen_cpp_async_unit`/`_cpp_stmt`/`_cpp_expr`) is deliberately scalar-only
throughout (see that method's own docstring) — a real, separate, larger
feature (a whole new non-scalar ctype category for that shared whitelist
emitter), not a narrow composition gap like the three above. Its
`create_raising_task(build_message())` call site therefore still falls
through to `_lower_call`'s existing, PRE-EXISTING "reachable but
uncompilable async function" stub: a loud runtime `abort()` with a
diagnostic message (NOT a silently wrong value), the same mechanism
already used for `test_raising_asyncrt.mojo`'s own provably-dead disabled
function — except `build_message` is NOT dead code here, so if this
compiled binary actually reaches `test_runtime_unified_async_memory_
result_raises`, it genuinely aborts. This is an honest, loud, documented
gap (not a silent miscompile), but it means `test_asyncrt.mojo` is not
YET fully correct end-to-end for every one of its tests — only removed
from `compile_stdlib.py`'s `EXPECTED_FAILURES` because that check is
(and, throughout this whole project, always has been) a `gcc
-fsyntax-only` check, which this file now genuinely passes. Fixing
`build_message` for real requires the non-scalar/String-return coroutine
support described above — a follow-on, not started this session.

`test_locks.mojo` (`TaskGroup` + `with`-inside-async) and `test_tracing.
mojo` (the monomorphizer nested-scope-shadowing gap, plus this same
`create_task` work, now landed) remain in `compile_stdlib.py`'s
`EXPECTED_FAILURES`, not attempted this session.

## Update — mutable (by-reference) closure capture for async coroutines (test_locks.mojo Step 1/2)

`test_locks.mojo`'s own blocker is really three independent, stackable
features (`TaskGroup` as a real type, `with`-inside-async, and mutable
closure capture) — this update lands the FIRST of the three, the one the
other two depend on having available at all: `async def inc() {mut}:
rawCounter += 1` mutating a captured local across thousands of separate
`create_task(...)` invocations, with the mutation genuinely visible back
to the caller.

**Safety validated BEFORE writing any real codegen** (this project's own
standing precedent for every prior promise/frame-shape change — see
Milestone D's/Step D's/Step H's own GCC-15 repros): a minimal, Mojo-
independent hand-written `.cpp` (a coroutine taking 1, then 3, POINTER-
typed parameters, mutating through them across multiple `co_await
std::suspend_always{}` suspend points, run at `-O0` through `-O3` on this
project's actual `g++-mp-15`) confirmed this is safe. Critically, this is
a DIFFERENT shape from the one GCC-15 corrupted before: that bug was
specifically about adding an EXTRA FIELD to the PROMISE type (see
`_gen_cpp_generator_unit`'s `unhandled_exception()` docstring) — a
coroutine's ordinary FORMAL PARAMETERS (of any type, including pointers)
have always been safe on this compiler, and this change never touches
any promise type at all.

**What changed** (all in `gimple_codegen.py`):
- `_mutated_free_names(inner, candidate_names)`: which of a nested
  closure's captured free variables its OWN body actually REASSIGNS
  (`AssignStmt`/`AugAssignStmt` with that name as the direct target,
  anywhere in the body) — those need a pointer capture; a merely-READ
  capture (every shape this project already supported: device_context.
  mojo's closures, `test_asyncrt_add`'s threaded comptime params, ...)
  keeps the existing, unchanged by-value path.
- `_enclosing_scope_with_locals(outer_fn)`: widens the captured-variable
  lookup scope beyond `outer_fn`'s own PARAMETERS (all `_compute_nested_
  closure_captures` had access to before) to ALSO include its top-level
  local `var`s — test_locks.mojo's own `lock`/`rawCounter`/`counter` are
  ALL locals of `test_basic_lock`, never parameters, so without this the
  existing capture computation silently found nothing to capture at all.
  Getting a captured local's C TYPE right here took two real, hand-
  verified false starts: an independent re-inference (`_infer_simple_
  expr_ctype`) guessed `int64_t` for a plain `var counter = 0`, but the
  REAL declared type `_gen_stmt_VarDecl` uses for that exact shape (no
  later reassignment anywhere in the function) is plain C `int` (`_lower_
  IntLiteral`'s own literal-only rule, not the broader int64_t-default
  estimators this file's OTHER "guess a scalar type" helpers use) — a
  real "incompatible pointer type" gcc error from taking the address of
  the wrong-width variable. Fixed by consulting `self._inferred_var_
  types[outer_fn.name]` (the SAME table `_gen_stmt_VarDecl` itself
  consults, for a name that IS reassigned elsewhere) with a narrow,
  literal-only fallback (`_local_literal_ctype`, mirroring `_lower_
  IntLiteral`/`_lower_FloatLiteral`/`_lower_BoolLiteral` exactly) for a
  name that's declared once and never reassigned — the actual common
  case, and the one every existing "guess" helper got wrong.
- `_gen_cpp_async_unit` gained a `mut_capture_names` parameter: a mutated
  capture's ctype in `extra_captures` is widened to a pointer (`f"{ctype}
  *"`) for the compiled unit's own SIGNATURE, while a separate `declared`
  table (feeding ordinary scalar type-inference, e.g. `counter + 1`) keeps
  the DEREFERENCED type — the C signature and the body's own type-
  inference need to disagree on purpose here.
- `_cpp_expr`'s `IdentExpr` case and `_cpp_stmt`'s `AssignStmt`/
  `AugAssignStmt` cases dereference (`(*name)` / `*name = ...`) any name
  in a new `self._cpp_mut_capture_names` side channel (mirroring `self.
  _cpp_gen_self_fields`'s identical technique — this coroutine-body
  emitter has no `self`-scoped AST annotation to consult instead).
- The `create_task(...)` call-site lowering (`_lower_call`, ordinary non-
  coroutine code) now forwards EVERY registered capture as an extra
  trailing argument (previously: none at all, for a plain nested async
  def with no comptime bracket params — read-only captures were simply
  never wired up for that specific pass either, until now) — a mutated
  one via a real GIMPLE address-of temp (`t = &name; ...`; `-fgimple`
  forbids a bare `&name` as an inline call-argument expression), a
  read-only one by value, unchanged.
- `_compile_nested_async_functions` (the pass handling a plain, non-
  comptime nested async def — test_locks.mojo's `inc()` shape) now
  actually computes and threads captures at all; it never did before
  (every real file it previously handled, e.g. `test_raising_asyncrt.
  mojo`'s `wrapper`, happened to have no captures).
- A separate, PRE-EXISTING bug surfaced by the same verification: `task.
  wait()` on a genuinely VOID-returning task unconditionally called `t =
  {base}_value(handle)` even when `vct == 'void'` — a `void` GIMPLE local
  is invalid C. This exact combination (`create_task`+`.wait()` on a void
  async function) was never exercised before (every prior test drove a
  void async function via `asyncio.run(...)` instead, which already had
  its own correct void-skip in `_emit_asyncio_run_drive`). Fixed by
  mirroring that same skip in `.wait()`'s own lowering.

**Verified end-to-end** (real compile+link+run, not compile-only) via the
new `test_mutable_async_capture.py`: a single captured `Int` incremented
by 3 separate `create_task(...)` calls reads back `3` (not `0`, which is
what a silent by-value regression would print), and two INDEPENDENT
captured counters mutated by two different closures with interleaved task
creation read back correctly (`3`/`104`) — confirming no cross-instance
frame aliasing between two different pointer-typed captures.

**Not yet done** (test_locks.mojo's own remaining two features, per the
original staged plan): `TaskGroup` as a real compiled type, and `with`-
statement support inside a compiled coroutine body (`_cpp_stmt` still has
no `WithStmt` case at all) — needed for `BlockingScopedLock`. `test_locks.
mojo` itself is NOT yet passing; this update only lands the capture
mechanism those two remaining pieces depend on.

## Update — TaskGroup + real 10,000-task stress test, plus two separate real bugs found and fixed

`TaskGroup` (test_locks.mojo Step 3) is now a real compiled intrinsic,
reinterpreted exactly like `create_task`/`create_raising_task` already
are (real Mojo's own `TaskGroup` in std/runtime/asyncrt.mojo is a
genuinely deep struct — raw MLIR ops, an atomic counter, a `_Chain`
low-level completion primitive, `List[_TaskGroupBox]` — nowhere near
reachable by this codegen's general struct-compiling path):

- `TaskGroup()` construction is intercepted in `_lower_call` (mirroring
  `create_task`'s own early-interception pattern) and represented as a
  plain `MojoList *` of int64_t-cast `MojoAsync *` handles — reusing the
  EXISTING `mojo_list_new`/`mojo_list_append_int`/`mojo_list_get_int`/
  `mojo_list_len` runtime infrastructure rather than inventing a parallel
  dynamic-array type (CLAUDE.md's consolidation principle). `self.
  _taskgroup_var_api` (name -> {'base', 'value_ctype'}) tags which
  variables are really task groups, mirroring `self._async_var_api`'s
  identical pattern.
- `.create_task(<call>)` and `.wait[origin]()` (the bracket origin
  argument is silently dropped — this codegen does no borrow-checking, so
  it's genuinely unneeded — reaching `_lower_method_call` as a plain,
  bracket-free `.wait()` via the EXISTING SubscriptExpr+MemberExpr
  routing) are handled in `_lower_method_call`, right next to the
  existing single-`Task`.`wait()` case they mirror. The resolve+
  construct+schedule sequence (including capture-forwarding) was factored
  out of the free `create_task(...)` call site into a new shared
  `_resolve_and_start_task` helper — the SAME sequence, not a second copy
  of it, now used by both call sites.
- Every task added to ONE `TaskGroup` must compile to the SAME async
  unit — an honest compile-time refusal (not silent wrongness) for the
  genuinely heterogeneous case real Mojo's type-erased `_TaskGroupBox`
  supports and this narrower reinterpretation doesn't; every real target
  shape only ever adds one kind of task to a given group.
- A real, hand-verified gap in the EXISTING nested-async-helper scoped-
  push (`self._nested_async_api` -> `self._async_api`, added by the
  create_task/await-composition work): it was only ever pushed around
  `gen_func` for a top-level function's OWN body compile, never around
  the closure-LIFTING loop (`_emit_closure_recursive`/`_gen_lifted_
  closure`) for that SAME top-level function's OTHER nested (ordinary,
  non-async) closures — so `tg.create_task(inc())` called from a
  DIFFERENT sibling nested closure (not the one `gen_func` compiles
  directly) found no entry for `inc` in `self._async_api` at all. Fixed
  by moving the push earlier, to wrap both the closure-lifting loop and
  `gen_func`.

**Two SEPARATE, pre-existing bugs found and fixed** while building a real
10,000-task stress-test repro (test_locks.mojo's own `for _ in
range(maxI): for _ in range(maxJ): tg.create_task(inc())` shape, with
`comptime maxI/maxJ` loop bounds):

1. **Nested `for` loops reusing the SAME loop-variable name** (`for _ in
   range(...): for _ in range(...): ...` — real Mojo/Python's extremely
   common "don't care" idiom, and exactly test_locks.mojo's own shape)
   silently corrupted the OUTER loop's iteration state: `_gen_for_range`
   used the user-visible loop variable itself (`_`) as BOTH the loop's
   own control/counter storage AND the per-iteration value exposed to the
   body — since `self._declare_var`/the C variable list are NAME-keyed,
   an inner loop sharing the outer loop's variable name reused the SAME
   underlying storage, so the inner loop's own reset/final value corrupted
   the outer loop's condition check on its next test after the inner loop
   finished. Hand-verified: `for _ in range(100): for _ in range(100):
   calls += 1` printed `100`, not `10000` — the outer loop silently ran
   only ONE iteration. This is a genuinely different bug from the
   already-known `_lower_in_impl` "'in' for char*" gap (see the bootstrap-
   verify session's own notes) — a fresh discovery, not a re-hit of a
   documented one. Fixed by decoupling loop CONTROL from the user-visible
   variable entirely: a dedicated internal counter temp (always fresh,
   never reused across nesting depths) drives the condition/increment,
   and the user variable is simply assigned the counter's current value
   once per iteration, at the top of the body — matching real Python/Mojo
   semantics (reassigning the loop variable inside the body never affects
   the loop's own iteration count) and fixing the collision regardless of
   variable name, not just for `_`.
2. **A local `comptime NAME = <value>` read as an ORDINARY runtime value**
   (`comptime maxI = 100` then `range(0, maxI)`, test_locks.mojo's own
   loop-bound idiom) silently substituted `0` — `_gen_stmt_ComptimeVarStmt`
   folds the value into `self._comptime_vals`, but that dict was
   previously consulted ONLY by `_eval_const` (comptime `if`/expression
   contexts), never by the ordinary runtime `IdentExpr` read path
   (`range(0, maxI)`'s own argument lowering) — falling through to that
   path's generic "unknown identifier" placeholder, which silently emits
   `0`. A REAL, hand-verified silent-miscompile risk, not just a narrow
   refusal. Fixed by consulting `self._comptime_vals` in that fallback
   too, before the placeholder.

**Verified end-to-end** (real compile+link+run) via the new `test_
taskgroup.py`: 100 tasks each incrementing a shared mutable capture via a
`TaskGroup` (`100`), the full test_locks.mojo-shaped 10,000-task stress
test with same-named nested `for _` loops and `comptime` bounds
(`10000`, exactly — proving no lost/double-counted increments), and the
nested-loop fix in isolation (also `10000`).

**test_locks.mojo itself is STILL not passing** — attempting the real
file directly surfaces three more, separate gaps: (1) `with
BlockingScopedLock(lock):` inside `inc()` — `_cpp_stmt` has no `WithStmt`
case at all (test_locks.mojo Step 4, not started); (2) `counter: Atomic[
DType.int64]` is a non-scalar STRUCT capture — this codegen's mutable-
capture mechanism only handles scalar (int64_t/double/_Bool) captures,
the same "deliberately scalar-only throughout" barrier `build_message`
(test_asyncrt.mojo) already needs lifted, for a different reason; (3)
`inc()` is called from `test_atomic()`, a DIFFERENT nested (ordinary,
lifted) closure than the one declaring its captures (`test_basic_lock`)
— confirmed via a hand-written repro that this hits an honest, newly-
added refusal (not a silent miscompile: `self.var_types` is checked
before emitting `&name`) rather than a confusing raw gcc "undeclared
identifier" error. The general (non-async) closure-lifting mechanism has
no notion of "this closure transitively needs a capture because it calls
something that does" — teaching it that is a real, structurally separate
change to a DIFFERENT, already-complex subsystem, assessed as a genuine
blocker for confident same-session completion rather than something to
force. `compile_stdlib.py`'s `EXPECTED_FAILURES` entry for test_locks.
mojo has been updated to describe these three remaining gaps precisely
(TaskGroup and scalar mutable capture removed from its description, since
both now work).

## Update — investigated (not fixed) the transitive-closure-capture gap; found it's deeper than a name-propagation fix

Investigated whether gap (3) above (`test_atomic()` calling `inc()`
without itself referencing `inc()`'s captured `lock`/`counter`) is
fixable by simply widening `_scan_for_closures`'s free-variable
computation for the CALLING closure (`test_atomic`) to transitively
union in any REGISTERED async unit's own captures whenever the calling
closure's body calls that unit by name — i.e. teach the general
(non-async) closure-lifter "this closure needs variable X because it
calls something that needs X", not full call-graph analysis (this
project's own async-unit registration already gives an exact, flat
name -> captures lookup, no graph traversal needed).

That part is genuinely simple. But a SEPARATE, deeper problem surfaced
first: does the GENERAL (non-async) closure-lifting mechanism even
support a captured variable being MUTATED at all today?

**Correction (independently verified against real Mojo via `tools/mojo`
after this Update was first written):** the original repro here was
`def inc(): counter += 1`, with NO explicit capture-spec — that is not
actually valid Mojo. Real Mojo rejects it outright at parse time:
`error: Could not infer capture convention of the captured value
counter`. Mojo requires an explicit `{mut}` capture-spec (unlike
Python's implicit closure-over-enclosing-scope) to mutate a captured
variable at all. The corrected, actually-valid repro:

```python
def test_ordinary_mut() raises:
    var counter = 0
    def inc() {mut}:
        counter += 1
    inc(); inc(); inc()
    print(counter)
```

Confirmed against real Mojo (`tools/mojo`): prints `3`, as expected.
Confirmed against THIS project, both paths, independently: `mojo.py run`
prints `0`; `mojo.py build` + running the compiled binary also prints
`0`. So the underlying finding stands, just narrower/more precise than
originally stated — this is not "real Mojo silently allows implicit
mutable capture and we're wrong about the default"; it's "even the
explicitly-`{mut}`-annotated, actually-valid form of mutable capture
doesn't work in either of this project's execution paths." This is a
genuinely SEPARATE, PRE-EXISTING, latent bug in the general closure
system — independent of async, independent of TaskGroup, independent of
this whole project — that nothing in this codebase's own test suite
currently exercises or depends on (confirmed: no existing test covers a
`{mut}`-capture-spec closure at all), which is presumably why it's gone
unnoticed.

This changes the shape of gap (3): transitively PROPAGATING `inc`'s
capture NAMES into `test_atomic`'s own free-variable set (the simple
part) would still not be enough on its own -- `test_atomic` would need
the GENERAL closure lifter to ALSO thread `lock`/`counter` through to it
BY REFERENCE (a pointer), a capability that mechanism does not have at
all today for ANY nested closure, sync or async. Building that is
structurally the same kind of change this session's own async mutable-
capture work already did (see the "Update — mutable (by-reference)
closure capture" section above) — pointer-typed captured parameters,
dereferenced reads/writes — but applied to a DIFFERENT, much more
widely-used code path (`_gen_lifted_closure`/`_scan_for_closures`,
exercised by every ordinary nested closure in the entire stdlib compile,
not just async ones), which is real, additional regression surface this
session's own async-only changes never touched.

**Assessment: deeper than the simple transitive-name-propagation fix
this update set out to try** — confirms the coordinator's own stated
condition for stepping back (needs a new capability in a widely-shared
subsystem, not just call-graph/name propagation). Not attempted further
this session. `test_locks.mojo` remains blocked on all three gaps listed
in the previous update; moving on to `test_tracing.mojo` next per the
standing plan.

## Update — general {mut}-capture fix landed, then transitive capture propagation (gap 1) fixed on top of it

A later session fixed the deeper blocker identified just above: general
(non-async) `{mut}`-capture-spec closures (`def inc() {mut}: counter +=
1`) now genuinely mutate their captured variable by reference, in both
execution paths (commit `90dbbbe`) — see `myinterpreter.py`'s
`_assign_target`/`Scope.set` fix and `gimple_codegen.py`'s heap-boxed
`_boxed_mut_locals` mechanism (needed instead of a plain `&stack_local`
because `-fgimple` rejects a stack local's address being taken anywhere in
a function that also casts or `return`s that same local elsewhere — a real
gap the by-reference-capture design above didn't anticipate, surfaced by
`std/memory/span.mojo`'s own `Span.count`).

With that landed, gap (1)/(3) (transitive capture — `test_atomic()`
calling `inc()` without itself referencing `inc()`'s own captures) turned
out to be exactly the "simple part" this Update originally set out to try,
now that the general closure lifter can actually thread a capture through
by reference at all: `_scan_for_closures` was widened to transitively
union in a called `self._nested_async_api` unit's own captures (value AND
mut_names) into the CALLING closure's own capture set, and
`_resolve_and_start_task` (the `create_task(...)`/`TaskGroup.create_task(
...)` call-site lowering) now forwards a mutably-captured name from
either a heap-boxed LOCAL of the current function or an already-preloaded
`_gimple_mut_ptr` entry (this closure's own by-reference capture of that
same name), not only ever `&name` (which is invalid inside a closure body,
where the name was never a plain addressable local to begin with).

Verifying this against a real 10,000-task stress test (mirroring
test_locks.mojo's own `for _ in range(maxI): for _ in range(maxJ):
tg.create_task(inc())` shape, called from a sibling closure) surfaced TWO
FURTHER, separate, genuinely pre-existing bugs — both fixed, both
previously unreachable because `.wait()`/`comptime` had simply never been
exercised from inside a nested (non-top-level) closure by any existing
test:
  - Every `.wait()` call site's `mojo_exc_pending_get()` pending-exception
    check declared its result temp as `_Bool`, but the real runtime
    prototype returns `int` — invalid under STRICT `-fgimple` ("invalid
    conversion in gimple call"). Silently tolerated everywhere else only
    because every other `.wait()` call site compiled through `gen_func`'s
    LENIENT (non-`__GIMPLE`-tagged) top-level-function path, which accepts
    the implicit int→_Bool narrowing like ordinary C — `_gen_lifted_
    closure`/`_gen_struct_method` always emit `__GIMPLE`, so this was only
    ever going to surface once `.wait()` became reachable from inside one
    of those. Fixed by declaring the temp `int` instead (works identically
    as an `if (...)` condition).
  - A `comptime NAME = <value>` declared in an enclosing function was
    invisible to that function's OWN nested closures (silently read as
    `0` via `_lower_IdentExpr`'s existing "ct param or undeclared"
    fallback — NOT a compile error, a real silent-miscompile risk).
    Closures are compiled in a pre-pass BEFORE the enclosing function's
    own body (and hence its `comptime` statement) is ever compiled via
    `gen_func`. Fixed by pre-folding an enclosing function's own
    top-level `comptime` statements into `self._comptime_vals` before
    compiling any of its nested closures.

Verified end-to-end (real compile+link+run) via `test_transitive_closure_
capture.py`: the simplest bare `create_task(...)`-from-a-sibling-closure
shape (`3`), and the full 10,000-task TaskGroup stress test with
same-named nested loops and `comptime` bounds, called from a sibling
closure (`10000`, exactly).

Also fixed a real gap in this project's own quality-gate tooling found
while re-verifying `make check-selfhost` after this work: `checked_run.py`
check-selfhost target never included `gimple_codegen.py` in its cache
key's `--extra` list (only `mojo_compiler.py`/`myinterpreter.py`/`mojo.py`/
`mojo_main.py`/`test_selfhost.py`), even though it's the compiler
`test_selfhost.py` actually exercises and is listed as a Makefile
prerequisite — a change to `gimple_codegen.py` alone could get a STALE
cached "pass" replayed without ever being re-verified. Fixed by adding
`--extra gimple_codegen.py` to the Makefile target.

`test_locks.mojo` remains blocked on the two REMAINING gaps: `with
BlockingScopedLock(lock):` inside `inc()`'s body (no `WithStmt` case in
the async coroutine body emitter) and the non-scalar (`Atomic[DType.
int64]`) struct capture. `compile_stdlib.py`'s `EXPECTED_FAILURES` entry
updated accordingly (662/664 unchanged, 0 unexpected).
