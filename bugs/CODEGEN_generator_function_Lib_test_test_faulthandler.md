# CODEGEN_generator_function: Lib/test/test_faulthandler.py

## Status (updated 2026-08-24, worktree fix/rest-remainder — checked ONLY via a safety-bounded ISOLATED compile (do_imports=False, no real `mojo.py build`/link) per this session's mandatory memory-safety rule for this exact file; one new, different blocker found, not attempted)

**Safety note**: this file is the confirmed 43+GB-RSS runaway-compile
hazard flagged in this task's own brief — a REAL `mojo.py build`/`run`
against it (which resolves/links its huge transitive import chain) must
never be run unbounded. This session used ONLY `gimple_codegen.
compile_to_gimple_with_cpp(do_imports=False)` (no import resolution, no
linking — a fundamentally bounded operation, unlike a real build), still
wrapped in `ulimit -v 8000000` plus a wall-clock/RSS watcher as a
belt-and-suspenders precaution; it completed in seconds. No real
`mojo.py build`/`run` was attempted against this file this session.

Isolated-compile `g++-mp-15 -std=c++20 -fsyntax-only` check on the
resulting `.cpp`: a NEW error surfaces inside a `finally:`-block RAII
lambda (`_MojoScopeExit`) at `os_helper.unlink(filename)` — `'os_helper'
was not declared in this scope`. This is the SAME general shape this
session's `_cpp_expr` MemberExpr fix targeted (an early-global module
name read as a bare attribute, here via a CALL `os_helper.unlink(...)`
rather than a bare value) — but it does NOT reproduce as fixed, meaning
the `finally:`-lambda body emission path (`_cpp_try_stmt`'s RAII lambda
construction) evidently does not see the same `_cpp_early_global_names`
resolution the ordinary body-statement emitter does (a plausible
scoping/context gap specific to that lambda's own expression-lowering
context, not investigated further here — genuinely a different code
path, out of scope for this session's narrower fix). Left open, flagged
for whoever next picks up this exact shape.

## Status (updated 2026-08-24 — PARTIAL, item 1 fixed; full-file build still unresolved and slow)

Fixed item 1 below this session (commit 753b199): `_safe_field` now
escapes `stdin`/`stdout`/`stderr` field names (Darwin `<stdio.h>` macro
collision), so `p.stdin.close()`'s "'MojoCompletedProcess' has no member
'__stdinp'" no longer reproduces. Item 2 (kwargs-slot packing arity for
the cross-module `assert_python_ok` callee) is unchanged/not attempted.
This file's full build was NOT independently confirmed to complete:
it pulls in a very large transitive import chain (collections, inspect,
typing, ctypes, compression/lzma/zstd, struct, ...) and three bounded
verification attempts this session did not reach a definitive pass/fail
— a 240s-capped run on the PRE-fix tree (baseline) stayed under 1GB RSS
but timed out before finishing; two bounded runs on the POST-fix tree
also didn't finish, and the longest (900s cap, isolated, no other
concurrent builds) hit 11.9GB RSS and climbing at 820s before the
watchdog killed it. This could be a real memory-growth regression from
this session's edits, or simply this file's own transitive-import
weight (the baseline run never got far enough in its 240s budget to
reach a comparable point, so the two aren't directly comparable) —
NOT conclusively isolated either way given this session's time budget.
Flagging as a possible memory-blowup issue needing dedicated follow-up
with a longer, controlled bisection (baseline vs. fixed tree, same
wall-clock budget, single isolated run each) rather than claiming this
doc resolved. The stdin-macro fix itself is verified correct and low-
risk independently: full quality gate clean (`test_gimple.py` 252/252,
`test_module_cache.py` 76/76, `make check-selfhost` clean x2,
from-scratch stdlib dylib rebuild exit 0, 0 skips).

## Status (updated 2026-08-23 — PARTIAL)

All Lib/test/support/__init__.py errors blocking this file's builds are
fixed (see sibling docs). Remaining, both in transitively-imported
support/script_helper.py, both newly precise:
1. line 222 `p.stdin.close()` — the generated struct-field access emits
   the field name `stdin`, which macOS libc MACRO-EXPANDS to `__stdinp`
   ('MojoCompletedProcess' has no member '__stdinp'). A platform-macro
   field-name collision (_safe_field escapes C keywords but not libc
   stdin/stdout/stderr macros); additionally the receiver is a
   subprocess.Popen-shaped param typed MojoCompletedProcess*, which has
   no stdin field at all.
2. line 324 `assert_python_ok('-u', script, '-v')` — callee declared
   (*args, **kwargs) -> (MojoList*, MojoDict*) but the imported call
   site passed 3 raw positional args: the kwargs-slot packing table is
   keyed per-module and has no entry for the cross-module callee.
Neither is generator-related; not attempted this session. Gate verification (2026-08-23): `test_gimple.py` 250 passed / 0 failed;
`test_module_cache.py` 76 / 0; `make check-selfhost` clean; from-scratch
stdlib dylib rebuild EXIT=0 with **0** `skip <module>:` lines — matching
the pre-change baseline of exactly 0 skips.

## Status (updated 2026-08-12, re-verified — unchanged)

Re-verified against current master with a real `MOJO_DEBUG=1 python3
mojo.py build`. Confirmed unchanged from the 2026-08-09 entry below:
`check_stderr_none` still doesn't appear in the "not eligible"/refused
list; the full build still fails purely on the same unrelated errors in
`Lib/test/support/__init__.py` (the `mojo_list_set_int`/`int64_t *`
pointer-cast/`print_warning`/malformed-statement errors around lines
488, 1184-1186, 1420, 1905-1908) plus, this time, two additional
unrelated `Lib/test/support/script_helper.py` errors (`MojoCompletedProcess`
has no member `__stdinp`; a call-arity mismatch on
`test_support_script_helper_assert_python_ok`) — all pre-existing,
already covered by this doc's general "OTHER, unrelated, non-generator
errors transitively reached in `Lib/test/support/__init__.py`,
`os_helper.py`, and `script_helper.py`" characterization above, none of
them generator-codegen issues, none in this doc's scope. No code change
made; nothing new to fix here beyond the already-documented structural
gaps below.

## Status (updated 2026-08-09)

Re-verified against current master (`42faf64`). Confirmed:
`check_stderr_none` no longer appears in the "not eligible"/refused
list at all in a full `MOJO_DEBUG=1 python3 mojo.py build` of the real
file — the `sys.stderr = None` assignment-target fix described below
still holds. The full-file build still fails overall, but now purely on
OTHER, unrelated, non-generator errors transitively reached in
`Lib/test/support/__init__.py`, `os_helper.py`, and `script_helper.py`
(int64_t/pointer-cast mismatches, an undeclared `print_warning`, etc.) —
none of those are generator-codegen issues and none are in this doc's
scope; they never even reach the `.cpp` coroutine-compile stage since
the plain `.ci` compile fails first.

To see what `check_stderr_none` itself now compiles to, in isolation
(a standalone 20-line repro of just this method, since the full-file
build no longer surfaces it), inspecting the generated `_gen.cpp`
confirms the doc's next paragraph is still accurate, with concrete
evidence:
```cpp
static _mojogen_FaultHandlerTests_check_stderr_none_Task
_mojogen_FaultHandlerTests_check_stderr_none_impl (FaultHandlerTests * self) {
    int64_t stderr;
    stderr = sys.stderr;              // sys.stderr READ: 'sys' is simply
                                       // undeclared in this TU -> hard g++ error
    ...
    int64_t cm;                       // untyped `with ... as cm:` binding
                                       // defaults to int64_t (known gap)
    co_yield (int64_t)0;
    FaultHandlerTests_assertEqual(self, mojo_str((void *)(cm.exception)), ...);
                                       // -> invalid member access on int64_t
```
The `with self.assertRaises(RuntimeError) as cm:` call itself is elided
to `(void)(0);` (the known "real side-effecting `with` inside a
generator body" gap) rather than actually invoking `assertRaises` and
populating `cm`, so `cm` is left as an uninitialized `int64_t` before
the invalid `.exception` member access on it.

All three remaining gaps are already-known, already-documented
structural gaps from this task family (not narrow, not attempted here):
- `sys.stderr` read — arbitrary outer-scope module-attribute resolution
  inside a generator's separately-compiled translation unit (the
  "genuinely structural" outer-scope-resolution gap).
- untyped `with ... as cm:` binding defaulting to `int64_t`.
- the `with self.assertRaises(...) as cm:` call being a real
  side-effecting `with` inside a generator body.

Also reconfirmed unchanged: `start_threads` (transitively reached via
`test.support`) is still refused with the `print()` non-scalar-argument
gap.

No code change made for this bug.

## Status (updated 2026-08-07, `sys.stderr = None` case now fixed)

This file's specific occurrence (`sys.stderr = None` in
`check_stderr_none`) is now fixed — `_cpp_stmt`'s `AssignStmt` handling
gained a narrow, structurally-scoped case for `sys.stderr`/`stdout`/
`stdin` as an assignment target (elided as a safe no-op; see
`bugs/hard/CODEGEN_generator_non_plain_assignment_target_refused.md`
for the full root cause and why eliding this specific shape is sound).
Confirmed via `MOJO_DEBUG=1`: `check_stderr_none` no longer appears in
the "not eligible"/refused list at all.

