# CODEGEN_generator_function: Lib/test/libregrtest/save_env.py

## Status (updated 2026-08-26 -- re-verified at current master `e60b9cd`, unchanged)

Independent fresh re-verify, this session, against current master
`e60b9cd` (122 commits past the `a913ab8` branch point the entry
immediately below was checked against). Ran
`compile_to_gimple_with_cpp(do_imports=False)` directly: byte-for-byte
identical `RuntimeError` — `resource_info` refused on `getattr(obj,
name) with a non-static attribute name is not supported in a compiled
generator/coroutine body`. Gap 3 (runtime name->member reflection) is
unaffected by anything in the 122 intervening commits. Still
structural; untouched.

## Status (updated 2026-08-26 -- re-verified, unchanged)

Fresh re-verify against this worktree (branched from master `a913ab8`).
Ran a direct isolated `compile_to_gimple_with_cpp(..., do_imports=
False)` call (avoids the whole-program build's large transitive
`test.libregrtest`/`compression` import graph, same rationale the
2026-08-25 entry used, but completes cleanly rather than timing out):
byte-for-byte identical refusal — `resource_info` refused on
`getattr(obj, name) with a non-static attribute name is not supported
in a compiled generator/coroutine body (no runtime attribute-reflection
table exists in this codegen)`. Gap 3 (runtime name->member reflection)
is unaffected by anything landed since the last pass. Still structural;
untouched.

## Status (updated 2026-08-25 -- re-verified, unchanged)

Re-ran `python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/
test/libregrtest/save_env.py` fresh against current master (past the
struct-method cross-call scalar contract "Pass 1.3e",
generator-consumption-ordering fixed-point retry + defaults-aware arg
padding, `**kwargs`-forward slot-alignment fix, and coroutine-body
`int()`/`float()` builtin support landed since the 2026-08-24 entry
below). The whole-program build didn't finish within this session's
safety-wrapped time budget (large transitive import graph via
`test.libregrtest`/`compression`/etc.), but the per-function debug log
shows the identical refusal byte-for-byte before the watcher killed it:
`generator method saved_test_environment.'resource_info' not eligible
for C++ coroutine path, falling back to honest refusal: getattr(obj,
name) with a non-static attribute name is not supported in a compiled
generator/coroutine body (no runtime attribute-reflection table exists
in this codegen)`. Gap 3 (the only remaining gap) is unaffected by any
of the intervening fixes — none of them add runtime name-based
attribute reflection. Still structural; untouched.

## Status (updated 2026-08-24 -- re-verified, unchanged)

Re-checked this session while triaging the C3 cluster. Gap 3 (`getattr(self, get_name)` with a runtime-computed name, needing real compile-time name->member reflection) is unaffected by this session's two landed fixes (stdin/stdout/stderr field-name escaping; more char* string methods in coroutine bodies). Still structural; untouched.


## Status (updated 2026-08-23 — STILL-OPEN (unchanged blocker))

Re-ran the repro: identical honest refusal — `resource_info` refused on
`getattr(obj, name)` with a non-static attribute name (no runtime
attribute-reflection table). This session confirmed gaps 1 and 2 of the
2026-08-11 list remain fixed, and the transitively-imported
test/support/__init__.py is no longer a factor either way. Gap 3 stays
genuinely structural (needs a real compile-time name->member reflection
table). Gate verification (2026-08-23): `test_gimple.py` 250 passed / 0 failed;
`test_module_cache.py` 76 / 0; `make check-selfhost` clean; from-scratch
stdlib dylib rebuild EXIT=0 with **0** `skip <module>:` lines — matching
the pre-change baseline of exactly 0 skips.

## Status (updated 2026-08-11 — 2 of the 3 stacked gaps below FIXED; 1 confirmed genuinely structural)

Re-verified this doc's own 3-gap list (from the 2026-08-10 note directly
below) with a fresh isolated build. Fixed 2 of the 3 for real:

