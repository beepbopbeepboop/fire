# HARD BUG: `self.field = param` with an unannotated, no-default `__init__` parameter always types the field `int64_t`, even for real string/list/etc. call-site arguments

## Status (re-verified 2026-08-23 — no new work)

Re-ran all three repro shapes via `fire.py build` + executing the binary:
direct-literal `Widget("hello")` → `hello`/`5`; the 2026-08-18
IdentExpr-case fix `s = "hello"; w = Widget(s)` → `hello`/`5`; and the
conflicting-call-site case (`Thing("str")` + `Thing(3.5)`) still correctly
falls back to the `int64_t` default under the documented "not unanimous →
leave unresolved" rule (compiles and runs cleanly; no spurious
resolution). The 2026-08-18 fix is fully intact after the Wave-2 file
refactor; the remaining MemberExpr/CallExpr ctor-argument limitation
stands as documented below.

## Status (2026-08-18 — IdentExpr-argument case FIXED via a later reconciliation pass)

Closed the "Known limitation" gap this doc's 2026-08-09 status left open:
`s = "hello"; w = Widget(s)` now correctly types `Widget.label` as `char *`
and the compiled binary prints `hello`/`5`, not a raw pointer integer.

**Investigated both directions the 2026-08-09 status flagged, concretely**:
traced `gen_module`'s actual pass order and dependency graph rather than
picking abstractly.

- Option 1 (reorder the early ctor-literal pass to run after
  `self._inferred_var_types` exists): confirmed NOT safely reorderable
  without much broader surgery. `self._inferred_var_types` is populated at
  Pass 1.3b (~gimple_codegen.py:33711), which itself sits **after** the
  struct-field-collection loop (`_collect_self_assigns`, ~line 32404-32610)
  that locks in every field's C type — by design, since Pass 1.3b depends on
  things resolved earlier still (`_inferred_param_types`, struct field
  types themselves for some inference paths). Moving struct-field-collection
  to run after Pass 1.3b would risk exactly the kind of broad reordering
  this doc's own "Risk" section already warns against, for machinery this
  session did not fully audit end-to-end. Not attempted.
- Option 2 (a second, later reconciliation pass): this is what was
  implemented. Confirmed genuinely low-risk because of WHEN it runs: added
  as a new pass ("Pass 1.3d-ctor", gimple_codegen.py, immediately after
  Pass 1.3d's free-function cross-call scalar contract, ~line 33896) —
  after `self._inferred_var_types` exists, but **before any C struct
  typedef or code text has been emitted** (struct typedef emission is
  Phase 2, thousands of lines further down, ~line 36662+). So despite the
  name "reconciliation", this isn't actually patching already-emitted C —
  `self.struct_field_types` is a plain Python dict that nothing downstream
  has read yet at this point, so overwriting a stale `int`/`int64_t` entry
  here is indistinguishable from having gotten it right the first time, as
  far as every later pass and the actual C emission are concerned.

**What was implemented**: reused the exact same helpers Pass 1.3d's
free-function version already uses (`_arg_scalar_type`, `_caller_bodies`)
to scan every `ClassName(...)` call site again, now resolving `IdentExpr`
arguments via `self._inferred_var_types`/`self._inferred_param_types`
lookups (not just `StringLiteral`/`FloatLiteral` as the early pass does).
When a `__init__` parameter's call-site evidence is unanimous (`double` or
`char *`, exactly the same "not unanimous → leave alone" rule as every
sibling pass in this file), the corresponding `self.field = param` direct
assignment(s) in `__init__`'s own body are found via an explicit
`_walk_ast` loop (no `next(gen, default)` — the already-documented
self-host `_next`-link-failure gotcha this doc's own history already hit
once) and `self.struct_field_types[struct][field]` is upgraded from
`int`/`int64_t`/unset to the resolved type. Also updates
`self._ctor_lit_param_types` for consistency (harmless — nothing
downstream re-reads it at this point in `gen_module`).

Handles both direct-literal-assigned variables (`s = "hello"`) and a
variable whose own type came from a parameter/earlier inference chain —
confirmed via a real-world-derived repro modeled on `importlib/
_bootstrap.py`'s `_DummyModuleLock`/`_ModuleLockManager` pattern where the
constructor argument is itself a parameter of an intermediate function
(`get_lock(name): return _DummyModuleLock(name)`), not just a bare
top-level local.

### Verification (2026-08-18)

