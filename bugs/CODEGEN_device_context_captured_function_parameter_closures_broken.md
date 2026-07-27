# CODEGEN: captured comptime-function/`FuncType` parameter closures are broken in the GENERAL (non-async) codegen — blocks `std/gpu/host/device_context.mojo`, independent of async

## Discovery context

Found while implementing Step 4 of the compiled-async-codegen follow-on
project (getting `device_context.mojo`'s four `async def wrapper(...)
capturing -> None:` closures — see
`bugs/COMPILE_FAIL_*device_context*.md`-style tracking / compile_stdlib.py's
failing-file list) to compile. The original scoping assumed the ONLY gap was
`_async_quick_eligible` refusing parameterized `async def`s plus a missing
`_take_handle()` lowering. That assumption was correct as far as it went,
but a deeper investigation (needed once `_gen_cpp_expr`/`_cpp_stmt`, the
dedicated coroutine-body sub-compiler, turned out to have **no `CallExpr`
case at all** — see the async-project commit history / prior session notes)
surfaced two separate, PRE-EXISTING bugs in the shared, non-async closure
codegen that `wrapper()`'s body itself depends on — bugs that exist
independent of async or coroutines entirely, and that a hand-written,
non-async nested closure reproduces identically.

## Repro 1 — comptime function-type bracket parameter, called from a nested closure

```python
struct Ctx:
    var api: String
    def __init__(out self):
        self.api = String("cpu")

    def enqueue_cpu_function[
        func: def() capturing -> None,
    ](self) raises:
        def wrapper() capturing -> None:
            func()
        wrapper()

fn func_impl():
    print("ran")

def main() raises:
    var c = Ctx()
    c.enqueue_cpu_function[func_impl]()
```

Compiling this through `gimple_codegen.py` (via
`build_stdlib_dylib.compile_module_to_c_cached`) produces, for
`wrapper`'s body:

```c
int64_t func(...);
...
void __GIMPLE Ctx_enqueue_cpu_function_wrapper (void)
{
bb_2:
  func ();
}
```

`func` — the literal SOURCE PARAMETER NAME of the enclosing method's
comptime bracket parameter — is emitted as a bare, unresolved C
identifier, declared via a bogus catch-all `int64_t func(...);` (variadic,
wrong return type) extern prototype. It is never resolved to the REAL
bound callee (`func_impl` in this repro). This passes `gcc -fgimple
-fsyntax-only` (any extern declaration + matching call is syntactically
valid), which is why it has never shown up as a `compile_stdlib.py`
failure — but it is a hard **link error** in any real program (no
definition of a symbol literally named `func` exists), and even if one
coincidentally did exist, calling it would be semantically wrong.

## Repro 2 — runtime `FuncType`-parametrized closure argument

```python
struct Ctx:
    var api: String
    def __init__(out self):
        self.api = String("cpu")

    def enqueue_cpu_function[
        FuncType: def() -> None,
    ](self, func: FuncType) raises:
        def wrapper() capturing -> None:
            func()
        wrapper()

fn func_impl():
    print("ran")

def main() raises:
    var c = Ctx()
    c.enqueue_cpu_function(func_impl)
```

Here `func` genuinely reaches the nested closure through this codegen's
real environment-capture mechanism (`_env_wrapper`) — but the generated
environment struct is declared with **zero fields**:

```c
typedef struct Ctx_enqueue_cpu_function_wrapper_env {
} Ctx_enqueue_cpu_function_wrapper_env;
```

while the capturing code still writes through a `func` member that was
never declared on it:

```c
  _env_wrapper->func = _t1;
```

This also passes `gcc -fgimple -fsyntax-only` (GIMPLE mode does not appear
to validate the member exists against the incomplete-looking struct
tag the way an ordinary `gcc -c` compile would), but is a real, serious
bug: writing through `_env_wrapper->func` on a 0-byte-payload struct is
either a hard compile error under a normal (non-`-fgimple`) build or
undefined behavior / heap corruption if it somehow links. This is a
correctness bug in the closure-capture field-collection pass (something
scans a nested function's captured names to size/declare the env struct,
and it isn't seeing `func` as capturable — likely because it's a
`FuncType`-generic-typed parameter rather than a plain scalar/pointer
local), independent of async entirely.

## Why this blocks `device_context.mojo` specifically

All four `async def wrapper(...) capturing -> None:` closures in
`enqueue_cpu_function`/`enqueue_cpu_range` (both the comptime-bracket-param
overload and the runtime-`FuncType`-param overload) call their captured
`func`/`FuncType` argument as their ENTIRE body. Even with full `_take_handle()`
lowering and eligibility widened for parameterized, zero-await `async def`s
(the piece Step 4 originally set out to add — see
`runtime/mojo_async_runtime.h`/`.cpp`'s `mojo_coro_resume_generic`/
`mojo_coro_destroy_generic`/`AsyncRT_DeviceContext_enqueueHostFunction(Range)`
stubs, added but left unwired pending this), the coroutine body's captured
call would still be built on top of these two broken capture-resolution
paths — producing either a hard link failure or genuine memory corruption,
not merely an "unsupported shape" refusal. Wiring the new async plumbing on
top of it without fixing the capture bugs first would be exactly the kind
of silent miscompilation this project's own standing rule forbids.

## Why this isn't fixed in the same pass

Both bugs live in the GENERAL (non-async) closure/capture codegen — the
same machinery used PERVASIVELY across the entire compiled stdlib for
every higher-order-function call site, sort comparators, callback
closures, etc. (not something specific to `device_context.mojo` or to
async). Fixing either one correctly requires touching genuinely shared,
high-blast-radius code with no narrow, safely-scoped edit available —
exactly the class of change CLAUDE.md's quality gate (`make
check-selfhost` + full from-scratch stdlib dylib skip-count comparison) is
built to catch regressions from, and exactly the class of "correctness
question that can't be reasoned through safely in the current scope" this
project's standing rules call out as a legitimate reason to stop and leave
an honest, documented refusal rather than force a fix through.

## Update — both repros FIXED (this session)

**Repro 1** (comptime function-typed bracket parameter, called via a nested
closure): the bracket argument was being silently DROPPED at the call site —
`_lower_call`'s "obj.method[TypeParam](...)" branch unconditionally forwarded
to `_lower_method_call` with the `[...]` stripped, never binding `func` to
anything. Fixed via a new mechanism (`GimpleGen._method_threaded_comptime_
params`, populated in `gen_module`'s early pre-pass): a struct method's
comptime bracket parameter is threaded through as an ordinary TRAILING C
parameter (an opaque `int64_t` callable pointer — a function value carries
no compile-time-varying information this codegen's monomorphization needs,
unlike an Int/Bool comptime value) whenever it's BOTH function-typed (its
bracket annotation textually starts with `def` — `_bracket_param_type_
annotations`) AND actually referenced as a plain identifier somewhere in the
method's own body or a nested closure's body (`_used_idents_deep`, which —
unlike the pre-existing `_used_idents_node` — crosses FunctionDef
boundaries). `_gen_struct_method` appends the parameter; `_scan_for_closures`
seeds it into a nested closure's capturable outer scope; the "obj.
method[X](...)" call site forwards the bracket argument as an extra
positional arg. Gated by BOTH signals together (not `comptime_params`
membership alone) so a comptime TYPE parameter merely BOUNDING an ordinary
parameter's type (e.g. `FuncType: def() -> None` typing `func: FuncType` —
Repro 2's own shape) is correctly left untouched.

**Repro 2** (runtime `FuncType`-parametrized closure argument): the
environment-struct CAPTURE was already working correctly (contrary to this
bug's original description — the codebase had changed since that repro was
first documented); the actual live bug was in `_gen_stmt_ExprStmt`'s
captured-function-pointer guard, which — unlike `_lower_call`'s identical
guard a few hundred lines up, which correctly calls `_lower_fnptr_call` —
only evaluated the call's ARGUMENTS (for side effects) and then silently
dropped the call itself. A bare, value-discarding statement calling a
captured function-type parameter (`func()` alone, exactly `wrapper`'s entire
body) compiled to a real no-op. Fixed by making that guard call
`_lower_fnptr_call` too, mirroring the already-correct sibling.

**Real regressions found and fixed while landing Repro 1**: the first
implementation keyed `_method_threaded_comptime_params` by bare method name
only, which cross-contaminated (a) two sibling overloads of the same method
name ON ONE STRUCT with different bracket-parameter shapes
(`std/memory/span.mojo`'s two `binary_search_by` overloads — a full
from-scratch stdlib dylib rebuild regressed from 1 skip to 4, adding
`std/memory/span.mojo` and `std/benchmark/bencher.mojo`) and (b) two
UNRELATED structs defining a same-named method where only one needed
threading (`std/builtin/variadics.mojo`'s `VariadicList.consume_elements`
vs. `VariadicPack.consume_elements` — added `std/builtin/variadics.mojo` to
the regressed skip list too). Fixed by keying on `(struct_name, method_name,
overload_id)` instead (using `_struct_method_overload_ids`, this codegen's
own established overload-safe-keying convention, and a struct-scoped,
occurrence-indexed bracket-text search rather than a whole-module,
name-only one). After the fix, a full from-scratch stdlib dylib rebuild is
back to exactly 1 skip (`device_context.mojo` itself, for the separate,
still-open async-eligibility reason below) — confirming no other stdlib
file regressed. See `test_closure_capture_comptime_func_params.py` for
real, compile+link+run (and, for the two overload-collision regressions,
real `gcc -fgimple -fsyntax-only`) verification of all of the above,
including both original repros printing `"ran"` end-to-end.

**Known remaining narrow gap** (not hit by any real stdlib file today,
confirmed via the clean full dylib rebuild, so left undone rather than
risked): once a bracket argument is appended at a call site to match a
threaded overload's real, AUGMENTED C parameter count, `_lower_method_call`'s
own overload-dispatch (which matches by the ORIGINAL, pre-threading Mojo-
level argument count) could in principle pick the WRONG sibling overload if
one happens to also accept that same augmented count — a separate,
pre-existing overload-resolution limitation this fix doesn't touch.

## Update — device_context.mojo now genuinely PASSES compile_stdlib.py (this session, continued)

A sibling agent's merged commit (`cecf087`, "Add scalar parameter support to
compiled async functions") widened `_async_quick_eligible` to allow
parameterized `async def`s in general — but re-running
`compile_module_to_c_cached` on `device_context.mojo` directly afterward
showed the SAME "function(s) wrapper, ... (async function(s), declared
`async def`)" refusal, confirming (as flagged above) that this file's real
gap was NOT that single gate — `wrapper` is a NESTED closure (inside a
struct method, not a top-level function or a method itself), a shape none
of `gen_module`'s existing async pre-passes (top-level free-function loop,
generator/async-METHOD loops) ever attempt at all, eligible or not.

Built and landed, all in `gimple_codegen.py`:
- A genuinely NEW `gen_module` pass discovering async closures nested one
  level inside a struct method, computing their captured free variables via
  a new `_compute_nested_closure_captures` helper (mirrors `_scan_for_
  closures`'s own free-variable computation, deliberately NOT shared code
  with it per this file's established generator/async duplication
  precedent), and compiling each via `_gen_cpp_async_unit` with the
  captures appended as ordinary trailing parameters. Registered in new
  `_supported_async_closures`/`_async_closure_api` dicts keyed by
  `(outer_ctx, inner_name)` — `outer_ctx` being `f"{struct}_{method}
  {overload_id}"`, matching `_all_closures`'s own convention — NOT bare
  name, since this file alone has FOUR distinct `wrapper` closures (one per
  `enqueue_cpu_function`/`enqueue_cpu_range` overload) that would otherwise
  collide (confirmed via a real "conflicting types for
  '_mojoasync_wrapper_start'" gcc error on the first cut, keyed by bare
  name — fixed by mangling each closure's C++ `base` symbol with its full
  outer context via a new `base_name_override` parameter).
- Void/`None`-returning compiled async functions (`_gen_cpp_async_unit`):
  previously a hard refusal ("every return must carry a scalar value") —
  `wrapper`'s entire body is a call with no return at all. Needed careful
  handling of the promise type's `return_void()` vs `return_value(T)`
  (mutually exclusive in a C++20 promise), the `_value()`/`Awaiter::
  await_resume()` no-`result`-field cases, and — the one genuinely
  surprising part, found via a hand-written repro trapping with
  `EXC_BREAKPOINT` at the very first instruction of the generated coroutine
  — the fact that a C++ function is only treated as a real coroutine by the
  compiler if `co_return`/`co_await`/`co_yield` appears SYNTACTICALLY
  somewhere in its body; a function with genuinely no `return` anywhere
  needed an explicit trailing `co_return;` appended, not just a
  `return_void()` promise method.
- A `CallExpr` case in `_cpp_stmt` (the coroutine-body sub-compiler) for a
  bare call to a captured/parameter function-type value (`func()`/
  `func(idx)`), via the same `mojo_fnptr_call_N()` runtime helper the
  ordinary GIMPLE path's `_lower_fnptr_call` already uses.
- `std.builtin.coroutine`'s `_set_noop_callback()` (a no-op, matching this
  codegen's honest synchronous-stub simplification) and `_take_handle()`
  (returns the same `MojoAsync*` handle, reinterpreted as the plain
  `int64_t` handle representation `mojo_coro_resume_generic`/
  `mojo_coro_destroy_generic` expect) as special-cased methods in
  `_lower_method_call`, and `_coro_resume_fn`/`_coro_destroy_fn` (used as
  bare function-pointer VALUES) mapped to those same two generic runtime
  functions via `BUILTIN_VALUE_MAP`.
- `external_call["AsyncRT_DeviceContext_enqueueHostFunction(Range)", ...]`
  wired up correctly: registered real function-pointer-typed signatures in
  `_LIBC_SIGS`/`_LIBC_DECLARED` (deferring to `mojo_async_runtime.h`'s own
  declaration instead of auto-generating a conflicting `void*`-typed one),
  and fixed a genuinely general bug this surfaced in `_new_temp` (the one
  central GIMPLE-temp-declaration spot in the whole file): a function-
  pointer ctype like `'void (*)(int64_t)'` was declared as `TYPE name;`
  (invalid C for a function pointer — corrupts the REST of the file's gcc
  parse) instead of the correct `TYPE (*name)(PARAMS);` — fixed via a new
  `_c_var_decl` helper.
- `build_stdlib_dylib.py`: a real, hand-verified regression found via the
  mandatory from-scratch dylib rebuild gate (skip count briefly went 1 → 2,
  `device_context.mojo` itself AND `std/runtime/asyncrt.mojo`) — neither
  `mojo_async_runtime.cpp` (providing `mojo_coro_resume_generic`/
  `mojo_coro_destroy_generic`) nor a C++ link driver were ever folded into
  the production stdlib dylib, so a module referencing them compiled clean
  but crashed at real dyld-load time ("symbol not found in flat
  namespace") — undetected by `compile_stdlib.py`'s own `gcc -fsyntax-only`
  check (no linker involved) or even by the dylib's OWN link step
  (`-undefined dynamic_lookup` tolerates it). Fixed by compiling
  `mojo_async_runtime.cpp` via g++ (CAS-cached, mirroring `mojo_runtime.o`'s
  own handling) and linking the production dylib via `g++` instead of
  plain `gcc`; also extended `runtime_dylib()` (the separate dylib
  `link_runtime=True` test builds link against) the same way, scoped
  carefully to avoid polluting `test_module_cache.py`'s exact CAS
  hit/miss-count assertions.

Verified end-to-end (compile+link+run, not compile-only) via
`test_async_void_return.py`: a void async function actually driven via
`asyncio.run(...)`, the EXACT `enqueue_cpu_function`-shaped repro (prints
`"ran-for-real"` then `"done"` — `func_impl` genuinely invoked through the
runtime stub's synchronous resume callback, not merely constructed), and
the `enqueue_cpu_range`-shaped repro (three independently-driven handles,
each calling the captured function with its own correct index).

## Current status — RESOLVED

`device_context.mojo` genuinely passes `compile_stdlib.py` now (confirmed:
`std_gpu_host_device_context.o` compiles clean via real `gcc -fgimple` and
the full from-scratch stdlib dylib rebuild is back to 0 skips, the first
time this project has reached 0). Its `EXPECTED_FAILURES` entry has been
removed from `compile_stdlib.py` (the stale-entry check would otherwise
fail the gate). Both closure-capture bugs this file was originally
blocked on, the async-eligibility gate, the nested-closure discovery gap,
void-return support, the coroutine-handle primitives, and the dylib
build/link gap are all fixed and verified real, running end to end.
