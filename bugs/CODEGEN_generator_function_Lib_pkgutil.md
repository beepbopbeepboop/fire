# CODEGEN_generator_function: Lib/pkgutil.py

## Status (updated 2026-08-09, re-verified — TWO MORE generators now also refused, both tuple-valued yield)

Re-verified against current master (`c79a013`) via a real
`python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/pkgutil.py`.
`walk_packages`'s refusal reason is unchanged from the 2026-08-07 note
below (still exactly the `onerror(info.name)` "argument must be a
scalar ... expression" message) — that analysis stands.

**New since 2026-08-07: two more of this file's own generators now
also refuse**, both for the well-known tuple-valued-yield structural
gap (`_infer_generator_yield_ctype`'s `TupleExpr` handling,
`gimple_codegen.py:2699-2724`, which deliberately refuses rather than
emit broken C++ — see e.g. `CODEGEN_generator_function_Lib_ipaddress.md`
for the same pattern elsewhere in this cluster):

```
[gimple_codegen] generator '_iter_file_finder_modules' not eligible for
  C++ coroutine path, falling back to honest refusal:
  _iter_file_finder_modules: every `yield` must carry a value, and all
  values must agree on one scalar type (int64_t/double/_Bool)
[gimple_codegen] generator 'iter_zipimport_modules' not eligible for
  C++ coroutine path, falling back to honest refusal:
  iter_zipimport_modules: every `yield` must carry a value, and all
  values must agree on one scalar type (int64_t/double/_Bool)
```

Confirmed by reading the source: `_iter_file_finder_modules`
(pkgutil.py:128) does `yield prefix + modname, ispkg` (line 166) — a
real 2-element tuple yield (`str, bool`). `iter_zipimport_modules`
(pkgutil.py:176) does `yield prefix + fn[0], True` (line 191) and
`yield prefix + modname, False` (line 202) — same 2-element
tuple-yield shape at two call sites in the same generator. Both are
new, independent instances of the tuple-yield structural gap, distinct
from `walk_packages`'s captured-callback-argument gap analyzed below.
The overall `mojo.py build` failure now reports all three generator
names together (`_iter_file_finder_modules, iter_zipimport_modules,
walk_packages`) since `gen_module` collects every refused generator
in the module before raising once.

Net effect: even if `walk_packages`'s narrower callback-argument gap
were fixed, this file would still fail to build — two more of its own
top-level generators are independently blocked by the tuple-yield
structural gap. Not attempted here (matches this task's "structural,
do not force a fix" guidance). Doc kept, not deleted.

## Status (updated 2026-08-07, investigated further, correctly NOT fixed)

Re-verified against current master: `walk_packages`'s refusal reason
is unchanged, still exactly the `onerror(info.name)` "argument must be
a scalar ... expression" message from the 2026-08-06 note below.
Investigated to a conclusion this time (the previous note left it as
an open question "for whoever next hits this shape"):

**Root cause, precisely:** `info` is the loop variable of `for info in
iter_modules(path, prefix): yield info` — a `ModuleInfo` namedtuple
instance, i.e. a struct-typed value. `info.name` is a `MemberExpr` on
a NON-`self` local. `_infer_simple_expr_ctype` (the coroutine body's
scalar-type estimator used at this captured-callback call site) only
has a case for `self.<field>` MemberExpr reads (generator METHODS
only) — a `MemberExpr` on any OTHER object, including an ordinary
local like `info`, falls through to its final `return None`, which the
callback-argument check then rejects as "not a scalar type".

**This is NOT a narrow, single-call-site gap — it's the same
underlying limitation as `bugs/hard/CODEGEN_generator_struct_typed_
param_refused.md` (task #147), just surfacing at a captured-callback
call-site's ARGUMENT instead of a parameter's own declared type.**
Widening `_infer_simple_expr_ctype`'s `MemberExpr` case to cover
arbitrary (non-`self`) struct-typed locals would need the same
"real class-attribute/field-access story for non-`self` objects" this
codegen doesn't have anywhere yet (per task #147's own "What a fix
would need" analysis) — not a one-line widening reusing an existing
mechanism, the way the `Comprehension`/`object()` fixes landed
elsewhere in this cluster were.

**Independently confirmed not to matter for this file even if fixed**:
`walk_packages`'s body has several OTHER unsupported constructs beyond
this one check — `__import__(info.name)`, `sys.modules[info.name]`,
`getattr(sys.modules[...], '__path__', None)`, a nested closure `seen`
with a mutable default argument (`def seen(p, m={}):`), and a
self-recursive `yield from walk_packages(path, info.name+'.',
onerror)` with a REASSIGNED `path` parameter (not the untouched
top-level generator-recursion shape task #138 fixed). Even a full fix
to the `onerror(info.name)` argument-shape gap would only move the
refusal to the very next unsupported construct in the same function,
not unblock it. Not attempted — correctly left refused, matching this
project's "feature-sized, needs new shared machinery" bar for a
deferred fix (same bar `CODEGEN_generator_struct_typed_param_refused.md`/
`CODEGEN_args_kwargs_signature_assumed_forwarding_only.md` were each
independently assessed against).

## Status (updated 2026-08-06, superseded above)

**STILL FAILING**, but the specific reason has changed since 2026-07-30
(that note's "yields ModuleInfo objects — non-scalar yield type" framing
no longer matches the current refusal reason).

```
$ MOJO_DEBUG=1 python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/pkgutil.py
[gimple_codegen] generator 'walk_packages' not eligible for C++ coroutine path, falling back to honest refusal: calling captured function 'onerror': argument must be a scalar int64_t/double/_Bool/char* expression
Error building: cannot compile module: function(s) walk_packages (generator function(s), ...) — falling back to interpreting this module from source instead
```

**Root cause:** `walk_packages(path=None, prefix='', onerror=None)`
calls its own `onerror` parameter (a passed-in callback) as
`onerror(info.name)` inside the generator body (in an `except
ImportError:`/`except Exception:` handler). The coroutine codegen DOES
have support for calling a captured/parameter function value — the
refusal message ("argument must be a scalar int64_t/double/_Bool/char*
expression") shows the callback-invocation support itself has a
narrower requirement than the generator's own general parameter-type
allow-list: the ARGUMENT expression passed to the callback must
apparently be a simple literal/identifier, not `info.name` (a
`MemberExpr` field access on the loop variable `info`, a `ModuleInfo`
namedtuple instance) — even though `info.name`'s real runtime type
(`char *`) IS itself in the generally-allowed set.

**New, narrow gap — not yet folded into a hard-bug doc** (single
instance so far in this cluster). Distinct from the already-known
struct-typed-param refusal (`bugs/hard/CODEGEN_generator_struct_typed_
param_refused.md`) and the dynamic-`raise` gap (imaplib.py's bug doc):
this one is specifically about the SHAPE of an argument expression at a
captured-callback call site inside a generator, not about a parameter's
own declared type. Flagged for whoever next hits this shape (calling a
generator's own callback/function-valued parameter with a non-trivial —
e.g. member-access — argument expression) to confirm and fold into a
dedicated hard-bug doc.

Not fixed here — narrow-looking but inside the coroutine `.cpp`
call-lowering path, which this task's guidance flags as warranting its
own dedicated verification pass.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/pkgutil.py
