# CODEGEN_generator_function: Lib/test/_test_eintr.py

## Status (updated 2026-08-24, worktree fix/rest-remainder — the `.join()` gap from the 2026-08-23 entry (item 3) is FIXED; two other, DIFFERENT blockers now surface on the same/nearby lines, unaffected)

This session's `.join()`-on-string-literal fix (see `bugs/
CODEGEN_generator_function_Lib_ftplib.md`'s matching 2026-08-24 entry for
the mechanism) resolves this file's own item 3 (`'\n'.join((...))` was
previously refused outright as "`.join()` unsupported in the coroutine-
body expression lowering" — confirmed gone via a fresh isolated
`compile_to_gimple_with_cpp(do_imports=False)` + `g++-mp-15 -std=c++20
-fsyntax-only`: `mojo_str_join(...)` is now correctly emitted for this
call).

However, the SAME statement doesn't compile clean either way — its
argument is a LITERAL multi-line string tuple (`'\n'.join(("import os,
sys, time", "", ...))`), and a literal `TupleExpr`/`ListExpr` used
directly as a call ARGUMENT (as opposed to an assignment RHS, which this
emitter already has real `mojo_list_new()`-based construction for) still
lowers to a bare C++ brace-init-list, which isn't a valid `MojoList *`
argument (`expected ';' before '}' token` / a downstream `cannot convert
'char*' to 'MojoList*'`). This is a DIFFERENT, narrower gap than the
`.join()` refusal it was hiding behind — not attempted here (scope
creep beyond this session's `.join()` fix) — flagged for whoever picks
this up: extending the existing list/dict/set-literal-as-assignment-RHS
construction path to also cover a literal used directly as a call
argument would close it.

This file's DOMINANT blocker (item 1, `os.pipe()`/`os.close` — outer-
scope module-name resolution inside a generator's own translation unit)
is confirmed UNCHANGED and untouched by either fix — still the first
thing that would need solving for this file to build. Item 4
(`assertEqual` arity — inherited `unittest.TestCase` methods getting a
`(self)`-only extern declaration) also confirmed unchanged; investigated
this session (see `bugs/CODEGEN_generator_function_Lib_test_test_ctypes_
test_random_things.md`'s matching entry) but NOT fixed — the "declare
the extern as C-variadic instead" idea was considered but not attempted,
since there's no confirmed evidence a real backing DEFINITION for an
inherited-but-uncompiled base-class method exists to link against at any
arity; changing the extern declaration alone risks trading a diagnosable
compile-time arity error for a much more confusing link-time undefined-
symbol error. Needs a dedicated investigation into what (if anything)
currently backs these symbols before attempting.

Full mandatory gate for the `.join()` fix: `test_gimple.py` 252/252,
`test_module_cache.py` 76/76, `make check-selfhost` clean, from-scratch
stdlib dylib rebuild EXIT=0 with 0 skip lines.

Doc stays open — file still does not build.

## Status (updated 2026-08-24 -- re-verified, unchanged)

Re-checked this session while triaging the C3 cluster. This session's two landed fixes (stdin/stdout/stderr field-name escaping; more char* string methods in coroutine bodies -- strip/lstrip/rstrip/lower/upper/startswith/endswith) do not touch this file's dominant blocker (outer-scope module-name resolution, e.g. `os.pipe()`, inside a generator's own translation unit -- a module name like `os` is never in this narrow body model's known-symbol set at all, so no string-method or field-name fix reaches it). Still structural; untouched.


## Status (updated 2026-08-23 — PARTIAL)

Major unblocking this session: ALL FOUR previously-enumerated
Lib/test/support/__init__.py compile errors are gone (env[name]-dict
inference, bigmemtest closure mut-capture temps, print_warning
function-attribute namespace, patch()'s mojo_getattr signature), and
import_helper.py's unlink now binds to its weak stub. The file's OWN
generator (`_interrupted_reads`, `yield rd, datum`) now compiles all the
way to the coroutine .cpp stage, where NEW, precisely-localized errors
surface in ITS body only:
1. `'os' was not declared` — `rd, wr = os.pipe()`: outer-scope module
   name resolution inside a generator TU (documented structural family).
2. brace-init-list assigned to an int64_t local — bare list literal
   `data = [b'hello', ...]` still has no declared-type support.
3. `'\n'.join(...)` lowered as member call on the C string literal.
4. assertEqual arity: inherited-unittest-method extern declarations
   default to (self)-only params (same new residual documented on
   test_random_things below). Not attempted; outer-scope generator-TU
   resolution remains the dominant blocker family. Gate verification (2026-08-23): `test_gimple.py` 250 passed / 0 failed;
`test_module_cache.py` 76 / 0; `make check-selfhost` clean; from-scratch
stdlib dylib rebuild EXIT=0 with **0** `skip <module>:` lines — matching
the pre-change baseline of exactly 0 skips.

## Status (updated 2026-08-11 — tuple-valued yield fix holds; file's OWN code now compiles clean; blocked purely by 4 distinct, unrelated Lib/test/support/__init__.py bugs)

Re-verified against current master with a fresh real rebuild. The
2026-08-10 note's claim (tuple-valued `yield rd, datum` fixed, but
`os.pipe()`/bare-list-literal-local/`.join()` gaps earlier in
`_interrupted_reads`'s own body still block) does **not** reproduce as
described — direct inspection of the full error list shows **zero**
errors attributed to `_test_eintr.py` itself. Confirmed via `grep
"_test_eintr.py:" ... | grep "error:"` on a fresh build: no matches.
Whatever combination of fixes landed since 2026-08-10 (the tuple-yield
work, or unrelated ones) also resolved the `os.pipe()`/list-literal/
`.join()` gaps previously blocking this same body — `_test_eintr.py`'s
own 2 generators (`yield proc` and `yield rd, datum`) now compile
cleanly end to end.

**This file still does not build**, now blocked ENTIRELY by 4 distinct,
pre-existing, non-generator bugs in the transitively-imported `Lib/test/
support/__init__.py` (confirmed via direct source read at each site):

1. `set_sanitizer_env_var`'s `env[name] += f':{option}'` (line 488,
   `env` an untyped dict-shaped param) — `env` gets misinferred as a
   `MojoList`, not a `MojoDict`: `passing argument 3 of
   'mojo_list_set_int' makes integer from pointer without a cast`
   (a `char *` f-string result passed where `mojo_list_set_int` expects
   an `int64_t` index — the wrong runtime function entirely, list not
   dict).
2. `bigmemtest`'s docstring-adjacent lines (1184/1186) —
   `assignment to 'int64_t *' from 'int64_t' makes pointer from integer
   without a cast` — a closure/local type-inference mismatch, not yet
   traced past the mismatch symptom itself.
3. `print_warning`'s own body (`stream = print_warning.orig_stderr`,
   line 1420) — the Python idiom of using a plain function as an
   attribute-namespace (a later statement sets `print_warning.
   orig_stderr = ...`) breaks this codegen's function-vs-variable
   disambiguation: `implicit declaration of function 'print_warning'`.
4. `patch()`'s `getattr(object_to_patch, attr_name)` (line ~1908) —
   `passing argument 1 of 'mojo_getattr' makes integer from pointer
   without a cast [-Wint-conversion]`, plus a genuine syntax-level
   `expected ')' before ';'` / `expected expression before '('` pair
   nearby — at least two distinct problems in this one call's lowering.

None of (1)-(4) are IN `_test_eintr.py` itself, and none involve
generators — all are `test.support`'s own pre-existing, independent
codegen gaps (dict/list type-inference confusion, a function-as-
namespace attribute pattern, and a `getattr()`-on-dynamically-typed-
object lowering bug), first precisely enumerated at this level of
detail in this pass (superseding the STALE 2026-08-07 list below, which
named different symptoms — `force_color`'s plain-`int` param, `iter_
builtin_types`/`patch_list`'s slice-target refusal, `async_yield`'s
`return <value>` — none of which appear in the current error list,
apparently fixed by unrelated work since). Also note: the reported
line numbers for these 4 (1184/1186/1420/1906ish) are themselves
suspect — each points at a docstring/comment line, not the actual
offending statement a few lines below/above; this matches a separate,
not-yet-root-caused `#line`-attribution inaccuracy in this codegen's
whole-program C output also observed independently while investigating
`bugs/CODEGEN_generator_function_Lib_tempfile.md` this session (its own
`#line` pragmas for the shared globals-init struct run stale past a
certain point in a large concatenated build) — a real but separate
diagnostics-quality gap, not attempted here.

Not attempted: each of the 4 is its own nontrivial, independent root
cause (not narrow one-spot stubs) in a file that isn't one of this
cluster's 41 named target files, and none touch generator codegen at
all — out of scope for this pass. Doc kept open, not deleted.

## Status (updated 2026-08-10 — tuple-valued yield now FIXED; unrelated gaps earlier in the same body now block)

Implemented real tuple-valued-`yield` support this session (see
`gimple_codegen.py`'s `_cpp_yield_tuple`/`_generator_tuple_yield_slot_
ctypes`). Confirmed via an isolated compile: `OSEINTRTest.
_interrupted_reads`'s `yield rd, datum` (line 153) is no longer
refused, and its own `co_yield`/tuple-boxing text
(`mojo_list_append_int(rd)`/`mojo_list_append_int(datum)`) is
syntactically valid C++ — no g++ errors on those lines.

**This file still does not build**, blocked by unrelated, pre-existing
gaps EARLIER in the same function body (confirmed via g++ syntax-check):
`rd, wr = os.pipe()` (no lowering for `os.pipe()`), `data = [b"hello",
b"world", b"spam"]` (a bare list-literal local assignment inside a
coroutine body has no declared-type support — confirmed via a minimal,
tuple-free repro: `dirs = ["a","b"]; yield dirs[0]` hits the identical
"cannot convert brace-enclosed-initializer-list to int64_t" error), and
`'\n'.join((...))` (`.join()` unsupported in the coroutine-body
expression lowering). None of these are the promise/ABI gap this
session's fix targets. Not attempted here. Doc kept open (not deleted).

## Status (updated 2026-08-09, re-verified against current master `b48a941`)

Re-ran `MOJO_DEBUG=1 python3 mojo.py build .../_test_eintr.py` fresh.
**Still fails, but the root cause is now `_test_eintr.py`'s OWN code, not
just the transitive `test.support` gaps below** — the earlier
2026-08-06/07 passes' claim that "the file's own 2 generators compile
cleanly" does not hold up under direct re-verification:

`OSEINTRTest._interrupted_reads` (line 153) does `yield rd, datum` — a
real 2-element **tuple-valued yield**. `MOJO_DEBUG=1` output confirms:
```
generator method OSEINTRTest.'_interrupted_reads' not eligible for C++
coroutine path, falling back to honest refusal: _interrupted_reads:
every `yield` must carry a value, and all values must agree on one
scalar type (int64_t/double/_Bool)
```
Traced to `gimple_codegen.py`'s `_generator_yield_ctype` (module-level
helper, ~line 2647), the `TupleExpr` branch at lines 2699-2724: it
deliberately returns `None` (refuse) rather than letting the generic
"default to int64_t" fallback silently mis-lower `yield rd, datum` as
an invalid raw `co_yield {rd, datum};` braced-init-list. This is the
SAME widely-recurring "tuple-valued yield" structural gap this whole
`bugs/CODEGEN_generator_function_Lib_*` family already knows about
(the single most common sub-gap across the ~40-file cluster, e.g. also
hit by `Lib/test/libregrtest/save_env.py`'s `resource_info`) — no
dedicated fix attempted here per this cluster's standing guidance
(genuinely representing a tuple across a C++20 coroutine's single
scalar promise type is a real state-machine/ABI design problem, not a
one-spot stub gap).

Because this generator is refused (not merely one function skipped),
`gen_module`'s non-`relaxed_imports` path raises a hard
`RuntimeError('cannot compile module: function(s) _interrupted_reads
...')` and the ENTIRE module build fails outright (falls back to pure
interpretation) — this is expected behavior given the tuple-yield
refusal, not a separate bug.

`_test_eintr.py`'s other generator (`yield proc`, line 40) is a plain
scalar `Popen`-object yield — not independently reproducible as broken
on its own since the module never gets far enough to isolate it (the
`_interrupted_reads` failure aborts the whole module first).

## Status (updated 2026-08-07, re-verified against tasks #146/#149/#150)

Re-ran `MOJO_DEBUG=1 python3 mojo.py build .../_test_eintr.py` against
current master. Of the 4 transitively-reached `test.support` gaps
listed below (all pre-existing, none in `_test_eintr.py`'s own code):

1. `run_with_locale`/`subst_drive` dynamic-`raise` gap
   (`bugs/hard/CODEGEN_generator_raise_non_static_exception_class.md`,
   task #149) — **the underlying hard bug is FIXED**, but these two
   are unrelated to the specific case #149 fixed (a runtime-resolved
   `raise self._imap.error(...)`-style member-expression exception
   class) — not independently re-traced to confirm they're gone; the
   overall "not eligible" refusal list (below) no longer names either
   function, consistent with them now compiling past this gate.
2. `force_color`'s plain-`int`-typed parameter — **STILL REFUSED,
   unchanged**: `force_color: generator parameter 'color' has
   unsupported type 'int'`. Unrelated to any of the 6 fixes.
3. `iter_builtin_types`/`patch_list` — **STILL REFUSED**, but now
   precisely root-caused (see update below) as a THIRD, distinct
   "non-plain-assignment-target" sub-case (slice-subscript targets,
   `x[:] = ...`) that task #150's fix did NOT cover (#150 only widened
   tuple/list-*unpack* targets) — now documented as a new confirmed
   sub-case in `bugs/hard/CODEGEN_generator_non_plain_assignment_
   target_refused.md`.
4. `async_yield`'s `return <value>` inside a generator — **STILL
   REFUSED, unchanged**: `return <value> inside a generator is not
   supported`. Unrelated to any of the 6 fixes; not yet a hard-bug doc
   (single instance).

Confirmed via direct source read (`Lib/test/support/__init__.py`):
`patch_list`'s `orig[:] = saved` (line 1933) and `iter_builtin_types`'s
`subs[:] = []` (line 2814) both parse to `mojo_compiler.py`'s
`SliceExpr` target node, which `_cpp_stmt`'s `AssignStmt` case doesn't
special-case (only `SubscriptExpr`/`TupleExpr`/`ListExpr`/self-`Member
Expr` are handled) — falls through to the generic refusal, same
symptom text as before but a different, now-understood root cause.

`_test_eintr.py`'s own 2 generators still compile cleanly (no "not
eligible" refusal for either); the file's own current errors remain the
same unrelated lambda-argument parsing bugs noted below, out of scope
for this cluster.

## Status (updated 2026-08-06, superseded above)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-30 `request for member 'kill'` .cpp error no longer reproduces.
`_test_eintr.py`'s own 2 generators (`yield proc` line 40, `yield rd,
datum` line 153) do NOT appear in the current error list and have no
"not eligible" refusal — they appear to compile cleanly.

**Classification: mixed — the file transitively exposes a rich set of
`test.support` (test-infrastructure helper module) generator-codegen
refusals, none from `_test_eintr.py`'s own code, PLUS its own unrelated
lambda-parsing bugs:**

1. `test.support`'s `run_with_locale`/`subst_drive`: dynamic-`raise`
   gap, now `bugs/hard/CODEGEN_generator_raise_non_static_exception_
   class.md` (2 of that doc's 3 confirmed occurrences).
2. `test.support`'s `force_color`: generator parameter typed plain `int`
   (not `int64_t`) refused — a strict-string-match variant of the
   scalar/container allow-list family
   (`bugs/hard/CODEGEN_generator_struct_typed_param_refused.md`'s
   sibling gaps) — worth noting since `int` (C's native int, distinct
   from this codegen's usual `int64_t`) apparently isn't normalized
   before the allow-list check.
3. `test.support`'s `iter_builtin_types`/`patch_list`: now
   `bugs/hard/CODEGEN_generator_non_plain_assignment_target_refused.md`
   (2 of that doc's 3 confirmed occurrences — the 3rd, and the one with
   a fully-traced root cause, is `Lib/test/crashers/gc_inspection.py`'s
   own generator `g`, one of this cluster's 41 target files).
4. `test.support`'s `async_yield`: **new gap** — "`return <value>` inside
   a generator is not supported (a generator's `return` ends iteration
   with no value, unlike an ordinary function's `return`)" — Python's
   `return <expr>` inside a generator (sets the `StopIteration.value`)
   isn't supported by this coroutine codegen at all. Single new gap, not
   yet independently confirmed elsewhere in this cluster.

None of (1)-(4) are IN `_test_eintr.py` itself — they're in `test.
support`, reached transitively, not one of this cluster's 41 named
target files (source location not pinned down further in this pass).
`_test_eintr.py`'s OWN current errors are unrelated lambda-argument
parsing bugs (`lambda: os.wait3(0)`, `lambda pid: os.waitpid(pid, 0)` —
"expected ')' before ',' token" / "expected expression before '(' token"
at lines 130/166/170/180), out of scope for this generator-codegen
cluster.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/test/_test_eintr.py
