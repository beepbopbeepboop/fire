# HARD BUG: the self-hosting `getattr(self, x)`-dispatch-table heuristic mis-fires on ordinary stdlib code, emitting invalid C

## 2026-08-19: 02b14c5's own gate was too narrow, broke `test_dispatch_phase_b.py`/`test_dispatch_phase_c.py` — fixed by having the TESTS opt in, not by widening the production gate

The 2026-08-18 fix directly below (gating the "assume all methods"
fallback behind `DispatchSolver.allow_assume_all_methods`, set only when
`_is_selfhost_file`'s path-based check is true) turned out to be a real
regression against a *different* legitimate caller: `test_dispatch_phase_
b.py`'s `test_dispatch_solver_phase_b()` and `test_dispatch_phase_c.py`'s
five tests all construct a standalone `myinterp_test`/`multi_pattern_test`
source string containing the exact same `Interpreter.execute`-style
`getattr(self, x)`-as-vtable-dispatch idiom this whole mechanism exists
for — but as an in-memory test fixture, not one of this repo's own `.py`
files on disk, so `_is_selfhost_file` (which only ever looks at
`self._current_filename`'s path) was always False for them, and the
fallback that used to fire unconditionally (pre-02b14c5) silently stopped
firing. Confirmed via bisection: `gimple_codegen.py` checked out from
02b14c5~1 passes both tests; current (post-02b14c5) HEAD fails both with
"Should have planned at least one dispatch table" / "Should have planned
dispatch tables".

**First fix attempt (tried, then reverted — documented for anyone who
re-derives it)**: per this doc's own "option 2" below, widen the
production gate to also allow the fallback whenever the `getattr(self,
x)` RESULT is actually CALLED somewhere in the same function body
(`getattr(self, x)(...)` inline, or `m = getattr(self, x); ...; m(...)`
split across statements) — a signal independent of file path, checked via
two small new helpers (`_walk_assign_targets` + per-body `called_ids`/
`called_names` sets) in `_find_patterns_in_body`/`_analyze_getattr_
pattern`. This DID make both tests pass, and did NOT reintroduce the
original `_LazyModule` symptom (`return getattr(self, attr)` — a bare
return, never called, so `is_called` stays False for it, confirmed via
`gimple_codegen.compile_linked(...)`: still 0 `dispatch_t` occurrences).

However, a full `python3 mojo.py build .../Lib/ftplib.py` comparison
(before vs. after, diffing the sorted set of `error: '<name>' undeclared`
symbols) showed the widened gate reopened the doc's OWN "residual risk"
paragraph in a very concrete way: ordinary visitor-pattern code that
happens to store the `getattr` result in a local before calling it —
e.g. `Lib/ast.py`'s `NodeVisitor.visit`/`NodeTransformer.visit`
(`method = 'visit_' + node.__class__.__name__; visitor = getattr(self,
method, self.generic_visit); return visitor(node)`), `Lib/reprlib.py`'s
`Repr.repr1`, and `Lib/datetime.py`'s `timezone`/`tzinfo` dunder-heavy
structs — is *structurally identical* to the self-hosted `Interpreter.
execute` idiom under the `is_called` test: both assign the getattr result
to a plain local and both call that local later in the same body. Widening
the gate on `is_called` alone newly registered ALL of `NodeVisitor`'s /
`Repr`'s / `timezone`'s methods as dispatch-table callees under their
UNQUALIFIED names, which — since these structs live in non-root,
transitively-imported modules — hit exactly the still-open "option 3"
qualification gap this doc's 2026-08-10 entry already flagged
(`gimple_codegen.py`'s callee registry uses the plain `f"{stmt.name}_
{method.name}"` name, not the module-qualified one). Concretely: the
before/after diff of `ftplib.py`'s undeclared-identifier symptom set grew
from 30 to 56 entries, with `NodeVisitor_visit`, `NodeTransformer_
generic_visit`, `Repr_repr_dict`, `timezone___repr__`, `tzinfo_dst`, etc.
newly appearing — a real regression, so this approach was reverted in
full (`git checkout -- gimple_codegen.py`) rather than shipped. It
confirms the doc's own risk note ("a case where the heuristic mis-fires
AND the self type happens to resolve to something plausible-but-wrong is
still possible in principle") is not just theoretical: `is_called` alone
is not a sufficiently narrow signal — ordinary delegate-with-a-fallback
patterns very commonly DO call the result, they just don't need a whole
struct's method set registered as callees to do it.

**Actual fix landed**: leave `gimple_codegen.py`'s production gate
completely untouched (still purely path-based, `_is_selfhost_file`-only,
exactly as 02b14c5 left it), and instead have the two test files opt in
explicitly, the way a real self-hosting compile would:
- `test_dispatch_phase_b.py` constructs `DispatchSolver` directly, so it
  now passes `allow_assume_all_methods=True` at the call site — it's
  deliberately testing the self-hosted dispatch idiom, so asking for that
  behavior by name is honest, not a workaround.
- `test_dispatch_phase_c.py` goes through `GimpleGen.gen_module`, whose
  self-host gate is path-based on `self._current_filename`; a new
  `_make_selfhost_gen(**kwargs)` helper constructs the `GimpleGen` and
  sets `gen._current_filename = gimple_codegen.__file__` (a real path
  under this repo's own `_SELFHOST_DIR`) before `gen_module` runs, then
  all five call sites use it instead of calling `GimpleGen(...)` directly.

This is strictly narrower and lower-risk than either gating option this
doc previously considered: zero lines of `gimple_codegen.py` changed at
all, so there is no way this could reopen the `_LazyModule`/`ftplib.py`
symptoms — confirmed by re-running both repros unchanged (`git diff
gimple_codegen.py` is empty for this session). Both `test_dispatch_phase_
b.py` and `test_dispatch_phase_c.py` pass again.

Verification performed:
- `python3 test_dispatch_phase_b.py` / `python3 test_dispatch_phase_c.py`
  — both fully pass (previously "Should have planned at least one
  dispatch table" / "Should have planned dispatch tables" failures).
- `python3 test_dispatch_myinterpreter.py`, `test_dispatch_solver.py`,
  `test_dispatch_promotions.py` — all pass, unchanged (these already
  either construct `DispatchSolver()` with the `allow_assume_all_methods`
  default of `False`, matching current production behavior exactly, or
  don't exercise this code path at all).
- `gimple_codegen.compile_linked(...)` on `Lib/importlib/util.py` — still
  0 `dispatch_t` occurrences for `_LazyModule` (unaffected, since
  `gimple_codegen.py` itself has zero diff this session).
- `python3 mojo.py build .../Lib/ftplib.py` — before/after diff of the
  sorted `error: '<name>' undeclared` symbol set is empty (identical both
  times, as expected with no production-code change); confirms neither
  the original `Popen__close_pipe_fds`/`calendar.Month`/`Day` symptom nor
  the `NodeVisitor`/`Repr`/`timezone` regression from the reverted
  attempt above are present.
- `python3 test_gimple.py` — 248 passed, 0 failed.
- `python3 test_module_cache.py` — 76 passed, 0 failed.
- `make check-selfhost` — clean (1 passed, 0 failed; "self-host compiles
  + links clean").
- From-scratch `libmojostdlib.dylib` rebuild
  (`build_stdlib_dylib.build_stdlib()`, default job count) — exit 0, 0
  `skip <module>:` lines.
- `python3 compile_stdlib.py` (default jobs) — 664/664 passed, 0
  unexpected failures (one run hit a transient, unrelated
  `BrokenProcessPool` from the OS process pool; a clean immediate retry
  passed 664/664 — not a code issue).

Committed. This doc stays open for the same unchanged reason as before:
the underlying "option 3" module-qualification gap in the fallback's
callee-registration is still real and still has no fix, it's just still
without a live repro in the *shipped* code path (the near-miss above was
in a reverted, never-shipped attempt).

## Fixed 2026-08-18: root cause (the over-eager "assume all methods" fallback) gated off for non-self-host compiles

Implemented **option 1** from "What a real fix needs" below, in full:
the `else` branch of `DispatchSolver._analyze_getattr_pattern`
(gimple_codegen.py, the "assume all methods might be called" fallback)
now only fires when `DispatchSolver.allow_assume_all_methods` is
`True`. That flag is threaded in from `DispatchSolver.__init__`'s new
`allow_assume_all_methods` parameter, set at the single call site in
`gen_module` (Phase 1.5, "dispatch solving") to the SAME `_is_selfhost_file`
local already computed earlier in that function (path-based: the root
file currently being compiled is one of this repo's own `.py` sources
under `_SELFHOST_DIR` — the exact test already used by
`_struct_method_qualifier`/the hardcoded self-host struct tables
elsewhere in this file, so no new detection mechanism was invented).
For any ordinary stdlib/user compile, the fallback branch is now
skipped entirely; `_analyze_getattr_pattern` leaves the `DispatchPattern`
with zero callees, and `_plan_dispatch_tables`'s existing `if not
pattern.possible_callees: continue` guard means NO dispatch table is
planned or emitted for that pattern at all — confirmed by inspecting
the generated C for `Lib/importlib/util.py`'s `_LazyModule` directly
(`gimple_codegen.compile_linked(...)`): zero occurrences of
`dispatch_t` anywhere in the output now (previously it contained a
`_lazymodule__dispatch_t` typedef + init, per this doc's own original
symptom). The narrowly-scoped, correctly-shaped `f'{prefix}_{...}'`
branch (`_infer_getattr_targets`) is untouched and still applies to any
code, self-hosting or not — it was never the over-broad piece.

This also resolves the 2026-08-10 "new symptom" entry below
(`Popen__close_pipe_fds`/`calendar.Month`/`Day` "undeclared here"
errors from `subprocess.py`/`calendar.py`'s own ordinary
`getattr(self, attr)`-shaped methods getting mis-registered as
dispatch-table callees under their unqualified names): since the
fallback no longer fires on those non-self-host structs at all, no
dispatch table — qualified or not — is ever built for them, so
"option 3" (module-qualifying the dispatch-table callee registry) was
verified unnecessary for these repros and NOT implemented; if some
future, still-undiscovered self-hosting-context repro combines the
fallback firing with a non-root-module struct, that residual
qualification gap (`gimple_codegen.py:753-758`'s plain
`f"{stmt.name}_{method.name}"` callee registration) would still need
fixing then, but no live repro of that combination exists.

Verification performed (all clean, no regressions):
- `make check-selfhost` — clean both immediately before AND after the
  change (`mojo.py` compiling its own source: 1 passed, 0 failed both
  times).
- `python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/ftplib.py` —
  the `Popen__close_pipe_fds`/`calendar.Month`/`Day` "undeclared here"
  errors are GONE (confirmed via `grep -i undeclared` on the full build
  log: zero matches for those symbols). The file still fails to build
  end-to-end for several other, unrelated, already-documented reasons
  (`_varsubb`/`_t3`/`hits`/`misses` etc. undeclared-identifier errors
  elsewhere in `posixpath.py`/`codecs.py`/`inspect.py`/`functools.py`/
  `reprlib.py`) — out of scope for this fix, not claimed fixed.
- `python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/importlib/util.py`
  — still builds clean (exit 0), and direct inspection of the generated
  C (via `gimple_codegen.compile_linked`) confirms zero `dispatch_t`
  occurrences for `_LazyModule` now (previously the malformed
  `_lazymodule__dispatch_t` this doc's title symptom describes).
- `python3 test_gimple.py` — 248 passed, 0 failed.
- `python3 test_module_cache.py` — 76 passed, 0 failed.
- From-scratch `libmojostdlib.dylib` rebuild
  (`build_stdlib_dylib.build_stdlib(jobs=8)`) — 0 `skip <module>:`
  lines before AND after the change (baseline was already a clean
  595/0-style build per prior sessions' notes; stayed that way).

Committed. This doc is being kept open (not deleted) only because the
theoretical residual risk noted in the "Status" section below (a
self-hosting-context callee whose owning struct is in a non-root
module) remains unconfirmed/unaddressed in principle, even though it
has no live repro — see that section's own wording, unchanged from
2026-08-10.

## New symptom found 2026-08-10 (same mechanism, different manifestation — not fixed)

While re-verifying `bugs/CODEGEN_generator_function_Lib_ftplib.md`
(unrelated generator-codegen pass), hit a SECOND, distinct symptom of
this exact same "assume all methods" fallback:
`python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/ftplib.py`
(which transitively imports `ssl.py` -> `subprocess.py`) fails with
dozens of `error: 'Popen__close_pipe_fds' undeclared here (not in a
function); did you mean 'subprocess_Popen__close_pipe_fds'?` (and the
identical shape for several `calendar.Month`/`calendar.Day` dunder
methods, via `gettext.py`'s own build pulling in `copy.py` ->
`argparse.py`/`ast.py`). This is NOT the "self type resolves empty"
symptom `option 3` already fixed (`_Bool_items`/malformed `( *self,
...)`  declarations) — here the `self` type resolves FINE, but the
callee is registered under its UNQUALIFIED name.

Root cause: this fallback's callee registry,
`self.struct_methods[stmt.name][method.name]`
(`gimple_codegen.py:753-758`), is populated with the plain
`f"{stmt.name}_{method.name}"` mangled name
(`gimple_codegen.py:756`) — this call-graph/dispatch-table analysis
pass predates (or was never updated to match) the module-qualified-C-
symbol scheme used elsewhere in this codegen for cross-module method
calls (see the "SB-1 mojo_abs symbol-collision fix" session). For a
struct defined in the ROOT module being compiled, the unqualified and
module-qualified names happen to coincide, so the bug is invisible
there — it only shows up when this heuristic mis-fires on a struct
defined in a NON-root, transitively-imported module (`subprocess.Popen`,
`calendar.Month`/`Day` here), where the two names genuinely differ and
`DispatchTable.emit_table_init` (`gimple_codegen.py:552-575`) emits a
struct-literal function-pointer initializer referencing a symbol that
was never declared under that exact spelling.

Not investigated further / not fixed here — same "moderate risk,
needs a dedicated `make check-selfhost`-first pass" caveat as the rest
of this doc; flagging precisely so a future pass fixing this doesn't
have to re-discover the module-qualification angle from scratch. A
real fix likely needs `_plan_dispatch_tables`'s callee registration (or
`DispatchTable.add_method`) to resolve/emit the module-qualified name
for any callee whose owning struct isn't in the root module, mirroring
whatever lookup the rest of the codegen already uses for ordinary
cross-module method calls.

## Status

**Partially fixed 2026-08-07** ("option 3" below — the defensive net
against an empty resolved `self` type — is implemented in
`DispatchSolver`'s callee-to-struct resolution). Found and landed as
part of the `weakref.py` investigation that was tracked in the now-
deleted `bugs/hard/CODEGEN_module_globals_cross_contamination_via_
imported_stmts.md` (fully fixed and removed 2026-08-10 — see commit
636718b and its predecessor for the fix detail and combined gate
results) — filed there rather than duplicated here since it's a
different subsystem (`DispatchTable`/`_plan_dispatch_tables`) from that
doc's own `gen_module` globals-struct fixes, but option 3 is
specifically this doc's own proposal.

The underlying heuristic mis-fire itself (this doc's root cause below)
is NOT fixed — option 3 only prevents it from emitting invalid C when it
mis-fires on a case whose `self` type can't be resolved; a case where the
heuristic mis-fires AND the self type happens to resolve to something
plausible-but-wrong is still possible in principle and not addressed.

**Re-verified 2026-08-10**: re-ran this doc's own real-world repro
(`Lib/importlib/util.py`'s `_LazyModule`) two ways — (a) `python3
mojo.py build /Users/mrs/net/Python-3.14.6/Lib/importlib/util.py`
(the default entry point, which for this file happens to succeed via
`driver.py`'s per-module link mode) and (b) directly via
`gimple_codegen.compile_linked(src, filename=...)` (the same call
`mojo.py build` makes), inspecting the generated `.ci` and compiling it
standalone with the project's real `-fgimple` GCC
(`/opt/local/bin/gcc-mp-15 -fgimple ...`). Both succeed cleanly (exit
0, 0 `error:` lines). The generated dispatch table for `_LazyModule`
now has a correctly-resolved `self` type on both function-pointer
fields (`void (*LazyModule___delattr__)(_LazyModule *self, int attr)`,
previously the malformed `( *self, int attr)` this doc's symptom
describes) — confirms option 3's defensive net (or some other change
since 2026-08-07) is holding for this doc's own concrete repro. The
dispatch table still contains both of `_LazyModule`'s dunder methods
(`__delattr__`/`__getattribute__`) as callees, consistent with the
heuristic's "assume all methods" fallback still firing (not narrowed) —
this file's `_LazyModule` just happens to have no OTHER, non-dunder
methods for the fallback to over-broadly rope in, so it can't currently
demonstrate the theoretical "self type resolves to something
plausible-but-wrong" residual risk described above. That residual risk
remains unconfirmed (no live repro) and unaddressed — same status as
2026-08-07, not attempted here either, for the same reasons (see
"Risk" below). Keeping this doc open for that reason: the doc's TITLE
symptom (emitting invalid C) has no known live repro anymore, but the
doc's own root cause (the over-eager heuristic itself) is still
genuinely unfixed, just currently non-crashing on every repro found so
far.

Originally: unfixed, root-caused 2026-08-06 while investigating
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