- **Step 1 baseline confirmation**: re-ran the doc's own `IdentExpr`
  minimal repro against the unmodified tree first — confirmed clean compile
  + wrong runtime output (`4306227784` / `6581285` for a fresh run),
  reproducing this doc's 2026-08-09 findings exactly, before making any
  change.
- IdentExpr minimal repro (`s = "hello"; w = Widget(s)`): now prints
  `hello` / `5` — FIXED.
- Direct-literal repro (`Widget("hello")`): still prints `hello` / `5` — no
  regression.
- Conflicting-call-site repro (`Thing("str")` / `Thing(3.5)`): still
  compiles and runs cleanly, field still falls back to `int64_t` (no
  spurious resolution from disagreeing evidence) — the "not unanimous →
  unresolved" rule holds under the new pass too.
- Comprehension-sibling repro (`Tools/cases_generator/cwriter.py`-style
  `self.indents = [i * 4 for i in range(indent + 1)]`): still reads back
  `0, 4, 8` — no regression (this pass is additive, doesn't touch the
  `Comprehension` case).
- Real-world instance (`Lib/importlib/resources/readers.py`'s
  `NamespaceReader.__init__`): re-checked current status — still fails to
  build, but for the SAME pre-existing, unrelated reason this doc already
  documented (`_candidate_paths` is a generator function; no compiled-path
  generator support). Confirmed this specific instance is additionally NOT
  reachable by this fix even setting the generator issue aside: its own
  call site (`importlib/_bootstrap_external.py`: `NamespaceReader(self.
  _path)`) passes a `MemberExpr` (`self._path`), not a bare `IdentExpr` —
  outside this fix's scope by design (matches the doc's own original
  IdentExpr-only target, not scope-crept to arbitrary expressions). Since
  a full build still isn't possible for the unrelated generator reason, did
  an isolated check instead: a synthetic repro built directly from
  `importlib/_bootstrap.py`'s real `_DummyModuleLock`/`_ModuleLockManager`
  source (self-contained, no generator dependency) confirmed the
  interpreter and the compiled binary now agree (`importlib.util` / `done`
  in both), where the field-typing bug this doc describes would previously
  have shown up as a garbage integer from the compiled path only.

### Full 5-part quality gate (2026-08-18), doc's own fail-fast order

1. `python3 compile_stdlib.py -j8`: **664/664, 0 unexpected** — identical to
   baseline, checked FIRST per this doc's own "Risk" section reasoning.
2. `python3 test_gimple.py`: 248/248 passed.
3. `python3 test_module_cache.py`: 76/76 passed.
4. `make check-selfhost`: clean (`✓ self-host compiles + links clean`).
5. From-scratch stdlib dylib rebuild (`rm -f build/libmojostdlib.dylib` +
   `build_stdlib_dylib.build_stdlib(jobs=8)`): **0 skips**, dylib built.

All five passed cleanly on the first attempt — no revert needed.

### Remaining limitation (unchanged from before, out of scope for this fix)