1. **`for name in self.resources:` (a `MojoList *`-typed struct FIELD,
   not a local/param) inside a coroutine body** — FIXED. `_cpp_for_stmt`
   only special-cased a bare identifier iterable typed `int64_t`/
   `MojoList *`; a `self.<field>` `MemberExpr` iterable fell through to
   the generic C++ range-for fallback (`for (auto x : self->field)`),
   invalid for a raw pointer with no ADL `begin`/`end`. Extended that
   same indexed-loop lowering to a `self.<field>` iterable whenever
   `struct_field_types` says the field isn't one of the 4 known scalars
   (i.e. it's pointer-shaped, per this codegen's own struct-field-boxing
   convention). Also fixed the accompanying element-type gap this
   exposed: `resources` is a CLASS-BODY tuple-of-strings attribute
   (`resources = ('sys.argv', 'cwd', ...)`), and the class-body-attribute
   scan (`gen_module`, ~line 30371) registered the field's own pointer
   type (`MojoList *`) but never its ELEMENT type — so the new for-loop
   defaulted `name` to `int64_t`/`mojo_list_get_int`, wrong for a string
   element (`name.replace(...)` below then failed with "request for
   member 'replace' in a non-class int64_t"). Added the matching
   `_field_elem_types` population at the same class-body-attribute site
   (reusing the existing `_infer_list_elem_type` helper, the same one
   an ordinary `self.x = [...]` instance assignment already populates
   this map with) — `_cpp_for_stmt` now consults it to pick `char
   */mojo_list_get_str` instead of the `int64_t`/`mojo_list_get_int`
   default when the element type is known-`char *`.
2. **`get_name = 'get_' + method_suffix`, where `method_suffix = name.
   replace('.', '_')`** — FIXED, two compounding gaps: (a) `_cpp_expr`'s
   `CallExpr`/`MemberExpr` case had no `.replace(old, new)` case at all
   for a `char *`-typed object (a real string method call, not a module/
   struct-method call) — added, routing through the same
   `_char_replace_impl` runtime helper the ordinary GIMPLE path's own
   `str.replace(...)` lowering already uses (already declared via the
   wholesale `#include <mojo_runtime.h>` every generated `.cpp` file
   has). (b) `_infer_simple_expr_ctype` (used to pick a first-assigned
   local's declared C++ type) had no case for `.replace(...)` either, so
   `method_suffix` defaulted to `int64_t` — which then made the
   subsequent `'get_' + method_suffix` string-concat detection
   (`_is_str_operand`, keyed on the SAME type map) miss, emitting a raw,
   invalid C++ `+` instead of `mojo_str_cat`. Added a matching `char *`
   case there too.
3. **`getattr(self, get_name)` (`get_name` a RUNTIME-computed string)**
   — NOT fixed, confirmed genuinely structural on renewed investigation
   (not just re-asserted from the prior note): this codegen's own
   `mojo_getattr` runtime helper (`runtime/mojo_runtime.c`) is an
   honest always-return-0 stub — there is no runtime name→member
   reflection table anywhere in this codegen; every struct field/method
   access is resolved to a fixed compile-time offset/symbol, never
   dispatched by a runtime string value. Correctly supporting this
   specific call would need real dynamic reflection (a name→offset/
   symbol table built at compile time, consulted at runtime) — a new
   feature, not a narrow fix. Converted the previous UN-diagnosed raw
   miscompile (`'getattr' was not declared in this scope`, from falling
   through to the generic bare-name-call fallback) into an honest
   `_UnsupportedGeneratorShape` refusal instead, matching this cluster's
   own established convention (e.g. the tuple-yield fix below) of
   turning a raw miscompile into a clean, diagnosed fallback to
   interpreting the module from source — a real improvement even though
   it doesn't make the file itself compile.

**save_env.py still does not build** — blocked solely by gap 3 now,
confirmed via a fresh isolated compile (`resource_info` is refused with
the honest "generator function(s) ... falling back to interpreting this
module from source instead" message; no other gap remains in this
function).

### Gate verification (2026-08-11)

`test_gimple.py`: 247 passed, 0 failed. `test_module_cache.py`: 76
passed, 0 failed. `make check-selfhost`: clean. From-scratch stdlib
dylib rebuild (`build_stdlib_dylib.build_stdlib(jobs=18)`): 0 `skip
<module>:` lines. `compile_stdlib.py`: 664/664 passed, 0 unexpected.

## Status (updated 2026-08-10 — tuple-valued yield now FIXED; other, pre-existing gaps now block)

Implemented real tuple-valued-`yield` support this session: `yield a,
b, ...` boxes the tuple's elements into a real runtime `MojoList *` at
the yield site (`_cpp_yield_tuple`, `gimple_codegen.py`) — each
element's own natural type is inferred independently (so `resource_
info`'s `getattr(self, get_name)` elements, which this codegen can't
type further, get the same int64_t-default-for-unknown convention the
scalar-yield case already used) — unboxed on the consumer side via
`_gen_for_generator_iter`'s new tuple-target handling. Confirmed via an
isolated compile: `resource_info`'s `yield name, getattr(self,
get_name), getattr(self, restore_name)` (line 326) is no longer
refused at the Python-level eligibility gate, and the `_mg_tup_1`
boxing text itself (3 `mojo_list_append_int` calls + `co_yield`) is
syntactically valid C++.

**save_env.py still does not build**, blocked by THREE separate,
pre-existing gaps earlier/later in the SAME function body (confirmed via
direct g++ syntax-check of the isolated compile), all unrelated to
tuple-yield:
1. `for name in self.resources:` — a plain `for` loop over a struct
   FIELD (`self.<field>`) typed `MojoList *`, inside a coroutine body.
   `_cpp_for_stmt`'s range-for fallback (`for (auto name : ...)`)
   doesn't work for a raw `MojoList *` (no ADL `begin`/`end`) — g++:
   `'begin'/'end' was not declared in this scope`. (The already-existing
   fix for this exact shape, `_gen_for_iter`'s handling of a bare
   IdentExpr local, doesn't cover a `self.field` MemberExpr iterable.)
2. `get_name = 'get_' + method_suffix` — string concatenation lowers to
   a `const char *`-returning helper, assigned into a `char *`-declared
   local — g++: "invalid conversion from 'const char*' to 'char*'".
3. `getattr(self, get_name)` — the coroutine-body expression lowering
   (`_cpp_expr`) has no case for `getattr(...)` at all; it falls through
   to a generic "emit the call verbatim" path that references a
   nonexistent C++ function named `getattr` — g++: "'getattr' was not
   declared in this scope".

None of these are the promise/ABI-representation gap this session's fix
targets — they're independent, narrower `_cpp_stmt`/`_cpp_expr` gaps.
Not attempted here. Doc kept open (not deleted).

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
