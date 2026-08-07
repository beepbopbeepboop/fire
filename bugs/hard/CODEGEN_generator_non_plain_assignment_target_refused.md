# HARD BUG: any assignment inside a generator body whose target isn't a bare identifier is refused outright

## Status (updated 2026-08-07, SliceExpr sub-case: `iter_builtin_types`'s `subs[:] = []` FIXED; `patch_list`'s `orig[:] = saved` correctly STILL refused, for a good reason)

**Fixed the FULL-slice-assignment case** (`x[:] = value`, i.e.
`start`/`stop`/`step` all `None`) in `_cpp_stmt`'s `AssignStmt`
handling: it now lowers to genuine, pre-existing runtime helpers
(`mojo_list_clear` + `mojo_list_extend`), which is real correct
in-place-mutation behavior (matching Python's own slice-assignment
semantics — other references/aliases to the same list must observe
the change), not a no-op elision like the `sys.stderr` fix above.
Bounded/stepped slice-assign (`x[a:b] = y`, `x[::2] = y`) still needs
real element-shifting splice support and remains unattempted/refused —
no real occurrence found requiring it.

**Of this doc's two confirmed real occurrences, one is now genuinely
fixed end-to-end at the eligibility gate, the other is correctly still
refused** — found to differ during hand-verification, not assumed:

- `iter_builtin_types`'s `subs[:] = []` — **FIXED**, passes the
  eligibility gate. The RHS is a literal empty list, which needs no
  type information about `subs` at all (an empty-list RHS is always
  just "clear the target", handled as its own branch ahead of the
  general identifier-RHS case) — this occurrence has no way to hit the
  hazard described below. (The function as a whole still doesn't fully
  compile end-to-end for OTHER, unrelated reasons — same established
  "eligibility gate passes, other separate gaps remain" pattern as
  every other partial fix in this cluster — not investigated further
  here since not required for this fix.)
