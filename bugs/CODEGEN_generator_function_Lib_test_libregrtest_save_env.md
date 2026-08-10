# CODEGEN_generator_function: Lib/test/libregrtest/save_env.py

## Status (re-verified 2026-08-09, unchanged)

Re-ran `python3 mojo.py build .../Lib/test/libregrtest/save_env.py` against
current master (140 commits past the 2026-08-07 fix below, none of which
touch tuple-yield handling). Reproduces identically: clean, honest refusal —

```
Error building: cannot compile module: function(s) resource_info
(generator function(s), contain a `yield`/`yield from`) — ... falling back
to interpreting this module from source instead
```

No new regression, no new fix landed for actual tuple-value ABI support.
Still the same structural gap (tuple-valued `yield` has no real codegen
support — see the family-wide note in this cluster's task doc). Nothing
further to do here.

## Status (updated 2026-08-07 — malformed-C++ tuple-yield now an honest refusal, not a fix for the file itself)

Re-verified the 2026-08-06 root-cause trace below by dumping the actual
generated `.cpp` directly (`compile_to_gimple_with_cpp(..., do_imports=
False)`): confirmed `_cpp_stmt`'s `YieldExpr` case emits the 3-tuple
yield as a raw braced-init-list, `co_yield {name, getattr(self,
get_name), getattr(self, restore_name)};`, against a promise whose
`yield_value(int64_t v)` only accepts a SCALAR — genuinely invalid,
mismatched C++ (not merely a name-resolution problem as the "expected
')' before ',' token"/"'name' undeclared" GCC messages made it look;
GCC's specific wording is itself an artifact of how badly a raw `{...}`
list confuses its parser inside a `co_yield` expression, plus the
usual `#line`-drift misattribution this cluster has hit elsewhere this
session — see `bugs/CODEGEN_generator_function_Lib_glob.md`'s "How this
was diagnosed" section for the general mechanism).

**Real root cause, precisely**: `_generator_yield_ctype`
(gimple_codegen.py:2593) correctly calls `_infer_simple_expr_ctype` to
type each yielded value — which correctly has NO case for `TupleExpr`
and returns `None` ("don't know, refuse this shape", per its own
docstring). But `_generator_yield_ctype`'s caller-facing YieldExpr
handling then OVERRIDES that `None` signal with a blanket
`t = 'int64_t'  # default when type can't be inferred` fallback,
silently discarding the "refuse" signal for THIS shape and letting an
unsupported tuple-yield generator sail through eligibility all the way
to `_cpp_stmt` body emission — where the SEPARATE emission code path
(which never consults `_generator_yield_ctype`'s result at all) just
emits the raw tuple literal regardless, producing the mismatched C++
above.

**Fixed** (narrow, targeted at this exact shape only): added an early
`if isinstance(n.value, TupleExpr): return None` check in
`_generator_yield_ctype`'s `YieldExpr` branch, BEFORE the generic
int64_t-default fallback — so a real multi-element tuple yield now
correctly propagates `None` all the way to `_gen_cpp_generator_unit`'s
existing `if value_ctype is None: raise _UnsupportedGeneratorShape(...)`
check, which is the SAME graceful "not eligible for C++ coroutine path"
fallback every other unsupported shape in this file already gets.
Deliberately scoped to ONLY the tuple-yield case (not a change to the
general "unknown type defaults to int64_t" fallback, which many other,
currently-working generator shapes may depend on) — low regression
risk, since any generator hitting this new check was ALREADY guaranteed
to fail (with a confusing, misattributed GCC error) before this fix;
the only possible behavior change is failing more cleanly/honestly.

**Verified**: re-running the isolated compile now raises
`_UnsupportedGeneratorShape`/escalates to the SAME honest
`RuntimeError: cannot compile module: function(s) resource_info
(generator function(s), ...) — ... falling back to interpreting this
module from source instead` message this project's other refused-
generator files already show (e.g. `Lib/dis.py`'s `_get_instructions_
bytes`), instead of the previous malformed/misattributed GCC syntax
error.

**Not fixed (and NOT the same thing as making save_env.py build)**:
`save_env.py` still does not successfully build — tuple-valued yields
have no real support in this codegen at all (the promise/ABI layer only
carries a single scalar value; making `co_yield name, get, restore`
actually WORK would need real tuple/struct-typed yield-value support
threaded through the promise type, the `_value`/`_resume` C ABI, and
every `for a, b, c in gen():`-unpacking consumer — a genuine new
feature, not a narrow fix, matching this cluster's already-deferred
#141/#142/#143/#147 shape). This fix only converts a previously-
confusing miscompile into an honest, correctly-diagnosed refusal for
this one construct.

### Gate verification

See the shared end-of-session gate run covering every fix made in this
session (test_gimple.py/test_module_cache.py/check-selfhost/stdlib
dylib rebuild/compile_stdlib.py -j8).

## Status (updated 2026-08-06, superseded above — same root shape, now precisely diagnosed and given an honest-refusal fix)

**STILL FAILING**, but the specific error has changed since 2026-07-30
(that `'begin' was not declared` shape — dyld.py's bullet-3 iteration
gap — no longer reproduces for this file). Current failure is a real
SYNTAX error in the generated `.cpp` itself (not just an unresolved
name):

```
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/save_env.py:327:16: error: expected ')' before ',' token
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/save_env.py:339:4: error: 'name' undeclared (first use in this function); did you mean 'rename'?
/Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/save_env.py:339:15: error: 'restore' undeclared (first use in this function)
```

**Root cause (traced to source, new gap — narrow, single instance,
not yet a hard-bug doc):**
```python
def resource_info(self):
    for name in self.resources:
        method_suffix = name.replace('.', '_')
        get_name = 'get_' + method_suffix
        restore_name = 'restore_' + method_suffix
        yield name, getattr(self, get_name), getattr(self, restore_name)   # line 326
```
`yield name, getattr(self, get_name), getattr(self, restore_name)` — a
3-element tuple yield where two of the three elements are `getattr(self,
<dynamic-name-string>)` calls (each resolving to a BOUND METHOD at
runtime). The emitted C++ for this specific tuple-yield shape has a real
syntax error (`error: expected ')' before ',' token` — not a name-
resolution problem, an actually malformed expression/statement), which
then cascades: `__enter__`'s `for name, get, restore in
self.resource_info():` (line 339) unpacking the (never-compiled)
generator's output reports `name`/`restore` as undeclared, since the
tuple-yield's own emission never got far enough to declare them.

Not folded into a hard-bug doc (single instance so far in this cluster
— the closest prior finding, dyld.py's bullet-1 "untyped params default
wrong", is a different mechanism: this is about a MULTI-ELEMENT TUPLE
yield containing `getattr(...)` call results specifically, producing
outright malformed C++ syntax rather than a type mismatch). Flagged for
whoever next hits a tuple-yield containing `getattr()`/similarly dynamic
sub-expressions to confirm and fold into a dedicated hard-bug doc.

Not fixed here — inside the coroutine `.cpp` tuple-yield emission path,
warranting its own dedicated verification pass per this task's
guidance.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/test/libregrtest/save_env.py