**`check_stderr_none` still does NOT fully compile end-to-end**,
for OTHER, unrelated, pre-existing reasons in the same method body
(confirmed via an isolated repro of its exact source): `stderr = sys.
stderr` (a `sys.stderr` READ — a separate, still-open gap, since `sys`
has no real backing value anywhere in this model outside the `print(
file=sys.stderr)` structural match), `self.assertRaises(...)`/`self.
assertEqual(...)` (method calls on `self`, out of this narrow `self.
<scalar field>`-reads-only model's scope), and `with ... as cm:`
binding a method-call result. Same "target-shape fixed, sibling
constructs in the same body still gap out" pattern as every other
partial fix in this cluster (task #149's imaplib.py, task #150's
original list-unpack fix on gc_inspection.py).

Also still present, unrelated: the transitively-reached `test.support`
`start_threads` gap noted below (`print()` non-scalar argument).

Full 5-part CLAUDE.md gate passed for the codegen change (see the
hard-bug doc for details): test_gimple.py 247/247, test_module_cache.py
76/76, check-selfhost clean, dylib rebuild 0 skips, compile_stdlib.py
664/664 0 unexpected.

## Status (updated 2026-08-07, superseded above)

`bugs/hard/CODEGEN_generator_non_plain_assignment_target_refused.md`
is now PARTIALLY fixed (task #150) — but only the tuple/list-pattern-
unpack target shape. This file's own occurrence (`sys.stderr = None`,
a non-`self` MODULE-attribute assignment target) is the specific shape
that fix deliberately did NOT cover — assigning into an arbitrary
object's attribute has no representation in this narrow scalar-only
generator-body model, correctly identified as a meaningfully bigger,
separate step in the hard-bug doc's own "What a fix needs" analysis.
`check_stderr_none` is still refused, unchanged.

## Status (updated 2026-08-06, superseded above)

**STILL FAILING**, confirmed reproducing against current master
(`2b0c4c5`), now precisely classified.

```
$ MOJO_DEBUG=1 python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/test/test_faulthandler.py
[gimple_codegen] generator method FaultHandlerTests.'check_stderr_none' not eligible for C++ coroutine path, falling back to honest refusal: only a plain identifier assignment target is supported
```

**Classification: `bugs/hard/CODEGEN_generator_non_plain_assignment_
target_refused.md`** (4th confirmed occurrence, and the first involving
a MODULE attribute as the target rather than tuple/list-unpack):
```python
def check_stderr_none(self):
    stderr = sys.stderr
    try:
        sys.stderr = None            # <-- module-attribute assignment target
        with self.assertRaises(RuntimeError) as cm:
            yield
        ...
```
`sys.stderr = None` assigns to `sys.stderr` — a `MemberExpr` target
(module attribute), not a bare identifier — refused by the same
generic "only a plain identifier assignment target is supported" check
as the doc's other 3 occurrences (which were tuple/list-pattern
unpacking). Confirms the gap is broader than just unpack-shapes: ANY
non-`IdentExpr` assignment target inside a generator body is refused,
including plain attribute assignment.

Also transitively (via `test.support`, not this file's own code): a
NEW gap, `start_threads` refused with "`print()` argument must be a
scalar int64_t/double/_Bool/char* expression" — a `print()` call with a
non-scalar argument inside a generator body. Single instance, not yet a
hard-bug doc; plausibly related to the pkgutil.py callback-argument-
shape gap (`bugs/CODEGEN_generator_function_Lib_pkgutil.md`) as another
instance of "some call sites inside a generator body have a stricter
argument-shape requirement than the general parameter-type allow-list."

Not fixed here.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/test/test_faulthandler.py