- `patch_list`'s `orig[:] = saved` — **investigated and deliberately
  left refused**, for real-correctness reasons discovered by hand-
  verifying the actual function body end-to-end (not just checking the
  eligibility gate in isolation, which this occurrence WOULD have
  passed under a naiver version of the fix). `saved = orig[:]` two
  lines above types `saved` as `char *`
  (`_infer_simple_expr_ctype`'s `if isinstance(e, SliceExpr): return
  'char *'` — this narrow coroutine-body model reads EVERY slice as a
  string; a separate, pre-existing, unfixed gap — see the "Verification"
  section of the earlier `sys.stderr` status update above, which
  independently confirmed the identical gap: `stderr = sys.stderr`
  lowering to an undeclared identifier). A first version of this fix
  blindly reinterpret-cast any non-`MojoList*`-typed RHS identifier to
  `MojoList*` (mirroring an existing, accepted ambiguous-boxing
  convention used elsewhere in this codegen, e.g. the plain GIMPLE
  path's `DelStmt` `SliceExpr` branch) — for `saved` specifically, this
  SYNTAX-compiled (`g++ -fsyntax-only` accepted it: an explicit
  C-style pointer cast is always legal) but would have been a genuine
  runtime memory-corruption bug: `mojo_list_clear`/`mojo_list_extend`
  called on a real `char *` string reinterpreted as `MojoList *` — the
  exact "silently wrong or broken code" this whole codegen otherwise
  refuses to emit. Worse, this specific hazard is HIDDEN at the point
  the fix is applied: `_cpp_try_stmt` translates a `finally:` block's
  statements BEFORE the preceding `try:` block's (see its own
  docstring/body — `finally_lines` is computed first), so at the point
  `orig[:] = saved` (inside `patch_list`'s `finally:`) is translated,
  `saved` is NOT YET in `declared` at all (it's only assigned inside
  the `try:` block, not yet processed) — it reads back as untracked
  (`None`), not as its eventual real type. Treating "untracked" as
  "assume it's a list" (the permissive rule this fix DOES still use for
  the ASSIGNMENT TARGET side, where it's safe and mirrors existing
  precedent) would have silently done the wrong thing here specifically
  because of this ordering quirk. Fixed by holding the RHS identifier
  to a STRICTER bar than the target: only lower via `mojo_list_extend`
  when `declared[name] == 'MojoList *'` exactly (positive proof,
  no ambiguous-default fallback) — `saved` fails this check (it's
  `None`, not `'MojoList *'`, at translation time), so `patch_list`
  correctly falls through to the pre-existing generic refusal, exactly
  as it should given the RHS really is a string here. Fixing the
  underlying `finally`-before-`try` ordering (so `saved`'s real,
  eventual type WOULD be visible) or the separate SliceExpr-reads-as-
  string gap are both real, larger, un-narrow steps — not attempted.

**Verification:** isolated repros for both the safe-cast path (a
`MojoList*`-typed parameter assigned via cross-function call-site
inference) and the empty-list path compile to valid C++ (`g++
-std=c++20 -fsyntax-only`, 0 errors). The real `iter_builtin_types`
occurrence (isolated to just its own `subs[:] = []` shape) also passes
the eligibility gate and compiles to valid C++. The real `patch_list`
occurrence was hand-verified (via `MOJO_DEBUG=1`) to still be refused,
confirming the type-guard did its job rather than emitting the earlier
draft's unsafe cast. Full 5-part CLAUDE.md gate run and passed:
`test_gimple.py` (247/247), `test_module_cache.py` (76/76), `make
check-selfhost` clean, from-scratch `libmojostdlib.dylib` rebuild (0
`skip <module>:` lines), `compile_stdlib.py -j8` (664/664, 0
unexpected — unchanged count).

## Status (updated 2026-08-07, non-self-MemberExpr FIXED for the `sys.stderr`/`stdout`/`stdin` shape)

**The specific confirmed non-`self`-`MemberExpr` occurrence (`sys.
stderr = None`, `Lib/test/test_faulthandler.py`'s `check_stderr_none`)
is now FIXED.** `_cpp_stmt`'s `AssignStmt` handling gained a narrow,
structurally-scoped case for `sys.stderr`/`sys.stdout`/`sys.stdin` as
an assignment target, ahead of the generic refusal.

**Root cause / why this narrow shape (and only this shape) is safe to
fix by eliding it:** `sys` has no real backing value ANYWHERE in this
coroutine codegen — `_cpp_expr`'s `IdentExpr` case has no case at all
for a bare module name (a bare `sys.stderr` READ outside one specific
position already lowers to a nonsensical, undeclared `sys` C++
identifier — confirmed by hand: `stderr = sys.stderr` inside a
generator body still fails to compile, unchanged, a separate
pre-existing gap on the READ side, not attempted here). The ONLY place
this codegen gives `sys.stderr` any meaning at all is `_is_sys_stderr`/
`_gen_print`'s structural, compile-time-only match of `file=sys.stderr`
as a `print()` keyword argument — never a real runtime value. Given
that, an assignment `sys.stderr = <val>` has nothing real to change:
eliding it (after still evaluating the RHS for side effects, `(void)
(val);`) can't discard any behavior this codegen could otherwise
observe, and lets the surrounding function's OTHER statements be
reached and judged on their own merits instead of refusing the whole
function solely for this one line. This reasoning is intentionally
narrow to `sys.{stderr,stdout,stdin}` specifically — every OTHER
non-`self` `MemberExpr` assignment target (a real object's attribute)
remains refused unchanged, since a real object might have an
observable backing value elsewhere in the program that silent elision
would corrupt.

**Verification:** isolated repro (`sys.stderr = None; print("after")`
inside a generator) now compiles to valid C++ (`g++ -std=c++20
-fsyntax-only`, 0 errors) — previously refused at the eligibility gate.
`check_stderr_none` itself, run through the real file, is no longer
refused at the gate either — but does NOT fully compile end-to-end,
confirmed via an isolated repro of its exact body: the SAME pattern as
every other partial fix in this cluster (task #149's `imaplib.py`,
task #150's original list-unpack fix on `gc_inspection.py`) — other,
separate, pre-existing gaps in the same method remain: the `stderr =
sys.stderr` READ (line 829, noted above), `self.assertRaises(...)`/
`self.assertEqual(...)` (method calls on `self`, out of this narrow
`self.<scalar field>`-reads-only model's scope), and `with ... as cm:`
binding a method-call result. Confirmed via direct isolated compile:
```
error: use of undeclared identifier 'sys'        (stderr = sys.stderr)
error: member reference base type 'int64_t' ...  (cm.exception)
error: called object type 'int' is not a function ...  (self->assertEqual(...))
```
Full 5-part CLAUDE.md gate run and passed: `test_gimple.py` (247/247),
`test_module_cache.py` (76/76), `make check-selfhost` clean, from-
scratch `libmojostdlib.dylib` rebuild (0 `skip <module>:` lines),
`compile_stdlib.py -j8` (664/664, 0 unexpected — unchanged count).

## Status (updated 2026-08-07, new sub-case found: slice-assignment targets)

**Third confirmed unsupported target shape, found while re-verifying
this doc's fixed/unfixed state against the real `CODEGEN_generator_
function_Lib_test__test_eintr.md` cluster file**: a SLICE-subscript
assignment target (`orig[:] = saved`, `x[a:b] = y`) parses to
`mojo_compiler.py`'s `SliceExpr` node, NOT `SubscriptExpr` — confirmed
directly:
```
>>> parse("orig[:] = saved")
AssignStmt(target=SliceExpr(obj=IdentExpr('orig'), start=None, stop=None, step=None), ...)
```
`_cpp_stmt`'s `AssignStmt` handling (gimple_codegen.py ~line 22755) only
special-cases `isinstance(s.target, SubscriptExpr)` for the "already
supported" arbitrary-index-assignment path (`arr[i] = val`) — a
`SliceExpr` target falls through to the same generic "only a plain
identifier assignment target is supported" refusal as the (now mostly
understood) tuple/list-unpack and non-`self`-`MemberExpr` cases.
Two independent real occurrences, both in `Lib/test/support/__init__.
py`, both reached transitively (not themselves one of the 41 cluster
target files, but both confirmed via `MOJO_DEBUG=1 python3 mojo.py
build Lib/test/_test_eintr.py`):
- `patch_list(orig)` (line 1933): `orig[:] = saved`
- `iter_builtin_types()` (line 2794, inner loop): `subs[:] = []`

Meets this project's "recurs ≥2 times" bar for a documented hard-bug
sub-case (promoted here rather than a new file, since it's the same
family — "AssignStmt target shape not yet handled" — as this doc's
existing tuple/list-unpack and non-`self`-attribute cases). Not fixed
in this pass; a real fix would lower `x[start:stop] = value` via
whatever runtime slice-assignment helper the plain (non-generator)
codegen path uses for the equivalent construct (not independently
checked here whether one already exists) — likely a smaller, more
self-contained step than the non-`self`-`MemberExpr` case below, since
it's still "write into a container the generator itself owns a
reference to," not "write into an arbitrary external object's
attribute."

## Status (updated 2026-08-07)

**PARTIALLY FIXED** (task #150) — the list-pattern-unpack case
specifically. Root-caused 2026-08-06 while classifying the
`CODEGEN_generator_function_Lib_*.md` cluster (tasks #95-135) — found in
`Lib/test/crashers/gc_inspection.py`'s own generator `g`, fixed
2026-08-07.

`_cpp_stmt`'s `AssignStmt` case widened its existing `isinstance(s.
target, TupleExpr)` unpacking branch to `isinstance(s.target, (TupleExpr,
ListExpr))` — `ListExpr` and `TupleExpr` share the exact same `.elements`
field shape (see `mojo_compiler.py`), and `[a] = ...`/`[a, b] = ...` is
semantically identical to `a, = ...`/`a, b = ...` (Python's other, less
common unpacking-target spelling), so the EXISTING decomposition logic
(already handling `MojoList*`-returning calls, unresolved-call stubs,
and the plain-subscript fallback) applies completely unchanged — no new
lowering logic was needed, just widening which target-node TYPE reaches
it. This doc's own minimal repro (`[x] = [42]; print(x)` inside a
generator) now passes the eligibility gate (previously refused with
"only a plain identifier assignment target is supported").

**NOT fixed, still refused** (per the "What a fix needs" section
below, correctly identified at diagnosis time as a bigger, separate
step): non-`self` `MemberExpr` assignment targets — e.g. `sys.stderr =
None` (confirmed in `Lib/test/test_faulthandler.py`'s
`check_stderr_none`). `self.field = val` and `arr[i] = val` (subscript)
targets were ALREADY supported before this pass (found while
implementing this fix — the doc's "What a fix needs" section slightly
understated existing coverage here); only a MODULE-level or otherwise
non-`self` attribute-assignment target remains unsupported. Not
attempted — assigning into an arbitrary object's attribute (as opposed
to reading `self.<scalar field>`, or writing `self.<field>` which IS
supported) has no representation in this narrow scalar-only
generator-body model, and is a meaningfully bigger step exactly as
originally diagnosed.

## Verification

Hand-verified via `compile_to_gimple_with_cpp` + `g++ -fsyntax-only`:
`[x] = [42]; print(x)` inside a generator now passes the eligibility
gate. The exact literal-RHS shape in this specific micro-repro still
hits a SEPARATE, PRE-EXISTING, unrelated gap in `_cpp_expr`'s `ListExpr`
lowering (a literal list/tuple value lowers to a C++ brace-init-list,
which isn't itself a subscriptable expression) — confirmed via `git
stash` that the IDENTICAL gap already existed for `TupleExpr` targets
with a literal tuple RHS (`(x,) = (42,)`) on unmodified code, so this
is not a regression, just a pre-existing limitation this fix's target-
shape widening now ALSO inherits unchanged (not worsened) for the list-
target spelling. The realistic corpus shape this branch is actually
exercised against (a `MojoList*`-returning function call as the RHS,
e.g. tokenize.py's `encoding, consumed = detect_encoding(readline)`
style) was already correctly handled before this fix for `TupleExpr`
and is now handled identically for `ListExpr`.

## Gate

All five gates in CLAUDE.md's quality-gate section passed: `test_gimple.
py` (247/247), `test_module_cache.py` (76/76), `make check-selfhost`
clean, from-scratch `libmojostdlib.dylib` rebuild (0 `skip <module>:`
lines), `compile_stdlib.py -j8` (664/664, 0 unexpected — unchanged
count).

## Original diagnosis (unfixed-era notes, kept for history)

Not attempted at the time — see "What a fix needs" below.

## Symptom

```
[gimple_codegen] generator 'g' not eligible for C++ coroutine path, falling back to honest refusal: only a plain identifier assignment target is supported
[gimple_codegen] generator 'iter_builtin_types' not eligible for C++ coroutine path, falling back to honest refusal: only a plain identifier assignment target is supported
[gimple_codegen] generator 'patch_list' not eligible for C++ coroutine path, falling back to honest refusal: only a plain identifier assignment target is supported
```
Same fatal-whole-module-`RuntimeError`-escalation pattern documented in
the sibling hard-bug docs for this cluster (`CODEGEN_generator_struct_
typed_param_refused.md`, `CODEGEN_generator_raise_non_static_exception_
class.md`) when the refused generator is module-level.

## Root cause (confirmed via `gc_inspection.py`'s source)

```python
def g():
    marker = object()
    yield marker
    [tup] = [x for x in gc.get_referrers(marker) if type(x) is tuple]
    print(tup)
    print(tup[1])
```
`[tup] = [x for x in ...]` is a LIST-PATTERN destructuring assignment
(unpacking a single-element list into `tup`) — a real, if slightly
unusual, Python idiom equivalent to `tup, = [...]`/`(tup,) = [...]`. The
coroutine codegen's assignment-statement lowering inside a generator
body (`_cpp_stmt`'s `AssignStmt` case) only handles a bare `IdentExpr`
target — any other target shape (list-pattern unpack, tuple unpack,
subscript assignment, attribute assignment) is refused wholesale with
this one generic message, rather than each shape getting its own
specific diagnosis. (The plain, non-generator/non-coroutine codegen path
DOES support several of these target shapes — this is specifically a
narrower/less mature area of the coroutine `.cpp` emission path, same
overall theme as this cluster's other gaps.)

## Confirmed occurrences

- `Lib/test/crashers/gc_inspection.py`: `g` — `[tup] = [...]` (list-
  pattern unpack). One of this cluster's own 41 target files; see
  `bugs/CODEGEN_generator_function_Lib_test_crashers_gc_inspection.md`.
- `Lib/test/support` (exact submodule not pinned down, reached
  transitively while diagnosing `Lib/test/_test_eintr.py`, not itself
  one of this cluster's 41 targets): `iter_builtin_types` and
  `patch_list` — target shape not independently read from source in
  this pass, only the refusal message observed.
- `Lib/test/test_support.py`: `save_restore_warnings_filters` — target
  shape not independently read from source in this pass. One of this
  cluster's 41 target files; see `bugs/CODEGEN_generator_function_Lib_
  test_test_support.md`.
- `Lib/test/test_faulthandler.py`: `FaultHandlerTests.check_stderr_none`
  — `sys.stderr = None` (a MODULE-ATTRIBUTE assignment target, not a
  tuple/list unpack — confirms the refusal is general to ANY non-
  `IdentExpr` target, not just unpack patterns). One of this cluster's
  41 target files; see `bugs/CODEGEN_generator_function_Lib_test_test_
  faulthandler.md`.

## What a fix needs

`_cpp_stmt`'s `AssignStmt` handling for a generator body would need
dedicated lowering for at least: tuple/list-pattern unpack (`a, b = ...`
/ `[a] = ...`) — likely straightforward by decomposing into N
single-target assignments against a temporary, mirroring how the plain
codegen path already does it — and, separately, subscript/attribute
assignment targets (`self.x = ...`, `d[k] = ...`), which are a
meaningfully bigger step (the existing `_gen_cpp_generator_unit`
docstring already flags "mutating a self field" as explicitly out of
this step's current scope for the SEPARATE reason of self-field write
support, not this assignment-target-shape issue — worth keeping the two
distinct if picked up, since fixing target-shape support doesn't imply
self-field-write support is also ready). Not attempted here.

## Minimal repro

```python
def g():
    yield 1
    [x] = [42]
    print(x)

def main():
    for v in g():
        print(v)

main()
```
Expected (per root cause above): `g` refused at the generator-
eligibility pre-filter with "only a plain identifier assignment target
is supported", before any C++ is emitted.
