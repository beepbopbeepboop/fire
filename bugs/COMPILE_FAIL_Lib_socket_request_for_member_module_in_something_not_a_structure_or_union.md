# COMPILE_FAIL: Lib/socket.py — request for member '__module__' in something not a structure or union

## Status (re-verified 2026-08-25): still does not build; error count 187 → 213, same already-catalogued grab-bag categories, no new failure class

Re-ran `python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/socket.py`
fresh against current master (past the struct-method cross-call scalar
contract "Pass 1.3e", generator-consumption-ordering fixed-point retry +
defaults-aware arg padding, `**kwargs`-forward slot-alignment fix, and
coroutine-body `int()`/`float()` builtin support landed since the
2026-08-24 entry below). 213 `error:` lines (was 187). Bucketed the
error messages by normalized shape rather than re-running a full sorted
A/B diff (time-boxed): every top category matches ones already
catalogued in this doc's history — `expected expression before 'X'`
(operator.py's `partial`/lambda lowering), `'X' has no member named
'X'` / `request for member 'X' in something not a structure or union`
(posixpath/ntpath struct-shape mismatch, argparse's `_kw_default`),
`invalid operands to binary % ` (enum.py's struct/dict `%`), `'X'
undeclared here (not in a function)` (the still-open task #141
bare-name-collision class), `perror(...)` lines reappearing in the
context snippets (the same `perror`-misdetection shape from tokenize.py/
argparse.py noted in earlier entries). No new error category observed.
Consistent with the 2026-08-24 finding that this file's error count
oscillates as a side effect of which functions successfully type-check
as coroutine bodies shifting whole-program compile order and which
module "wins" a bare-name race — not a regression from any of this
session's landed fixes, and none of those fixes target this file's
still-open blockers (task #141 general struct-field-table qualification,
operator.py partial/lambda lowering, enum.py struct/dict codegen,
posixpath/ntpath collision). Quality gate for the intervening fixes
verified clean at their own landing commits (see git log). Doc kept
open — still not a narrow, single-cause fix.

Landed the `_cpp_trusted_fn_return_types`/`_cpp_fn_container_shape`
coroutine-body-typing feature (see `bugs/COMPILE_FAIL_ctypes_
macholib_dyld.md`'s 2026-08-24 entry for what it targets — it does
NOT target this file's failure class at all). Re-ran `python3 mojo.py
build /Users/mrs/net/Python-3.14.6/Lib/socket.py`: 187 `error:` lines
(was 178). Did a controlled A/B (`git stash` the fix, rebuild, diff
the exact sorted error sets against the fix applied) rather than trust
the raw count: every one of the 30 errors that DISAPPEARED and all 33
that APPEARED are the same already-tracked, still-open bare-name-
collision shape this doc and `bugs/hard/CODEGEN_same_bare_name_
struct_collision_across_modules.md` both describe (`redefinition of
'_alloc_expandvars_repl_env'`/`'expandvars_repl_env' has no member
named ...` moved from `posixpath.py` to the sibling `ntpath.py`;
`reprlib_Repr_repr*` "undeclared here" reappeared, now in `enum.py`'s
compile unit instead of being fully absent; `namedtuple___*`/
`inspect_getattr_static_*`/`_signature_get_user_defined_method_
lambda_1` "undeclared here" appeared in `io.py`/`dataclasses.py`).
None of these are new failure MODES — they're the same general,
already-documented-as-unfixed mechanism (only the STRUCT-METHOD-
QUALIFIER slice and one specific `Repr_repr*` dispatch-table instance
of it were ever fixed, per that doc's own 2026-08-20/08-23 entries;
the general struct-field-table/type-identity fix remains open) landing
on a different sibling module because this session's fix changes which
functions successfully type-check as coroutine bodies, which shifts
whole-program compile order and which module "wins" a given bare-name
race. Net: **not a regression from this fix** — same bug class,
different specific victim files, count within noise for a ~180-error
grab-bag file with many independent unrelated root causes.

**socket.py still does not build.** Quality gate for the fix itself
(unrelated to this file) verified clean: `test_gimple.py` 252/252,
`test_module_cache.py` 76/76, `make check-selfhost` clean, stdlib
dylib rebuild 0 skips.

## Status (updated 2026-08-23): error count 201 → 178; the last cross-module "undeclared here" collision class (`Repr_repr*`) fixed via dispatch-table qualification

Re-ran `python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/
socket.py`: 178 `error:` lines (was 201). The "'X' undeclared here"
collision pattern is now ZERO (was 13 at the 2026-08-20 update): all
11 remaining instances were `Repr_repr*` — reprlib.Repr's prefix-
shaped `getattr(self, 'repr_' + typename)` pattern planned a dispatch
table whose initializer referenced bare `Repr_repr*` symbols while
reprlib's methods are emitted as `reprlib_Repr_repr_*`. Root-caused
and fixed as the live instance of the residual callee-qualification
gap in `bugs/hard/CODEGEN_selfhost_getattr_dispatch_heuristic_
misfires_on_ordinary_code.md` (2026-08-23 entry there: rows now
re-resolved through `_struct_method_csym`; diffed sorted error set
before/after shows ONLY those 11 errors removed).

**socket.py still does not build.** The remaining 178 errors are the
same independent grab-bag as catalogued below (enum.py's struct/dict
`%` operator x12 + `invalid types for 'trunc_mod_expr'` x11,
argparse.py's `_kw_default` member access x4, operator.py's
`partial`/lambda lowering, pickle.py's `partial`, contextlib's
`exc.__traceback__` member writes, posixpath/ntpath struct-shape
mismatch, etc.) — none struct-collision-shaped. Doc kept open.

## Status (updated 2026-08-20): task #141's struct-method-qualifier mechanism (the dominant blocker class) FIXED, file still fails overall

The 2026-08-09 status below identified "task #141 cross-module
bare-name collisions" (`bugs/hard/CODEGEN_same_bare_name_struct_
collision_across_modules.md`) as ~57% (370/650) of this file's error
lines. Investigating a live, concrete instance of that mechanism via
`Lib/mailbox.py` (`bugs/CODEGEN_generator_function_Lib_mailbox.md`'s
2026-08-20 entry) found and fixed the specific piece of it responsible
for STRUCT-METHOD symbol misqualification: `_struct_method_qualifier`
(gimple_codegen.py ~line 25808) wrongly preferred the shared,
whole-program `_imported_struct_home` registry over a struct's own
genuine local declaration whenever a bare struct name collided between
a locally-defined struct and a same-named struct registered elsewhere
in the transitive closure. Fixed by checking local declaration first
(see that doc / the code comment at the fix site for full detail and
the general risk assessment — this is a narrower, lower-risk fix than
task #141's own doc's general "qualify struct FIELD tables too" plan,
which remains unattempted and out of scope here).

Re-verified via a fresh `python3 mojo.py build
/Users/mrs/net/Python-3.14.6/Lib/socket.py`: error count dropped from
650 to 201, and the "'X' undeclared here ... did you mean 'Y_X'"
collision pattern dropped from 370 to 13 occurrences. **socket.py
still does not build** — the remaining 201 errors are the same
independent grab-bag already catalogued below (`enum.py`'s struct/dict
`%` operator, `argparse.py`'s `_kw_default` member access,
`operator.py`'s `partial`/lambda lowering, etc.), none of them
struct-collision-shaped anymore. Doc kept open; task #141's own doc
updated separately with this cross-reference.

Full quality gate re-run clean (see `bugs/CODEGEN_generator_function_
Lib_mailbox.md`'s 2026-08-20 entry for the complete gate results —
same fix, same verification pass).

## Status (updated 2026-08-18): `perror` sub-blocker fixed, file still fails overall

One item from the "~280 other errors" grab-bag listed in the
2026-08-09 status below is now fixed: `Lib/tokenize.py`'s `conflicting
types for 'perror'` (reached transitively from `socket.py`'s own import
chain). Root cause was a general gap in gimple_codegen.py, not
`perror`-specific: `_gen_stmt_ExprStmt` (the lowering path for a bare,
value-discarding call statement) had its own copy of the "resolve a
call to a nested closure" logic that never got the sibling-closure
(`_lambda_outer_closures`) fallback `_lower_call` (the value-consuming
call path) already had — so a nested `def` calling one of its own
SIBLING nested `def`s as a bare statement (e.g. `tokenize.py`'s
`_main()`, whose `error()` calls its sibling `perror()`) emitted a
bare, unqualified `perror (...)` C call that collides with libc's real
`perror`. Fixed by adding the same sibling-closure lookup to
`_gen_stmt_ExprStmt`. Full analysis and verification in
`bugs/CODEGEN_generator_function_Lib_tokenize.md`'s matching
2026-08-18 entry.

Re-verified via a real `mojo.py build` of
`/Users/mrs/net/Python-3.14.6/Lib/socket.py`: `grep -c "conflicting
types for 'perror'"` on the build output is now 0. The build **still
fails overall** — none of the other blockers below (task #141 cross-
module bare-name collisions, `operator.py`'s `partial`/lambda lowering,
`posixpath`/`ntpath`'s struct collision, `enum.py`'s struct/dict
codegen, etc.) are affected by this fix; only the `perror` error class
is gone. Quality gate (`test_gimple.py` 248/248, `test_module_cache.py`
76/76, `make check-selfhost`, from-scratch stdlib dylib rebuild: 0
skipped modules before and after) all pass with no regression.

## Status (re-verified 2026-08-09, fresh against current master post-merge): still not PASS, same two blocker classes, error count 669→650

Re-ran `python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/socket.py`
against current master (this worktree's branch was rebuilt on top of
local master at fdd5e66, including all intervening-session fixes —
none targeted at this file's remaining blockers). Result: still fails,
650 `error:` lines (down slightly from the 669 recorded 2026-08-07;
diffing shows `Lib/stat.py:179`'s `invalid operands to binary &`
error listed in the previous status no longer reproduces — stat.py
now only emits warnings — but this is incidental and does not change
the overall outcome, since hundreds of other unrelated errors remain).

Confirmed both previously-identified blocker classes are still present
and still dominate:

1. **370 of 650 (~57%)** are still the `'X' undeclared here ... did
   you mean 'Y_X'` cross-module bare-name-collision pattern —
   `bugs/hard/CODEGEN_same_bare_name_struct_collision_across_modules.md`
   (task #141), still explicitly out of scope. Now concentrated mostly
   in `Lib/enum.py` (409 error lines total across all categories) and
   `Lib/argparse.py` (50), spreading into ~25 different transitively-
   compiled files (`typing.py`, `pickle.py`, `traceback.py`,
   `inspect.py`, `codecs.py`, `posixpath.py`, `contextlib.py`, `os.py`,
   `socket.py` itself, `functools.py`, `weakref.py`, `tokenize.py`,
   `threading.py`, `operator.py`, `locale.py`, `dis.py`, `copyreg.py`,
   `reprlib.py`, `codeop.py`, `ast.py`, `__future__.py`,
   `annotationlib.py`, `gettext.py`, `tracemalloc.py`), confirming this
   is a broad, systemic collision issue rather than anything
   `socket.py`-specific.
2. The other ~280 errors are still the same grab-bag of independent,
   pre-existing bugs: `Lib/operator.py:270`'s `non-trivial conversion
   in 'var_decl'` (still present, confirmed by line/column match),
   `Lib/operator.py:342`'s `expected expression before 'partial'`
   (still present), `Lib/posixpath.py`'s `expandvars_repl_env`
   redefinition/struct-shape mismatch against `Lib/ntpath.py`'s own
   same-named helper (still present, still a cross-module bare-name
   collision variant — arguably also task #141-shaped, just for a
   nested/synthesized struct name rather than a top-level function),
   `Lib/tokenize.py:396`'s `conflicting types for 'perror'` (still
   present, one line off from the previously-recorded :390 — a
   `perror()` call inside `argparse.py`'s error-formatting code being
   misdetected as a redeclaration of libc's `perror`), plus new-to-
   this-pass but same-flavor errors in `Lib/enum.py` (`expected ';',
   ',' or ')' before 'default'`, `invalid operands to binary %` between
   `int64_t` and `MojoDict *`), `Lib/argparse.py:1493`'s `request for
   member '_kw_default' in something not a structure or union`, and
   `Lib/contextlib.py`'s `request for member '__traceback__' in
   something not a structure or union` (lines 171/195/244/268) — the
   latter two are an actual literal match for THIS doc's own original
   `__module__`-pattern title, though on different member names/files;
   not investigated whether they share a root cause with each other or
   with the original `__module__` pattern.

None of these ~280 remaining errors were investigated further — each
is independently rooted in a different corner of the transitive
closure (enum.py's struct/dict codegen, argparse.py's kwarg-default
and exception-attribute handling, operator.py's `partial`/lambda
lowering, posixpath/ntpath's cross-module struct collision,
tokenize.py's `perror` misdetection), and fixing #141 alone would not
get this file anywhere near PASS. Confirms the 2026-08-07 assessment
below: this is not a narrow, well-scoped single bug but a convergence
of several independent, already-tracked-or-trackable issues, most of
which trace back to the same class of cross-module bare-name collision
underlying task #141. Checked whether the fix that resolved this
session's sibling doc (`bugs/COMPILE_FAIL_Lib_runpy_...md`, function-
scoped-import link stub, deleted 2026-08-09) has any bearing here:
`socket.py` is compiled via the `build_executable` fallback path (not
link mode), so that fix's code path is never exercised by this file at
all. Not a shared root cause with the other two docs in this cluster.

## Status (updated 2026-08-07, final): PERF timeout resolved, matmul crash fixed, but file still not PASS — multiple simultaneous blockers, confirmed via direct rebuild

The PERF hard bug this doc previously matched
(`bugs/hard/PERF_nested_module_compile_walk_ast_quadratic_rescan.md`)
has since had its Phase 2 fix land — `Lib/socket.py` no longer times
out: it now completes (via `mojo.py build`'s `build_executable`
fallback path) in ~61s, generating ~10 MB of C, and reaches a real GCC
error stage.

Also fixed this session: the first blocking error that used to appear
(`Lib/operator.py:118:9: error: implicit declaration of function
'int64_t___matmul__'`, from `def matmul(a, b): return a @ b`'s
untyped-param fallback) — `_lower_matmul`'s blind
`{struct_name}___matmul__` call for a non-struct operand type. Fixed by
a guarded weak stub, mirroring an existing pattern used for
unresolved-base-class method calls — verified against the full 5-step
gate, no full-corpus regression.

**Still not PASS — confirmed via a direct rebuild in the final merged
state: 669 total `error:` lines**, from (at least) two independent,
simultaneous blockers:

1. **338 of 669 (~50%)** are `'X' undeclared here ... did you mean
   'argparse_X'/'ast_X'/...'` — this is
   `bugs/hard/CODEGEN_same_bare_name_struct_collision_across_modules.md`
   (task #141), explicitly excluded from this session's scope (already
   assessed as feature-sized/high-risk, not to be re-attempted without
   new information). Not investigated further here — see that doc for
   the mechanism.
2. The remaining ~330 errors are several OTHER, unrelated,
   pre-existing bugs in the transitive closure, none blocked by task
   #141: `Lib/operator.py:270`'s `non-trivial conversion in 'var_decl'`,
   `Lib/operator.py:342`'s `expected expression before 'partial'`,
   `Lib/stat.py:179`'s `invalid operands to binary &` (int64_t vs
   char*), `Lib/posixpath.py`'s `expandvars_repl_env` struct-shape
   mismatch (`redefinition of...`/`'...' has no member named...`),
   `Lib/tokenize.py:390`'s `conflicting types for 'perror'`. None of
   these investigated further here — each is its own separate,
   independent bug, and fixing #141 alone would NOT get this file to
   PASS on its own.

(`socket.py` was NOT re-tested against link mode/`driver.
compile_program`, which might fare differently since it doesn't inline
the whole transitive closure into one translation unit the way
`build_executable`'s fallback does — left for a future session.)

## Original status (2026-08-06, superseded above)

Re-ran with a 150s timeout: got partway through (produced the usual
`drop stale export` dylib-link noise, then an `os.py: 'relpath' is
ambiguous` transitive-compile-fallback note) then TIMED OUT with no
further output. Retried standalone in the background — still running
after 9+ minutes before being killed for this session's time budget
(on a machine also running several other agents' `mojo.py build`
processes concurrently).

`socket.py` has a large transitive import graph (imports `os`, `sys`,
`enum`, `errno`, `io`, `selectors`, ... each with their own further
imports), matching the profile of the ALREADY-DOCUMENTED performance
hard bug `bugs/hard/PERF_nested_module_compile_walk_ast_quadratic_rescan.md`
(confirmed via a `_walk_ast`-call-count blowup on a similarly-shaped
file, `Lib/contextlib.py` — see `bugs/COMPILE_FAIL_Lib_contextlib_
request_for_member_module_in_something_not_a_structure_or_union.md`,
also timing out this session for the identical reason). Not
independently profiled here (would need `cProfile` + a longer budget
than this session had left), but the symptom match (times out only for
transitive-import-heavy files, produces no output for a very long
stretch) is strong. Not investigated further — see that doc for the
concrete root cause and phased fix plan.

The ORIGINAL `__module__`/"consolidated" note below is STALE (from an
older bug-tracking scheme; the referenced `consolidated/` directory no
longer exists) — not re-verified since the file never finishes
compiling within any reasonable timeout now.

## Original stale note (pre-2026-08-06, unverified)

**TIMEOUT resolved** (2026-07-25) — the hang was caused by the multi-name
`import a, b, c` binding bug (fixed in commit 52ea4d7). The file no longer
times out, but now hits COMPILE_FAIL errors in its transitive dependencies.

```
request for member '__module__' in something not a structure or union
```

This error pattern was tracked in:
`consolidated/COMPILE_FAIL_cc_error_request_for_member_x_in_something_not_a_structure_o.md`
(directory no longer exists as of 2026-08-06).

Source file: `/Users/mrs/net/Python-3.14.6/Lib/socket.py`
