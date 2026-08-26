# CODEGEN_generator_function: Lib/pkgutil.py

## Status (re-verified 2026-08-26, wtOpencode_genlib3): byte-identical refusal, unchanged

Fresh real `python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/
pkgutil.py` against current master (f0f6e78): dies with the identical
`RuntimeError: cannot compile module: function(s) iter_importers,
iter_modules, walk_packages ...` — the same three independent gaps as
the 2026-08-26/08-25 entries (non-static `getattr(obj, name)`; `map()`
with no coroutine-body lowering; consumption of a never-translated
generator). None of the recently landed shared mechanisms bear on
these. A map()-only narrowing still would not unblock the file
(iter_importers + walk_packages' five further stacked constructs
remain), per the 2026-08-24 analysis below — feature-sized, out of
scope. No code change; doc stays open.

## Status (re-verified 2026-08-26, worktree fix/rest-remainder19d — checked against today's super()/self.__class__ fix (bdfb825) and generator-value-return-slot fix (326db78); neither applies, unchanged)

Fresh isolated `compile_to_gimple_with_cpp(do_imports=False)` repro:
byte-identical refusal — `iter_importers, iter_modules, walk_packages`,
same three independent gaps as every prior entry (`getattr(obj, name)`
non-static name; `map()` has no coroutine-body lowering; consumption of
`iter_modules` moot until its own `map()` gap resolves). Neither of
today's two landed fixes is relevant: `bdfb825` is about `super()`/
`self.__class__` call resolution (this file uses neither), and `326db78`
is about value-carrying `return` inside a generator (none of this file's
3 refused generators have one — all refuse earlier, on `map()`/`getattr`
shape). No code change; doc stays open.

Fresh `MOJO_DEBUG=1 python3 mojo.py build /Users/mrs/net/Python-3.14.6/
Lib/pkgutil.py` against current tree (`a913ab8`, includes the self-host
bootstrap fix and every other shared mechanism landed through
2026-08-25): byte-for-byte the same three refusals as the 2026-08-25
entry below — `iter_importers` (`getattr(obj, name)` non-static name),
`iter_modules` (`map(...)` unresolved callee), `walk_packages`
(consumes `iter_modules`, which never becomes a translated generator).
Also confirmed by direct source reading, not just re-running the build:

- `gimple_cpp_core.py`'s `_cpp_expr` CallExpr dispatch (~line 2632-2660)
  has no case for `map`/`filter` anywhere — its own comment explicitly
  lists "Python builtins with no coroutine-body lowering (map/filter...)"
  as a known-unhandled bucket, falling through to the generic
  unresolved-callee refusal. No shared fix (zip_longest, isinstance,
  int()/float(), etc.) touches this; `map()` remains categorically
  unsupported.
- `getattr(obj, name)` with a non-static `name` is a DELIBERATE,
  commented refusal (same file, ~line 2224-2251): "no runtime
  attribute-reflection table exists in this codegen" — not a narrow
  gap, a structural one (this compiler resolves every field/method to a
  fixed compile-time offset/symbol, never a runtime string).

Both are genuine, still-unimplemented feature gaps (real `map()`
lowering with either eager materialization or a driving-loop consumer,
and a real name->member reflection table for `getattr`), not narrow
widenings of existing machinery. `walk_packages` remains additionally
blocked by the 5 further independent unsupported constructs the
2026-08-11 entry catalogued (nested closure w/ mutable default,
`__import__`, `sys.modules[...]`, 3-arg `getattr`, reassigned-param
self-recursion) even if `iter_modules` were fixed. No code change.
Doc stays open — module still does not build. Quality gate unaffected
(no compiler-source change this pass): `test_gimple.py` 256/256,
`test_module_cache.py` 76/76 (both re-run fresh this session).

## Status (updated 2026-08-25, branch fix/opencode-pkgutil — shared consumption-ordering blocker FIXED at the machinery level; this file stays open on its own separately-classified gaps)

The "generator-consumption ordering" blocker this doc was the primary
repro for is now fixed in shared source (commit `9ea2749`), just not in
the shape earlier entries assumed. Findings that supersede the
"single-pass emitter / consumed generator must be defined earlier"
framing below:

- The emitter has NOT been single-pass for a while: gen_module already
  had a multi-pass retry loop for generators whose consumers precede
  their producers. Two real defects remained ON TOP of it, both now
  fixed:
  1. The retry loop was hard-coded to `range(3)`. A forward-consumption
     CHAIN needs one retry per link, so anything deeper than 4 silently
     left its head generators refused (verified pre-fix with a
     6-generator chain: a1/a2 stayed refused while a3..a6 compiled).
     It now runs to a fixed point (bounded by the pending-generator
     count; mutual-recursion cycles make no progress and break out to
     the same honest refusal as before, verified terminating).
  2. Both coroutine-body consumption paths (`for ... in <gen>(...)`
     and `yield from <gen>(...)`) hard-refused on argument count when
     the consumed generator had defaulted params ("expected 2
     argument(s), got 1"), and the DIRECT generator-call path had
     pre-BUG-2026-020 defaults indexing — `prod(3)` against
     `def prod(n, step=10)` SILENTLY ran compiled with step=0 (a wrong-
     code bug, not a refusal). All sites now share
     `gimple_exprtypes._trailing_default_at` and pad honestly via
     `_default_expr_to_pair` (literal-only, cannot emit an undeclared
     identifier into a coroutine body).
- Refusal reasons are now latest-wins across retries. Previously the
  FIRST pass's message stuck (`setdefault`), which routinely reported
  the stale "defined LATER" text even when the deciding failure was a
  different shape entirely — several of this cluster's diagnoses (this
  doc's included) were written off that stale message.
- Verified END-TO-END (compiled path, not interpreter fallback):
  5-deep all-forward consumption chains, defaults through every
  consumption path (for-loop / yield-from / direct call / method call)
  all compile AND produce correct runtime output; new regression tests
  in test_gimple.py + test_gimple_generator_runner.py; gates clean
  (253/253, 76/76, selfhost clean, stdlib dylib 0 skips).

**What this means for pkgutil.py specifically: nothing closes yet, by
design of the task split.** Current per-function state (fresh repro,
post-fix):

- `walk_packages`: still refuses consuming `iter_modules(...)` — but
  the binding constraint is no longer ORDERING (an eligible later-defined
  callee now resolves automatically); it is that `iter_modules` never
  becomes a translated generator AT ALL, because of its own
  `importers = map(get_importer, path)` gap. Moot-ordering refusal;
  unblocks only when iter_modules' map() gap gets its own fix.
- `iter_modules`: `map(...)` unresolved-callee refusal (separate,
  already-documented gap; unchanged).
- `iter_importers`: non-static `getattr(obj, name)` refusal (separate,
  already-documented gap; unchanged).

A true TWO-PASS scheme (pre-registering generator prototypes before
body lowering) was investigated and deliberately NOT implemented: it
buys only mutual-recursion cycles beyond what fixed-point retry
already delivers, and cycles additionally need retraction semantics
(a consumer's emitted unit references `{base}_start/_resume/_value`
symbols that must disappear if the producer ultimately refuses — the
current consume-only-fully-translated-generators rule is what guarantees
link safety). Classified feature-sized, matching the project bar for
shared emission-ordering machinery. Doc stays open — module still does
not build.

## Status (updated 2026-08-24, worktree fix/gen-core — re-verified fresh, findings unchanged; not fixable narrowly)

Re-ran the isolated coroutine-path compile fresh (post-`fd909e9`,
post-this-session's `6e92df8` dunder-alias fix — neither applies to
this file's own blockers). Confirms the 2026-08-23 entry's diagnosis
exactly: `iter_importers` (`getattr(obj, name)` with a non-static
name), `iter_modules` (`importers = map(get_importer, path)` then
consumed later — `map()` has no coroutine-body lowering; a narrower fix
scoped to "a KNOWN module-level function passed to `map`" was
considered but would still leave `walk_packages` and `iter_importers`
blocked on their own separate gaps, so not attempted), and
`walk_packages` (consumes `iter_modules`, which is defined LATER in the
module than `walk_packages` itself — this single-pass emitter requires
a consumed generator to be defined earlier) all still refuse for the
same reasons. Three independent, genuinely feature-sized gaps stacked
on three functions — confirmed, not narrow. Doc stays open, unchanged
classification.

## Status (updated 2026-08-23, worktree branch fix/gen-lib-b — re-verified, unchanged; correctly NOT fixed)

Re-verified against current HEAD (post f7cf084/53b1aaa/65706f3) via a real
`python3 mojo.py build .../Lib/pkgutil.py`: **0 errors attributed to
pkgutil.py's own source**, and the build still fails on `walk_packages` +
`iter_importers` exactly as this doc's 2026-08-11 analysis predicts.
`walk_packages`'s current refusal reason is now the predicted NEXT gap in
that analysis — `for ... in iter_modules(...)` "does not consume a
generator this compile has itself already translated" (the consumption-of-
a-non-compiled-generator shape) — with the remaining stacked gaps (nested
closure with mutable default, `__import__`, `sys.modules[...]`, 3-arg
getattr, reassigned-param self-recursion) still queued behind it.
`iter_importers` refuses on its own documented shape (`getattr(obj, name)`
with a non-static attribute name). All other refusals in the build log
name generators in OTHER transitively-imported modules. The 2026-08-11
"feature-sized, do not force" classification stands unchanged.

## Status (updated 2026-08-11, real fix attempted on `walk_packages` — confirmed genuinely stacked, not narrow)

Re-verified against current master via a real `python3 mojo.py build
/Users/mrs/net/Python-3.14.6/Lib/pkgutil.py`. Confirms the 2026-08-10
status below still holds exactly: the module's own two tuple-yield
generators stay fixed, and `walk_packages` is the file's only remaining
refused generator (`MOJO_DEBUG=1` shows only `walk_packages` refusals
across all 4 codegen passes now — nothing else in this file's own
source).

Went further than the prior passes and actually attempted a real fix
for `walk_packages`'s narrowest-looking refusal (`onerror(info.name)`:
"argument must be a scalar ... expression", from `info.name` being a
`MemberExpr` on a non-`self` local). Read `walk_packages`'s full body
(`pkgutil.py:37-90`) end-to-end before touching any code, specifically
to check whether fixing just that one check would actually unblock the
function (this project's history flags "narrow-looking single-check
fixes that don't move the needle" as wasted, regression-risking effort
on shared machinery). It would not — the SAME function body has, all
independently reachable regardless of that one fix:

