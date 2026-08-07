# HARD BUG: `self.field = param` with an unannotated, no-default `__init__` parameter always types the field `int64_t`, even for real string/list/etc. call-site arguments

## Status

Unfixed. Root-caused 2026-08-06 while investigating
bugs/COMPILE_FAIL_importlib__bootstrap.md (a tangent from that
investigation, not the compile error itself — this is a SEPARATE, more
severe finding). Not attempted — this is a genuinely large fix (extending
an existing cross-call-argument-inference mechanism to a new call shape)
and this exact area of the codebase (call-argument/parameter type
inference) has already produced two real regressions elsewhere this
session from confident-looking changes — see bugs/COMPILE_FAIL_
collections___init__.md's `_tuplegetter` investigation.

## Why this matters more than a typical bug

Unannotated `__init__` parameters (`def __init__(self, name): self.name
= name`, with NO type annotation and NO default value) are the
OVERWHELMINGLY common style throughout real Python — including the vast
majority of CPython's own stdlib, which is exactly the corpus this
compiler targets (`compile_stdlib.py`'s 664 files). This bug means any
such field is SILENTLY given the wrong C type (`int64_t` instead of the
real `char *`/`MojoList *`/etc.) — not a compile failure, a silent
WRONG-VALUE bug. `compile_stdlib.py`'s 664/664 pass rate only checks
"does it compile and link", never "does the compiled program compute the
right values" — so this has been invisibly present and unmeasured
throughout this entire multi-session bug-fixing effort. Given how common
the triggering shape is, it is very likely responsible for a
meaningful fraction of "compiles clean but the compiled binary's actual
behavior is subtly wrong" gaps nobody has flagged yet (there is no
current test harness that would catch this — see "How this evaded
detection" below).

## Minimal repro

```python
class Widget:
    def __init__(self, label):
        self.label = label

def main():
    w = Widget("hello")
    print(w.label)          # prints a raw pointer value as a decimal
                             # integer instead of "hello"
    print(len(w.label))     # nonsense length (interprets the pointer's
                             # bit pattern as a fake int64_t "length")

main()
```

Confirmed: adding an explicit annotation (`def __init__(self, label:
str):`) makes it print correctly ("hello") — annotated fields are NOT
affected, only unannotated ones.

Confirmed via the interpreter (`mojo.py run`, the SEPARATE, correct
implementation): prints "hello" correctly — this is exclusively a
compiled-path (`gimple_codegen.py`) bug.

## Root cause

`gen_module`'s struct-field-type-collection pass (~gimple_codegen.py:
26708-26854, comment "Always scan ALL methods for self.x = ... to build
complete field list") has a nested helper `_collect_self_assigns` which,
for `self.field = <IdentExpr param>`, does:

```python
if isinstance(v, IdentExpr):
    ft = param_types.get(v.name, 'int64_t')
```

`param_types` (built a few lines above, per-method, as `pm`) is populated
PURELY from the `__init__` method's OWN parameter list, with NO
cross-reference to how the class is actually CONSTRUCTED elsewhere in the
program:

```python
if ptype:
    pm[pname] = self._resolve_type(ptype)          # explicit annotation
elif pname in _defaults:
    ...                                             # inferred from a `=default` literal
else:
    pm[pname] = 'int64_t'                            # <-- unconditional fallback
```

An unannotated, no-default parameter ALWAYS falls to the `int64_t`
default at that last line — regardless of what real callers pass
(`Widget("hello")` — a string literal, right there in the same file).

## Why this doesn't affect free functions the same way

This codebase ALREADY has a general mechanism for exactly this class of
problem — the "cross-call scalar contract" pass (gimple_codegen.py, Pass
1.3d, ~line 27630-27686): it scans every call site across the whole
program (`_caller_bodies`, including top-level code) for calls to
FREE FUNCTIONS (`_free_params.get(callee)` — keyed by free-function name)
whose argument at a given position is a scalar (`double`/`char *`), and
if EVERY call site agrees, it retroactively refines that unannotated
parameter's inferred type (`self._inferred_param_types`).

This mechanism is scoped to `call.func` being an `IdentExpr` whose name
is a FREE FUNCTION (`_free_params`) — a constructor call like
`Widget("hello")` has `call.func.name == 'Widget'` (the class name), which
is never in `_free_params` (that dict is populated from free
`FunctionDef`s only), so constructor calls are invisible to this pass
entirely. The existing mechanism was simply never extended to cover
`ClassName(...)` call sites feeding `__init__`'s own params, which is
what `_collect_self_assigns` would need in order to give unannotated
constructor parameters the same treatment.

## How this evaded detection until now

- `test_gimple.py`/`test_module_cache.py`: don't happen to cover this
  exact shape with a runtime-value assertion (a compile-only or a
  differently-shaped test wouldn't catch it).
- `make check-selfhost`: only checks that mojo.py compiling itself
  produces a working binary — this compiler's OWN source (gimple_codegen.
  py, mojo_compiler.py, etc.) may simply not have many `self.field =
  unannotated_param` shapes where the WRONG type silently still compiles
  without symptom (a GIMPLE type mismatch would at least be a hard
  compile error, same class as the "non-trivial conversion"/"declared
  void" errors already documented elsewhere in this codebase as
  originating from exactly this kind of struct-field mistyping — see the
  comment this investigation found at gimple_codegen.py:26769-26772,
  which references a DIFFERENT but RELATED instance found via importlib/
  resources/readers.py's `ZipReader.__init__`, fixed only for the
  "chained string-returning method call" RHS shape, not this "plain
  identifier referencing an unannotated param" shape).
- `compile_stdlib.py -j8`'s 664/664: only checks compile+link success,
  never runs the resulting binaries or asserts on their output. A field
  silently boxed as `int64_t` instead of `char *` very often still
  compiles and links CLEANLY (a pointer bit-reinterpreted as an int64 is
  frequently a valid, if semantically wrong, C value) — it just computes
  the wrong thing at runtime, which this gate cannot see.

## What a real fix needs

1. Extend the cross-call scalar-contract pass (or add a parallel, similar
   pass) to ALSO scan constructor call sites (`ClassName(...)` where
   `ClassName` is a known `StructDef` with an `__init__`), collecting
   observed argument types per `__init__` parameter position the same
   way `_free_params`/`_scalar_obs` already does for free functions.
2. Thread the result into `_collect_self_assigns`'s `param_types` lookup
   (or populate `self._inferred_param_types` under the SAME struct/
   `__init__`-scoped key `_collect_self_assigns` could then consult) so
   `self.field = unannotated_param` picks up the inferred real type
   instead of unconditionally defaulting to `int64_t`.
3. Given the class can ALSO be instantiated with NO literal-typed
   arguments anywhere visible (e.g. only ever constructed with an
   already-`int64_t`-typed variable, or constructed via `**kwargs`
   unpacking, or subclassed with the subclass never calling `Widget(...)`
   directly) — the fallback for an unresolvable case must remain the
   current `int64_t` default (matching today's behavior when NO call-site
   evidence is unanimous), not a hard requirement — this is a strict
   ADDITIVE improvement, not a replacement of the existing (correct,
   necessary) default-value fallback.
4. Verification MUST include actually RUNNING a compiled binary and
   checking output (not just compile success) — this exact category of
   bug is invisible to `compile_stdlib.py`'s existing pass/fail gate, as
   established above. The minimal repro's `print(w.label)` producing
   "hello" (not a raw number) is the concrete acceptance check.
5. Given how pervasive the triggering shape is (this is the DEFAULT style
   for the entire Python ecosystem, not an edge case), a real fix here
   could plausibly fix — or at minimum meaningfully improve — MANY of the
   still-open COMPILE_FAIL bugs whose root cause is a struct-field type
   mismatch ("non-trivial conversion in ...", "assignment to X from Y
   makes ... without a cast", "declared void" families) without those
   needing individual investigation, IF their root cause turns out to be
   this same gap. Worth checking a sample of remaining open bugs against
   this hypothesis before assuming each needs a bespoke fix.

### Risk

Same class of risk as bugs/hard/CODEGEN_args_kwargs_signature_assumed_
forwarding_only.md and the `_tuplegetter` investigation: this touches
shared call-site/parameter type-inference machinery with a demonstrated
history of broad, hard-to-predict regressions in `compile_stdlib.py`
from seemingly-narrow changes THIS SESSION. Any fix attempt MUST run the
full 5-part quality gate (test_gimple.py, test_module_cache.py, make
check-selfhost, from-scratch stdlib dylib rebuild, compile_stdlib.py -j8)
— and, per point 4 above, should ALSO spot-check a few compiled stdlib
binaries' actual runtime output before/after, since the existing gate
cannot detect this bug's OWN symptom (wrong values, not failed compiles).

## Real-world instances confirmed 2026-08-06

- `Lib/importlib/resources/readers.py`'s `NamespaceReader.__init__(self,
  namespace_path)`: unannotated `namespace_path` defaults to `int64_t`;
  the real call site always passes a genuine path-like/iterable object.
  The body does `map(self._resolve, namespace_path)` — iterating
  `namespace_path` as a container — and the generated GIMPLE tries to
  feed the `int64_t`-typed param through `map`'s iteration/spread
  lowering, producing `error: non-trivial conversion in 'mem_ref'` at
  the `self.path = MultiplexedPath(*filter(bool, map(self._resolve,
  namespace_path)))` line. Confirmed by inspecting the generated `.ci`:
  `void NamespaceReader___init__ (NamespaceReader *, int64_t)` (the
  param declared `int64_t`) and, a few lines into the body, `str(
  namespace_path)` lowered as `mojo_str_from_int(namespace_path)` —
  the tell-tale "real value is a string/container, field typed
  int64_t" signature this doc's own minimal repro also produces. See
  `bugs/COMPILE_FAIL_importlib_resources_readers.md` for the full
  build log this was found in. Not fixed here, for the same reason
  nothing in this doc has been fixed — this is exactly the shared,
  high-risk machinery this doc already flags.
