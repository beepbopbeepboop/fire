# CODEGEN_generator_function: Lib/test/test_dbm.py

## Status (updated 2026-08-26, worktree fix/rest-remainder16 — re-verified unchanged)

Fresh re-verify against this worktree (branched from master `a913ab8`).
Isolated compile (`do_imports=False`) of `test_dbm.py` succeeds with no
`RuntimeError` (matches the 2026-08-24 fix); pulled the generated
`dbm_iterator` coroutine `.cpp` and confirmed via `g++-mp-15 -std=c++20
-fsyntax-only`: zero errors. Directly inspected the emitted C++ body:
it is literally `co_return;` with nothing else — confirms the
"iterable not statically list/dict-typed" fallback still silently
compiles the whole `for name in dbm._names:` loop (and everything
inside it, including the `__import__(name, fromlist=['open'])` call) as
dead code, exactly as the 2026-08-24 entry documented. The `.ci` (plain
part) has zero occurrences of `__import__` or `dbm.` symbol references
needing resolution, consistent with the loop body never actually being
emitted. So the `__import__` blocker is not "fixed" — it's simply never
reached because the loop around it compiles to nothing; this generator
will not iterate correctly at runtime once linked, matching the doc's
own honest caveat. No shared mechanism since 2026-08-24 changes this.
`test_dbm.py` as a whole (transitive `do_imports=True` build) still not
independently re-verified this pass (would require the full-build RAM/
time budget for a file with a large `test.support` import graph);
nothing suggests its unrelated transitive-dependency errors have
changed. No change; doc stays open.

## Status (updated 2026-08-24, worktree fix/rest-remainder — the `'dbm' was not declared` gap FIXED; isolated coroutine TU now compiles with ZERO errors)

Root-caused the "outer-scope module-name resolution" family precisely
for the SPECIFIC shape this file hits (`for name in dbm._names:`, a
module-import name read as a bare, uncalled attribute VALUE — as
opposed to `os.pipe()`-style module-attribute CALLS, which already had
a "stub to 0" fallback): `gimple_cpp_core.py`'s `_cpp_expr` MemberExpr
case has an `obj_expr = ... else e.obj.name` shortcut that, whenever
the receiver is a bare `IdentExpr`, uses the raw Python name as C++ text
directly — bypassing `_cpp_expr`'s own IdentExpr resolution (which
already knows how to recognize a module-level global/import name)
entirely. `dbm` (from `import dbm`) hit exactly this: emitted as literal
`dbm` text, an undeclared C++ identifier.

Fixed: added the same "known early-global name, not a declared local,
stub to 0 (diagnosed)" check the CallExpr/MemberExpr branch already
uses for module-attribute CALLS (`os.pipe()`), applied here too, ahead
of the raw-text shortcut, for the uncalled-attribute-VALUE case.
Verified via a fresh isolated `compile_to_gimple_with_cpp(do_imports=
False)` + `g++-mp-15 -std=c++20 -fsyntax-only`: `test_dbm.py`'s own
`dbm_iterator` generator TU now compiles with **ZERO** g++ errors (was:
hard `'dbm' was not declared` failure). Caveat, honestly recorded: this
doesn't make `dbm_iterator` semantically correct — `dbm._names` (the
loop's iterable) isn't a real, resolvable `MojoList*`/`MojoDict*` in
this narrow body model either, so the existing (separate, pre-existing)
"iterable not statically list/dict-typed" fallback silently compiles
the whole `for` loop as dead code (0 iterations) — the generated C++ is
`int64_t name = 0; co_return;`, no loop at all. This is the SAME
already-documented "loop runs zero times, diagnosed" convention seen
elsewhere in this project (e.g. `Tools/unicode/gencodec.py`'s
`os.listdir` gap) — a real, honest compile fix, not a runtime-behavior
fix; `dbm_iterator` itself will not actually iterate real dbm backends
once linked.

The `__import__` (dynamic import call) blocker is UNCHANGED — a
separate, genuinely structural gap (dynamic import resolution), not
touched by this fix.

Full mandatory gate: `test_gimple.py` 252/252, `test_module_cache.py`
76/76, `make check-selfhost` clean, from-scratch stdlib dylib rebuild
EXIT=0 with 0 skip lines.

`test_dbm.py` as a whole still does not build (transitive dependency
closure has its own separate failures, not investigated here). Doc
stays open.


## Status (updated 2026-08-24 -- re-verified, unchanged)

