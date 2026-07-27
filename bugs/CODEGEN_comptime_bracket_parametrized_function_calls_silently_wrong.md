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

## Still open — NOT fixed by the above

The fix above only covers a bracket call to a function *defined at module
top level*. Confirmed still broken, same silent-`0` failure mode: a
`@parameter`-decorated **nested** `def f[lhs: Int](rhs): ...` (defined
inside another function's body) — the exact shape `test_asyncrt.mojo`'s
`test_asyncrt_add[lhs: Int](rhs: Int)` and `test_tracing.mojo`'s
`test_tracing_add[enabled: Bool, lhs: Int](rhs: Int)` actually use. Root
cause: `gen_module`'s "Local generic free functions" registration scan
only walks top-level `stmts` looking for `isinstance(s, FunctionDef)` —
nested defs live inside an enclosing `FunctionDef.body`, so they're never
registered into `_imported_generics` and never stripped from being
(mis-)compiled as an ordinary nested closure. Confirmed via a fresh repro
(`@parameter def nested_add[lhs: Int](rhs: Int)` inside `main()`) — still
folds to `0`.

Additionally, `test_asyncrt_add`/`test_tracing_add` are themselves `async
def`, not just nested — even with nested-comptime-registration fixed,
these two files are STILL refused today for a separate, legitimate reason:
`_async_quick_eligible` rejects any parameterized `async def` outright
(confirmed directly: after this fix, `test_asyncrt.mojo` now fails with
"function(s) ... test_asyncrt_add, test_asyncrt_add_two_of_them (async
function(s), declared `async def`)" — the ordinary "no compiled
async/generator support for this shape" refusal, not the comptime bug).
So getting `test_asyncrt.mojo`/`test_tracing.mojo` to pass needs BOTH (a)
extending local-generic registration to recurse into nested function
bodies, in a way that's compatible with `@parameter`/closure-capture
semantics for nested defs, AND (b) the previously-scoped "parametric
`@parameter async def` support" / `_async_quick_eligible` widening work —
neither attempted yet.

## Current status

Free top-level functions: FIXED and verified (see
`test_comptime_bracket_params.py`). `device_context.mojo`'s Repro 1 (a
comptime FUNCTION-TYPE bracket parameter on a struct METHOD, called from a
nested closure) is a structurally different call shape (`obj.method[Func]
(...)`, routed through `_lower_call`'s separate "Subscripted method call"
branch, not the local-generics path this fix touches) and is confirmed
STILL broken — see `bugs/CODEGEN_device_context_captured_function_
parameter_closures_broken.md`, unchanged by this fix.

All four Group 1 files (`test/runtime/test_asyncrt.mojo`,
`test_locks.mojo`, `test_raising_asyncrt.mojo`, `test_tracing.mojo`)
remain honest whole-module refusals in `compile_stdlib.py`'s
`EXPECTED_FAILURES` — `test_asyncrt.mojo`/`test_tracing.mojo`'s entries
have been updated to describe their real current blocker (nested/async
comptime-parametrized `async def`s, not the general value-binding bug,
which is now fixed for the top-level case). The other two
(`test_locks.mojo`, `test_raising_asyncrt.mojo`) are blocked by a
different, separately-documented reason (no `create_task`/`Task`/
`TaskGroup`/`RaisingTask` codegen support exists at all yet — see their
own `EXPECTED_FAILURES` entries in compile_stdlib.py).
