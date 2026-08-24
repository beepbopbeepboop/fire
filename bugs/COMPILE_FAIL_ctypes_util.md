# COMPILE_FAIL: Lib/ctypes/util.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/ctypes/util.py`

## Status (2026-08-24): not re-verified this session; root cause unrelated to the fix landed

This session landed `bugs/COMPILE_FAIL_ctypes_macholib_dyld.md`'s
targeted fix (coroutine-body local/yield typing derived from a
callee's trusted return type, in `gimple_cpp_core.py`/
`gimple_exprtypes.py`). This file's own documented blocker (below) is
entirely in a different subsystem — bare package-import resolution
(`_module_candidate_paths` not trying `<pkg>/__init__.py` for a bare
`from ctypes import cdll`) and from-import binding of module-level
VALUES — with zero overlap with coroutine/generator codegen, so no
behavior change is expected here. A full re-run was started
(`python3 mojo.py build .../ctypes/util.py`) but not completed within
this session's time budget — this file's own doc history already
notes multi-minute-to-9-minute build times on a loaded machine. Left
unverified rather than reporting a guessed result; re-run standalone
to confirm before any future fix attempt on this doc's own root cause.

## Status (re-verified 2026-08-23, triage pass): identical failure; root cause refined into three stacked gaps

Re-ran `python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/
ctypes/util.py`: byte-identical failure — same two errors at the same
lines (`util.py:500`/`502`, `variable or field '_t21' declared void` /
`invalid use of void expression`), `cdll` still lowered as the generic
weak int64_t stub, and the generated code at line 500 still
dereferences `_funcptr_cdll` (`_t20 = _funcptr_cdll; _t21 = *_t20;`).
Also re-confirmed `python3 mojo.py build .../Lib/ctypes/__init__.py`
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

Re-verified fresh via `python3 mojo.py build`. Symptom is byte-for-byte
identical to the 2026-08-06 finding below: same two errors at the same
lines (`util.py:500`/`502`, `variable or field '_t21' declared void` /
`invalid use of void expression`), and the generated `.ci` still shows
`cdll` lowered as the same generic weak int64_t-returning stub
(`__attribute__((weak)) int64_t cdll (...) { mojo_print (...); return
(int64_t)0; }`). Notably, `ctypes/__init__.py` itself now compiles
clean end-to-end (`python3 mojo.py build .../ctypes/__init__.py` exits
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
