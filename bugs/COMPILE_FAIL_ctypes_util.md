# COMPILE_FAIL: Lib/ctypes/util.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/ctypes/util.py`

## Status (re-verified 2026-08-26, wtOpencode_genlib3): consistent with the entry below; still not closed — whole-program build still watcher-bound, zero util.py-attributed errors

Fresh safety-wrapped attempt against current master (f0f6e78): two runs
(300s and 900s wall caps, RSS tripwire 6GB). First run killed at the
300s cap at only **819MB**; second run processed the closure further
than ever recorded here (collections → inspect → glob → shutil all
soft-fallbacked to source interpretation) before being killed at the
**900s** cap at 4.6GB RSS — same monotonic late-closure RAM growth,
slower onset than the 6.26GB@16min of the entry below, likely machine
contention (5 concurrent agent builds). `grep 'error:'` over both full
partial logs: only 4 lines, ALL soft structural fallbacks in OTHER
modules (`collections` Counter-subscript-store, `inspect`
OrderedDict-subscript-store, `glob` generator-method-as-value,
`shutil` ambiguous sibling `open`) — **zero** mentions of
`ctypes/util`. The doc's two remaining items are unchanged: (a) no
exit-0 whole-program build within any safety budget (memory/time-bound
by design, `_module_stmts` retention + interpreted fallbacks), and
(b) compiled-mode `cdll.load(...)` needs the callable/class-object
VALUE representation (`return self._dlltype(name)` through a stored
class ref still lowers to `(int64_t)0` + `mojo_fnptr_call_N(NULL,...)`
in gimple_gen_exprs.py's documented placeholder branch) — feature-
sized, deliberately NOT attempted per the entry below. Note the
failing lines remain dead test-only code guarded by
`os.name == "nt"`. No code change. Doc kept open.

## Status (re-verified 2026-08-26, wtOpencode_ctypesutil2): gaps #2/#3 fixes re-verified fresh; gap #3's routing found DEAD and FIXED (phantom-field minting); remaining blocker narrowed to class-ref-as-value + a whole-program RSS runaway

Re-verified against current master past d3e758a (both of this doc's
remaining gaps' fixes). Three findings this pass:

1. **Full build still does not complete — now MEMORY-bound, not
   error-bound.** Four safety-wrapped attempts (wall caps 450s/600s/900s;
   final run 1500s cap) all processed the transitive closure further than
   ever recorded here — os, ctypes/__init__, collections, inspect, glob,
   shutil all lowered/fell back WITHOUT A SINGLE hard `error:` line in any
   partial log (grep 'error:' == 0 throughout; vs **265** hard errors on
   2026-08-24) — and every run was then watcher-killed before gcc. The
   last run was killed by the **6GB RSS tripwire itself** (6.26GB at
   ~16min, growth accelerating during late-closure processing after
   shutil's fallback), not by the wall clock: RAM now grows monotonically
   with closure size (per-module parse trees are retained whole-build by
   design in `_module_stmts`, plus fallback modules execute interpreted).
   Note for future agents: `ulimit -v` is a NO-OP on this macOS
   (`cannot modify limit`); the RSS watcher is the only real guard. No
   util.py-attributed error was ever observed. Not marked resolved (no
   exit-0).

2. **Gap #3's fix (d3e758a's unknown-member→`__getattr__` routing) was
   DEAD CODE as landed — root-caused and FIXED this session**
   (commit `61bff2c`). Minimal single-file repros of exactly the
   LibraryLoader shape showed: the two READ-side field-minting passes in
   gimple_module_gen.py (`_collect_self_reads`, and
   `_scan_body_for_local_field_access`'s typed-local scan — which walks
   into function bodies and mints from top-level constructor assignments
   like `cdll = LibraryLoader(CDLL)`) registered every literally-spelled
   unknown member as a phantom `int` field BEFORE body lowering, so
   `cdll.msvcrt` took the plain known-field branch (uninitialized
   `_t1->msvcrt` scalar read; the generated struct even grew
   `int msvcrt;` + dead dispatch/repr entries). The commit adds:
   never mint phantom fields for member READS on a struct whose methods
   include `__getattr__` (write-side `self.X = ...` minting untouched —
   genuinely-assigned members still resolve statically). Verified
   END-TO-END with a class-ref-free repro (`Cfg.__getattr__` returning
   `prefix + name`; built binary prints `cfg:anything`/`cfg:other`,
   byte-identical to real CPython, exit 0). Gate: test_gimple 256/256,
   test_module_cache 76/76, check-selfhost clean, stdlib dylib rebuild
   EXIT=0 / 0 skips.

3. **Gap #2's fix verified working mechanically; the LAST runtime blocker
   is a pre-existing structural hole, precisely located.** With the
   phantom-mint fix in place, `from lib import cdll` lowers to real
   `_root_globals.cdll` reads and `cdll.load_library("zlib")` emits a
   direct call — the cross-module VALUE binding genuinely works.
   But `LibraryLoader.__getattr__` bodies do `return self._dlltype(name)`
   — a CALL THROUGH A STORED CLASS REFERENCE, and a bare class name used
   as a value still lowers to `(int64_t)0 /* class ref CDLL as value */`
   (gimple_gen_exprs.py's documented zero-placeholder branch), so
   `mojo_fnptr_call_1(NULL, ...)` segfaults at runtime. Same
   "callable/class-object value representation" family as the tracked
   LambdaExpr-as-value docs — feature-sized, deliberately NOT attempted.
   Until that exists, `print(cdll.msvcrt)` / `cdll.load("msvcrt")` cannot
   run correctly in compiled mode EVEN THOUGH they now lower cleanly.
   (Secondary observation, unattempted: unannotated forwarding params
   like `load_library(self, name)` infer `int64_t` where the call site
   provably passes char * — adjacent to the tracked param-inference
   families.)

Doc kept open: file still has no verified end-to-end build (RSS-bound)
and compiled-mode `cdll` usage still needs the callable-class-value
machinery. But the picture is materially better than the entry below:
zero attributed errors anywhere in the closure, gap #2 confirmed live,
gap #3's read path now genuinely functional.

## Status (re-verified 2026-08-25, wtOpencode_group3): consistent with the entry below — no util.py-attributed errors; full build again exceeded this session's watcher budget

Fresh safety-wrapped `fire.py build` attempt: watcher-killed at the
300s cap during transitive-import processing (machine contended by
concurrent agents' builds), but `grep 'ctypes/util.py:.*error:'` over
the partial log is **0** throughout — same picture as the 2026-08-25
entry below. Gaps #2/#3 (from-import binding of module-level VALUES;
`LibraryLoader`'s dynamic attribute surface) remain genuinely unfixed,
unattempted, and are only reachable once the other modules' unrelated
errors stop masking them. No code change. Doc kept open.

## Status (re-verified 2026-08-25): unchanged; gap #1's fix still holds, still no `ctypes/util.py`-specific errors

Re-ran `python3 fire.py build /Users/mrs/net/Python-3.14.6/Lib/
ctypes/util.py` fresh against current master (past the struct-method
cross-call scalar contract "Pass 1.3e", generator-consumption-ordering
fixed-point retry + defaults-aware arg padding, `**kwargs`-forward
slot-alignment fix, and coroutine-body `int()`/`float()` builtin
support landed since the 2026-08-24 entry below — none of these target
this doc's remaining gaps #2/#3, module-value from-import binding and
`LibraryLoader`'s dynamic attribute surface). Two full-build attempts
under this session's safety-wrapped watcher (300s then 450s wall-clock
cap, RSS stayed low/no runaway both times — this machine was also
running several other concurrent agents' builds) both got killed by the
watcher before the whole-program build finished or failed on its own;
however, in both partial runs `grep -c "ctypes/util.py:.*error:"` was 0
throughout, consistent with the 2026-08-24 finding that `ctypes/
util.py`'s own compile unit has zero errors now. Not re-confirmed to a
final exit code this pass (environment too slow/contended within the
safety budget to let the full transitive build finish); no evidence of
regression. Gaps #2/#3 remain genuinely unfixed and unattempted — same
assessment as below. Doc kept open.

## Status (2026-08-24): gap #1 (bare package-import resolution) FIXED; util.py's own documented error is GONE; file still does not build end-to-end (gaps #2/#3 below remain, plus unrelated errors in other transitively-imported modules)

The commit landed this session (see `bugs/COMPILE_FAIL_ctypes_
macholib_dyld.md`'s 2026-08-24 entry) turned out to include a real fix
for this doc's own **gap #1**: `gimple_gen_resolve.py`'s
`_module_candidate_paths` now also tries the `<dir>/<name>/__init__.
<ext>` package form for a BARE (non-dotted) module name, mirroring
what it already did for dotted names and what the interpreter side
already did — exactly the fix this doc's 2026-08-23 entry identified
as needed. (It also walks the importer's ancestor directories, bounded
6 levels, for nested-package-relative imports — found via `dyld.py`'s
own `from ctypes.macholib.framework import framework_info`.)

Re-ran `python3 fire.py build /Users/mrs/net/Python-3.14.6/Lib/
ctypes/util.py` end-to-end (full run, ~4 min): **the previously-
documented failure at `util.py:500`/`502` (`variable or field '_t21'
declared void'` / `invalid use of void expression`, from `cdll` being
lowered as the generic weak int64_t stub) no longer reproduces —
`ctypes/util.py` itself now has ZERO errors.** `ctypes/__init__.py`
is now genuinely inline-compiled into the whole-program unit (confirms
gap #1 is fixed, not just coincidentally unreached).

`python3 fire.py build` for this file still exits 1 overall: 265 real
compiler errors remain, but ALL in other transitively-imported
modules (`_collections_abc.py`, `argparse.py`, `ast.py`, `dataclasses.
py`, `operator.py`, `os.py`, `pickle.py`, `types.py`, etc.) — none at
`ctypes/util.py`'s own lines. Some of these (e.g. `ctypes/__init__.py`
itself: `reprlib_Repr_repr*` "undeclared here") are the same already-
tracked bare-name-collision class noted in `bugs/COMPILE_FAIL_Lib_
socket_...md`'s 2026-08-24 entry and `bugs/hard/CODEGEN_same_bare_
name_struct_collision_across_modules.md` — not new. Gaps #2 (from-
import binding of module-level VALUES) and #3 (`LibraryLoader`'s
dynamic attribute surface) below remain genuinely unfixed and
unattempted — not verified whether they'd still block `cdll` usage on
their own now that gap #1 no longer masks them, since the build never
gets isolated enough from the other modules' unrelated errors to tell
cleanly. Quality gate for the fix itself verified clean: `test_gimple.
py` 252/252, `test_module_cache.py` 76/76, `make check-selfhost`
clean, stdlib dylib rebuild 0 skips.

Doc kept open (file still doesn't build end-to-end) — gap #1's fix is
real progress, not a full resolution.

## Status (re-verified 2026-08-23, triage pass): identical failure; root cause refined into three stacked gaps

Re-ran `python3 fire.py build /Users/mrs/net/Python-3.14.6/Lib/
ctypes/util.py`: byte-identical failure — same two errors at the same
lines (`util.py:500`/`502`, `variable or field '_t21' declared void` /
`invalid use of void expression`), `cdll` still lowered as the generic
weak int64_t stub, and the generated code at line 500 still
dereferences `_funcptr_cdll` (`_t20 = _funcptr_cdll; _t21 = *_t20;`).
Also re-confirmed `python3 fire.py build .../Lib/ctypes/__init__.py`
builds clean end-to-end (exit 0) and, compiled standalone, gives
`cdll` a REAL type (`_global_var_types['cdll'] == 'LibraryLoader *'`,
stored in `_root_globals.cdll` with a typed accessor) — so upstream
compile health is no longer the blocker; the cross-module view is.

Refined root cause — three independent gaps stack up, and ALL must be
fixed for this file to build:

1. **Bare package imports never resolve to `<pkg>/__init__.py`.**
   `_module_candidate_paths` (gimple_gen_resolve.py) tries
   `<dir>/<name>.{py,mojo}` for every search dir but only appends the
   `<name>/__init__.{ext}` package form for DOTTED module names — so
   `from ctypes import cdll` inside util.py never even locates
   `/Users/mrs/net/Python-3.14.6/Lib/ctypes/__init__.py`, and
   ctypes/__init__ is never inline-compiled into util.py's whole-
   program unit at all (`LibraryLoader` absent from struct_field_types,
   `cdll` absent from the shared `_global_var_types`). The interpreter's
   own resolution (myinterpreter.py's `rel_pkg_path`) and imports.py's
   `_find` both DO try package-`__init__` forms for bare names — the
   compiled path is the outlier. (Note imports.py only tries `.mojo`
   there, not `.py`.)
2. **No from-import path for module-level VALUES.** Even with the
   package resolved, `_gen_stmt_FromImportStmt` can only register
   function signatures (or submodule markers); binding a cross-module
   global VALUE (a struct instance like `LibraryLoader(CDLL)`) into
   function scope has no lowering at all — it would need to read the
   owning module's globals-struct field (the `_<mod>_globals.<name>`
   machinery that MemberExpr-on-module already uses).
3. **`LibraryLoader`'s attribute surface is genuinely dynamic.**
   `cdll.msvcrt` / `cdll.load(...)` go through LibraryLoader's own
   `__getattr__` in real Python (any attribute = load that DLL); the
   struct model has no representation for per-instance dynamic
   attributes beyond the runtime `_mojo_dispatch_getattr` fallback.

Fixing only #1 was judged NOT worth landing alone under this session's
no-half-measures constraint: it changes which sources get inline-
compiled across every bare-package import in every build (broad blast
radius) while fixing none of this doc's errors by itself (#2/#3 would
still leave `cdll` unresolved). DOCUMENTED-NOT-FIXED; failing code
remains dead test-only `def test():` never invoked by anything.

## Status (updated 2026-08-09)

Re-verified fresh via `python3 fire.py build`. Symptom is byte-for-byte
identical to the 2026-08-06 finding below: same two errors at the same
lines (`util.py:500`/`502`, `variable or field '_t21' declared void` /
`invalid use of void expression`), and the generated `.ci` still shows
`cdll` lowered as the same generic weak int64_t-returning stub
(`__attribute__((weak)) int64_t cdll (...) { mojo_print (...); return
(int64_t)0; }`). Notably, `ctypes/__init__.py` itself now compiles
clean end-to-end (`python3 fire.py build .../ctypes/__init__.py` exits
0) — a real improvement since this doc's last update — but that alone
wasn't enough to fix `util.py`'s cross-module view of `cdll`: nothing
in this session's fixes touched cross-module resolution of a MODULE-
LEVEL VALUE (as opposed to a function/class), so `cdll = LibraryLoader
(CDLL)`'s real struct-instance type still isn't visible to `util.py`'s
own compile. Root cause and priority assessment unchanged from below —
still the same structural, already-tracked gap, still dead test-only
code. No fix attempted (matches the "known structural gap" category:
cross-module resolution of a module-level value, not a function).

## Status (updated 2026-08-06)

Investigated 2026-08-06. Root-caused; not fixed — traces back to an
already-tracked, broader cross-module resolution gap. Low priority: the
failing code is dead test-only code, never reached by any real import.

```
error: variable or field '_t21' declared void
error: invalid use of void expression
```

at:
```python
################################################################
# test code

def test():
    from ctypes import cdll
    if os.name == "nt":
        print(cdll.msvcrt)
        print(cdll.load("msvcrt"))   # <- here
        print(find_library("msvcrt"))
    ...
```

## Root cause

`from ctypes import cdll` pulls in `cdll`, which in the real
`ctypes/__init__.py` is a MODULE-LEVEL VALUE (a struct instance, not a
function or class): `cdll = LibraryLoader(CDLL)`. Cross-module import
resolution here can't determine `cdll`'s real type, so it falls back to
emitting a generic weak stub for the unresolved symbol:

```c
#ifndef cdll
__attribute__((weak)) int64_t cdll (...) { mojo_print ((char *)"cdll: unavailable in compiled mode"); return (int64_t)0; }  /* stub from ctypes */
```

i.e. `cdll` gets treated as an unresolved CALLABLE returning `int64_t`,
not as a struct instance with a `.load(name)` method. `cdll.load("msvcrt")`
then lowers to a dynamic-dispatch call on that broken stub value, whose
return type resolves to `void` — and `print(<void-typed-expr>)` is
invalid C, producing the two errors above.

This is a variant of the SAME underlying gap already tracked for
`ctypes/__init__.py` itself (bugs/COMPILE_FAIL_ctypes___init__.md, task
#39) — that file's own compile has multiple unresolved issues
(`__ctype_le__`/`__ctype_be__` dynamic attributes, the CFUNCTYPE varargs-
packing bug), any of which could be why `ctypes/__init__.py`'s own
`LibraryLoader`/`cdll` never gets far enough to be visible to
`util.py`'s cross-module import resolution as a real, typed value. Not
independently root-caused further than that — `cdll`'s resolution
failure is downstream of `ctypes/__init__.py`'s own compile health, not
a bug specific to `util.py`.

## Priority note

The failing code is `def test():`, explicitly dead test/demo code at the
bottom of the file (guarded `if os.name == "nt":`, and this `test()`
function itself is never called by anything outside itself — no
`__main__` guard even invokes it in this file). Low priority relative to
real, reachable code paths. Worth revisiting once `ctypes/__init__.py`
(task #39) has a real, resolvable `cdll`/`LibraryLoader` — this file may
simply compile clean once that upstream dependency does, without any
change needed here at all.