- `for info in iter_modules(path, prefix):` — the CURRENT pass-1
  refusal reason (confirmed via `MOJO_DEBUG=1`, unchanged from below):
  `iter_modules` isn't a generator this compile has itself already
  translated via the coroutine path at the point `walk_packages` is
  compiled, an entirely separate gap from the `onerror` argument-shape
  one.
- a nested closure `def seen(p, m={}):` with a MUTABLE DEFAULT
  argument — no representation in this coroutine body model at all
  (nested `FunctionDef`s inside a generator body are a distinct,
  unhandled shape).
- `__import__(info.name)` and `sys.modules[info.name]` — both call/
  subscript a compile-time-unresolvable dynamic name; neither has a
  case in this scalar body model.
- `getattr(sys.modules[...], '__path__', None)` — compounds the
  `sys.modules[...]` gap above with a 3-arg `getattr` on its result.
- a self-recursive `yield from walk_packages(path, info.name + '.',
  onerror)` where `path` (the enclosing generator's OWN parameter) has
  been REASSIGNED earlier in the loop body — a different shape from
  the untouched-parameter self-recursion this codegen's generator-
  recursion support already handles (task #138's fix).

That's five further independent unsupported constructs in the same
function, on top of the argument-shape gap and the `iter_modules`
consumption gap already found. Fixing the `onerror(info.name)` check
alone would immediately hit the `for info in iter_modules(...)` gap
(now the actual pass-1 blocker), then each of the five above in turn.
This is not a case where one narrow check is the last thing standing
between this function and a clean compile — it is a function built
almost entirely out of shapes this generator-coroutine codegen doesn't
support yet, each independently. Not implemented — matches the
existing analysis below, now confirmed (not assumed) by tracing the
whole function body rather than stopping at the first refusal message.
Doc kept open, not deleted (module doesn't build).

## Status (updated 2026-08-10 — the 2 tuple-valued-yield refusals now FIXED; `walk_packages`'s own, unrelated gap remains)

Implemented real tuple-valued-`yield` support this session (see
`gimple_codegen.py`'s `_cpp_yield_tuple`/`_generator_tuple_yield_slot_
ctypes`). Re-verified via an isolated compile: `_iter_file_finder_
modules`'s `yield prefix + modname, ispkg` and `iter_zipimport_
modules`'s two `yield prefix + fn[0], True` / `yield prefix + modname,
False` sites are NO LONGER in the refusal list — both generators now
compile past the eligibility gate (confirmed: the overall build's
Python-level `RuntimeError` now names only `walk_packages`, not all
three as the 2026-08-09 status below shows).

**pkgutil.py still does not build**, blocked by `walk_packages`'s own,
wholly unrelated, pre-existing gap (unchanged from the 2026-08-07
analysis below): calling its own `onerror` callback parameter as
`onerror(info.name)` — `info.name` is a `MemberExpr` field read on a
non-`self` struct-typed local, which the coroutine-body's captured-
callback-argument type check doesn't accept. Not the tuple-yield gap
this session's fix targets. Doc kept open (not deleted) — 2 of 3
generators fixed, but the file still doesn't build as a whole.

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
