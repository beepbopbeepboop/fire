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

## Current status

All four Group 1 files (`test/runtime/test_asyncrt.mojo`,
`test_locks.mojo`, `test_raising_asyncrt.mojo`, `test_tracing.mojo`)
remain honest whole-module refusals in `compile_stdlib.py`'s
`EXPECTED_FAILURES`. This file is the justification for two of them
(`test_asyncrt.mojo`, `test_tracing.mojo`) — the other two
(`test_locks.mojo`, `test_raising_asyncrt.mojo`) are blocked by a
different, separately-documented reason (no `create_task`/`Task`/
`TaskGroup`/`RaisingTask` codegen support exists at all yet — see their
own `EXPECTED_FAILURES` entries in compile_stdlib.py). None of
`create_task`/`Task`/`TaskGroup`/`RaisingTask`/`Trace` context managers
have been attempted yet given this comptime-parameter prerequisite is
itself broken for the two files that need it.