Re-checked this session while triaging the C3 cluster. Both residual errors (`'dbm' was not declared`, `'__import__' was not declared`) are instances of the same outer-scope module-name-resolution gap _test_eintr.py hits with `os.pipe()` -- unaffected by this session's two landed fixes (stdin/stdout/stderr field-name escaping; more char* string methods in coroutine bodies), since neither adds general module-name resolution to the coroutine-body emitter. Still structural; untouched.


## Status (updated 2026-08-23 — PARTIAL)

ALL 9 previously-listed transitive-dependency errors (support/__init__.py
488/1184/1186/1420/1905-1908 + import_helper.py unlink) are fixed this
session; the file's own generator TU now compiles further and fails on
exactly TWO remaining errors, both in test_dbm_gen.cpp itself:
'dbm' was not declared in this scope (generator body referencing the
module-level `dbm` import) and '__import__' was not declared (dynamic
import call). Both belong to the same documented structural family —
arbitrary outer-scope/module-name resolution inside a generator's
separately-compiled translation unit — not narrow fixes. Gate verification (2026-08-23): `test_gimple.py` 250 passed / 0 failed;
`test_module_cache.py` 76 / 0; `make check-selfhost` clean; from-scratch
stdlib dylib rebuild EXIT=0 with **0** `skip <module>:` lines — matching
the pre-change baseline of exactly 0 skips.

## Status (re-verified 2026-08-11, unchanged classification, error count down further)

Re-ran against current master (154 commits past the 2026-08-09 note
below, incl. this session's own generator-body struct-construction fix
— see `bugs/CODEGEN_generator_function_Lib_test_test_doctest_test_
doctest.md` — which doesn't touch anything reachable from this file).
Error count has dropped again, from 29 to **8**. `test_dbm.py`'s own
generator (`yield mod`, line 34) still contributes zero errors/warnings
of substance (only `-Wunused-*`). All 8 remaining errors are still in
transitively-imported dependency files (`Lib/test/support/__init__.py`
lines 488/1184/1186/1420/1905-1908, `import_helper.py` line 50) —
`assignment to 'int64_t *' from 'int64_t' makes pointer from integer`,
`implicit declaration of function 'print_warning'`/`'unlink'`, and one
`expected ')' before ';' token` parse error. **Classification unchanged:
NOT a generator-codegen-cluster failure.** Still out of scope for this
cluster; not investigated further.

## Status (re-verified 2026-08-09, unchanged classification, error count down further)

Re-ran `python3 mojo.py build .../Lib/test/test_dbm.py` against current
master (140 commits past the 2026-08-07 note below). Error count has
dropped again, from 31 to **29**. `test_dbm.py`'s own generator (`yield
mod`, line 34) still contributes zero errors and shows no "not eligible"
refusal — its own translation unit only produces `-Wunused-*` warnings.
All 29 remaining errors are still in transitively-imported dependency files
(`Lib/test/support/__init__.py`, `import_helper.py`, `os_helper.py`),
dominated by `assignment to 'int64_t' ... from 'char *' makes integer from
pointer without a cast` (the same untyped-var-defaults-to-int64_t family
noted elsewhere in this cluster, but on the ordinary/non-generator codegen
path here). **Classification unchanged: NOT a generator-codegen-cluster
failure.** Still out of scope for this cluster; not investigated further.

## Status (updated 2026-08-07)

Re-verified against current master with a real rebuild. Still correctly
classified as **NOT a generator-codegen-cluster failure** —
`test_dbm.py`'s own generator still shows zero signal of a problem, and
`test_dbm.py`'s own source still contributes ZERO errors (down to 31
total errors from 39, all still in transitively-imported dependency
files). Not investigated further — out of scope for this cluster.

## Status (updated 2026-08-06, superseded above — error count has since dropped, same classification)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-30 `'dbm' was not declared` .cpp error no longer reproduces.
`test_dbm.py`'s own generator (`yield mod`, line 34) does not appear
anywhere in the current 39-error output and has no "not eligible"
refusal — it appears to compile cleanly.

**Classification: NOT a generator-codegen-cluster failure.** All 39
current errors are in transitively-imported dependency files, not
`test_dbm.py` itself — dominant pattern is `assignment to 'int64_t' from
'char *' makes integer from pointer without a cast` (20 occurrences) and
a couple of `'MojoBoundMethod' has no member named 'size'` (the same
property-access-leaves-a-bound-method family noted in `ipaddress.py`'s
current re-diagnosis). Not investigated further — out of scope for this
generator-codegen cluster.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/test/test_dbm.py
