# HARD BUG: the self-hosting `getattr(self, x)`-dispatch-table heuristic mis-fires on ordinary stdlib code, emitting invalid C

## Status

Unfixed. Root-caused 2026-08-06 while investigating
`bugs/COMPILE_FAIL_importlib_util.md`. Fully traced to a specific
function and branch (see below) — this is NOT one of the previously
documented hard bugs, a genuinely new mechanism.

## Symptom

```
error: expected declaration specifiers or '...' before '*' token
error: '<name>__dispatch_t' has no member named '<Struct>___<dunder>__'
```
in a `typedef struct { ... } <name>__dispatch_t;` block that references
a class that was never declared to want any such dispatch table at the
Python source level at all.

## Minimal repro (concept — not yet hand-reduced to a standalone file)

Any class subclassing an external/opaque base type (so its own C
struct layout can't fully resolve `self`'s type) whose `__getattribute__`
(or any other method) does an ordinary, single dynamic attribute lookup:

```python
class Wrapper(SomeExternalOpaqueBase):
    def __getattribute__(self, attr):
        return getattr(self, attr)   # ordinary delegation, NOT a dispatch table

    def __delattr__(self, attr):
        ...
```

## Real-world instance

`Lib/importlib/util.py`'s `_LazyModule(types.ModuleType)`:
```python
class _LazyModule(types.ModuleType):
    def __getattribute__(self, attr):
        ...
        return getattr(self, attr)
    def __delattr__(self, attr):
        ...
```
Generated (`util.ci`):
```c
typedef struct {
  void (*LazyModule___delattr__)( *self, int attr);
  int64_t (*LazyModule___getattribute__)( *self, int attr);
} _lazymodule__dispatch_t;
...
static const _lazymodule__dispatch_t _lazymodule__dispatch = {
  .LazyModule___delattr__ = (void (*)( *self, int attr))_LazyModule___delattr__,
  ...
```
— both function-pointer fields are missing the TYPE token before
`*self` (should be e.g. `_LazyModule *self`), producing multiple GCC
parse errors that cascade into "has no member named ..." further down.

## Root cause

`gimple_codegen.py`'s dispatch-SOLVER machinery (class `DispatchTable`
+ the `DispatchPattern`/`_analyze_getattr_pattern`/`_plan_dispatch_tables`
family, ~lines 490-1062) exists specifically to compile THIS COMPILER'S
OWN self-hosted interpreter code (`myinterpreter.py`'s `Interpreter.
execute(self, node): return getattr(self, f'execute_{type(node).__name__}')
(node)` — a genuine `getattr`-as-vtable-dispatch pattern, confirmed by
the class's own docstring: "Interpreter's execute dispatch: maps
execute_* methods"). It recognizes `getattr(self, name_expr)` calls
inside a struct's own methods (`_analyze_getattr_pattern`,
gimple_codegen.py:905) and tries to figure out which methods could be
retrieved.

When `name_expr` matches the expected `f'{prefix}_{something}'` shape
(a `BinaryOp` with `op == '+'` and a string-literal left side), it
correctly narrows to methods sharing that prefix
(`_infer_getattr_targets`). But when it DOESN'T match that shape —
which is the case for `getattr(self, attr)` where `attr` is just a
plain parameter, not a string-concatenation expression — it falls into
this branch (gimple_codegen.py:936-943):
```python
else:
    # If we can't analyze the pattern, assume all methods might be called
    # This is conservative but correct
    if struct_name in self.struct_methods:
        for method_name, full_name in self.struct_methods[struct_name].items():
            if method_name not in ('__init__', 'execute'):
                pattern.add_callee(full_name)
```
The comment's claim ("conservative but correct") is true only in the
narrow self-hosting context this mechanism was built for (where every
struct with such a pattern really IS an `Interpreter`-style dispatch
class with uniformly-shaped `execute_*` methods). It is NOT correct in
general: `getattr(self, x)` for ordinary attribute delegation is one of
the most common Python idioms there is (`__getattribute__`,
`__getattr__` overrides, proxy/wrapper classes, `_LazyModule` here), and
has nothing to do with a dispatch table. The fallback unconditionally
registers EVERY method of the enclosing struct — including dunder
methods like `__delattr__`/`__getattribute__` themselves — as a
"dispatch table callee". `_plan_dispatch_tables` then builds a real
`DispatchTable` for this bogus pattern, inferring each callee's C
signature from `func_return_types`/`func_param_types`. For `_LazyModule`
(subclassing the opaque, unresolvable `types.ModuleType`), the `self`
parameter's C type resolves to an empty string, producing the malformed
`( *self, int attr)` function-pointer declarations GCC then rejects.

## What a real fix needs

The `else` branch's "assume all methods" fallback is the over-broad
piece. Options, roughly in order of how surgical they are:

1. **Narrowest**: only take the "assume all methods" fallback when
   `struct_name` is a struct KNOWN to belong to this compiler's own
   self-hosting source set (i.e., this file is being compiled as part
   of `make check-selfhost`/the self-hosting bootstrap, not an ordinary
   third-party/stdlib file) — there's likely already a way to detect
   this context (`self.module_name` matching the compiler's own known
   module names, or a dedicated self-host flag). Zero behavior change
   for the self-hosting case; the fallback simply never fires for
   ordinary code.
2. **Safer but broader**: keep the fallback for any struct, but require
   at least one call site elsewhere in the program to actually
   RETRIEVE-AND-CALL the getattr result in the same expression/statement
   (`getattr(self, x)(...)`, the real dispatch-table USAGE shape) rather
   than firing on a bare `return getattr(self, attr)` (just returning
   the looked-up value, not calling it) — `_LazyModule.__getattribute__`
   does the latter, not the former; this distinction alone might be
   enough to exclude this whole class of false positive without needing
   to detect self-hosting context at all.
3. Regardless of which gating is chosen, `_plan_dispatch_tables`
   (or `DispatchTable.add_method`) should also defensively skip/warn
   rather than emit malformed C when a callee's inferred "self" type
   resolves empty — a structural safety net independent of fixing the
   over-eager pattern detection, since a similar unresolvable-self-type
   situation could arise from some other future caller of this same
   machinery.

## Risk

Moderate. This machinery exists specifically to make `make
check-selfhost` work (compiling `myinterpreter.py`'s own dispatch-table
idiom), so ANY change here must be verified against that gate FIRST and
foremost — a regression would silently reappear as a self-host failure,
not necessarily an obvious "dispatch table" error. Option 1 above (gate
on self-hosting context) is the lowest-risk of the three since it's
purely narrowing an existing behavior to the cases it actually still
needs to cover; still requires the full 5-step quality gate given how
central self-hosting is to this codebase's development loop.

## Not fixed here

Out of scope for this investigation's time budget — this was reached
while triaging `bugs/COMPILE_FAIL_importlib_util.md` (one of ~46 files
assigned this session) and a careful fix needs dedicated verification
against `make check-selfhost` specifically, which this session's task
list treats as a separate, always-required gate rather than something
to iterate against quickly mid-triage.
