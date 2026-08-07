# CODEGEN_generator_function: Lib/test/_test_eintr.py

## Status (updated 2026-08-06)

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
