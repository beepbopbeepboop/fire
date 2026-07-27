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

## Current status

`device_context.mojo` remains an honest whole-module refusal
(`compile_stdlib.py`'s `EXPECTED_FAILURES`, with this file as the
justification). The async-specific plumbing that WOULD be needed once the
capture bugs are fixed (`_take_handle()`/eligibility widening/
`AsyncRT_DeviceContext_enqueueHostFunction(Range)` synchronous stubs) is
already built and verified inert/safe in `runtime/mojo_async_runtime.h`/
`.cpp` (generic `mojo_coro_resume_generic`/`mojo_coro_destroy_generic` +
the two stub externs), ready to be wired up once a future pass fixes
Repro 1/Repro 2 above.