Only DIRECT `self.field = param` assignments in `__init__`'s own body are
patched (mirroring `_collect_self_assigns`'s own `IdentExpr` case exactly).
A field set via a more indirect expression involving the param (e.g.
`self.field = str(param)` or a conditional branch computing a derived
value) is untouched by this pass and keeps whatever the original
struct-field-collection loop already inferred for it — this was never
part of either this fix's or the doc's original scope. A constructor
argument that is itself a `MemberExpr`/`CallExpr` (not a bare `IdentExpr`
or literal) is likewise still unresolved, same as before this fix (see the
`NamespaceReader` case above).

## Status (re-verified 2026-08-09 — unchanged, still PARTIALLY FIXED)

Re-ran both minimal repros against current master via `python3 fire.py
build <file>.py` + running the resulting binary:

- Covered case (direct literal constructor argument — `class Widget:
  def __init__(self, label): self.label = label` / `w =
  Widget("hello")`): builds clean, runs, prints `hello` / `5` — correct.
- Known-limitation case (same class, but constructed via an
  already-inferred local variable instead of a literal — `s = "hello";
  w = Widget(s)`): builds clean (no compile error) but the RUNNING
  binary prints a raw pointer decimal (e.g. `4337521104`) and a nonsense
  length (e.g. `6581285`) instead of `hello`/`5` — exactly the silent
  wrong-value symptom the "Known limitation" section below describes,
  unchanged.

Both claims in this doc still hold exactly as documented. No code
change made — extending the fix to the `IdentExpr`-argument case would
require the pass-ordering rework the "Known limitation" section already
flags as out of scope for a lightweight re-check, and this session's
assignment was explicitly to re-verify only, not extend the fix.

Both the comprehension sibling gap AND a scoped version of the main
`IdentExpr`/param fix are now fixed. The main fix's scope is narrower
than the full plan below — see "What was actually implemented" and
"Known limitation" before relying on this for a case beyond a literal
constructor argument.

### Comprehension sibling gap: fixed

Added a `Comprehension` case to `_collect_self_assigns`'s value-type
dispatch (`gimple_codegen.py`, alongside the existing `ListExpr`/
`DictExpr`/`SetExpr` cases), mapping `kind='list'/'set'/'dict'` to
`MojoList */MojoSet */MojoDict *` respectively. Verified against this
doc's own `Tools/cases_generator/cwriter.py`-derived repro (`self.
indents = [i * 4 for i in range(indent + 1)]`) — the compiled binary
now reads back the real list values (`0, 4, 8`), not a truncated
pointer.

### Main fix: constructor call-site scalar inference — fixed for LITERAL arguments only

**What was actually implemented**: extended `gen_module` with a new,
EARLY, standalone pass (placed immediately before the struct-field-
collection loop that calls `_collect_self_assigns`) that scans every
`ClassName(...)` call site across the module (and its transitive
imports) for a `StringLiteral`/`FloatLiteral` argument at a position
corresponding to one of `__init__`'s own unannotated parameters. When
every observed call site agrees, the parameter's real type (`char */
double`) is recorded in a new `self._ctor_lit_param_types` dict and fed
into `_collect_self_assigns`'s `pm` (param-type) lookup for `__init__`
specifically, ahead of the `int64_t` fallback — mirroring the doc's own
described plan (steps 1-3), but as a small, self-contained pass rather
than literally extending Pass 1.3d.

**Why NOT a literal extension of Pass 1.3d** (this doc's own "What a
real fix needs" section 1 suggested reusing/extending the existing
free-function cross-call scalar-contract mechanism): confirmed by
direct testing that Pass 1.3d runs too LATE — it depends on
`self._inferred_var_types`, itself populated even later in `gen_module`,
and by the time it runs, the struct-field-collection loop (several
thousand lines earlier in the same method) has already locked in every
field's C type. A first attempt that extended Pass 1.3d's own
`_scalar_obs`/Apply machinery (under a `<ctor>`-prefixed key to avoid
namespace collision with free-function entries) compiled and ran the
minimal repro correctly in isolation but was CONFIRMED, by direct
testing, to never actually take effect end-to-end (`Widget("hello")`
still printed a raw pointer integer) — exactly the pass-ordering bug
this paragraph describes. Reverted in favor of the standalone early
pass actually landed.

**Known limitation**: because the early pass runs before `self.
_inferred_var_types` exists, it can only see DIRECT LITERAL constructor
arguments (`Widget("hello")`), not the fuller "argument is an `IdentExpr`
referencing an already-inferred variable" evidence the free-function
version of this mechanism uses. This means `Lib/importlib/resources/
readers.py`'s `NamespaceReader.__init__` (this doc's own real-world
instance — the call site passes a variable, not a literal) is NOT
fixed by this change, and that file also independently fails to compile
for an entirely unrelated reason (`_candidate_paths` is a generator
function; this codegen has no compiled-path support for generators
containing `yield` in this call chain, an already-documented, separate
gap) — so it could not be used as an end-to-end verification instance
either way. Extending this to the fuller `IdentExpr`-based case would
require either reordering `gen_module`'s passes (broad, high-risk — the
plan's own reasoning for treating this whole area cautiously) or a
second, later reconciliation pass patching already-emitted struct field
types after Pass 1.3d runs (not attempted, left as a documented
follow-up). The `int64_t` fallback is unchanged for every case this
narrower pass can't resolve — strictly additive, per the doc's own
point 3, just with a smaller resolved set than originally scoped.

### Verification

- Minimal repro (`class Widget: def __init__(self, label): self.label
  = label` / `w = Widget("hello")`) — compiled binary now prints
  `hello`/`5` (`len(w.label)`), not a raw pointer integer.
- Conflicting-call-site repro (`Thing("str")` and `Thing(3.5)` for the
  same unannotated param in different call sites) — correctly falls
  back to the `int64_t` default (no unanimous type), compiles and runs
  without error, confirming the "not unanimous → leave unresolved" rule
  holds.
- Comprehension-sibling repro: see above.
- A self-hosted-build regression was caught and fixed during
  verification: the first draft used `next(generator, default)` in two
  places to find a struct's own `__init__` method — this is the EXACT,
  already-documented gotcha the neighboring Pass 1.3d code comments
  warn about (a self-hosted build of this file failed to link with an
  undefined `_next` symbol). Rewritten as explicit loops / a
  precomputed `_ctor_init_methods` dict; `make check-selfhost` confirmed
  clean afterward.
- Full 5-part gate, run in this doc's own recommended fail-fast order
  (`compile_stdlib.py -j8` FIRST, given this doc's own "Risk" section
  explicitly calls this the same class of risk as the `_tuplegetter`
  regressions): `compile_stdlib.py -j8` 664/664 (0 unexpected,
  unchanged from baseline) both before AND after the self-host-regression
  fix — no stdlib compile-breadth regression at any point.
  `test_gimple.py` 247/247, `test_module_cache.py` 76/76, `make
  check-selfhost` clean (after the `next()` fix), from-scratch stdlib
  dylib rebuild 0 skips.

## Original status (2026-08-07): still fully unfixed, including the comprehension sibling gap

This session's assignment explicitly held this whole task (#143) back
as "DO NOT TOUCH ... due to prior regressions". While investigating
`bugs/COMPILE_FAIL_Tools_cases_generator_cwriter.md` (independently, for
an unrelated `_compr_range_loop` bug — see that doc), a fix for this
doc's own "Sibling gap: comprehension RHS" section below was drafted
(adding a `Comprehension` case to `_collect_self_assigns`) and DID pass
the full 5-part quality gate cleanly with zero regressions — but was
deliberately reverted without landing, once it was recognized as inside
this doc's excluded scope, rather than unilaterally deciding it was
"safe enough" to ship despite the explicit hold. Recorded here so a
future session doesn't have to rediscover that a working draft exists
(look for the corresponding revert in this session's commit history) —
still genuinely unfixed, including this sibling gap, pending the
"separate, directly-supervised work" this task is reserved for.

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

Confirmed via the interpreter (`fire.py run`, the SEPARATE, correct
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
- `make check-selfhost`: only checks that fire.py compiling itself
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

## Sibling gap: comprehension RHS also falls to the same `int`/`int64_t` default

Confirmed 2026-08-06 via `bugs/COMPILE_FAIL_Tools_cases_generator_cwriter.md`.
`_collect_self_assigns` (the same function this doc's main root-cause
section describes) dispatches on `node.value`'s AST type to guess a
field's C type: `IdentExpr` → look up `param_types` (this doc's main
finding), `IntLiteral`/`StringLiteral`/`BoolLiteral`/`DictExpr`/
`(ListExpr, TupleExpr)`/`SetExpr`/`CallExpr` all get their own
dedicated case — but a **comprehension** (`[x for x in y]`/
`{x for x in y}`/`{k: v for k, v in y}`), a DIFFERENT AST node type
than a literal `ListExpr`/`DictExpr`/`SetExpr`, matches NONE of these
cases and falls to the same generic `else: ft = 'int'` fallback
(gimple_codegen.py:26787-26788) as any other unrecognized shape.

Real instance: `Tools/cases_generator/cwriter.py`'s `CWriter.__init__`:
```python
self.indents = [i * 4 for i in range(indent + 1)]
```
Field `indents` gets declared `int` (confirmed via the generated
`.ci`'s struct typedef: `int indents;`, vs. the real value being a
`MojoList *` pointer truncated through `(void*)→(int64_t)→(int)` casts
to fit). Any later method reading `self.indents` as a list then hits
`non-trivial conversion in 'integer_cst'` / `type mismatch in binary
expression`.

This is a distinct code path from the main `IdentExpr` case this doc
focuses on (no `param_types` lookup involved at all — a comprehension
is a computed expression, not a parameter reference), but the SAME
function, the SAME class of risk, and a real fix would naturally want
to add a comprehension case (`ListComp`/`SetComp`/`DictComp` — whatever
`mojo_compiler.py` names these nodes) mapping to `MojoList
*`/`MojoSet *`/`MojoDict *` respectively, alongside the existing
literal-collection cases at gimple_codegen.py:26744-26749. Not
attempted — flagging as a cheap addition to the SAME eventual fix this
doc already describes, not a separate investigation.

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
