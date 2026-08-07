# CODEGEN_generator_function: Lib/test/_test_eintr.py

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
