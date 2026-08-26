# CODEGEN_generator_function: Lib/test/test_finalization.py

## Status (updated 2026-08-25 -- old blocker FIXED, NEW distinct blocker found; file still doesn't build)

Re-verified fresh against current master and found the previous
classification stale: `cls.<attr>` READS were already fixed by an
intervening session (enum.py's `Flag._iter_member_by_value_` fix,
2026-08-21) — `cls.del_calls.clear()` etc. no longer trip the "no
class-level attribute/method access" refusal this doc's history
describes. The refusal `test()`'s isolated compile actually hits now
is a DIFFERENT message: `only a plain identifier assignment target is
supported`, from `NonGCSimpleBase._cleaning = False` — a WRITE to a
class attribute via the literal class name (not `cls`), which had no
AssignStmt case at all (only reads were wired up).

**Fixed this session**: added the write-side counterpart in
`gimple_cpp_core.py`'s `_cpp_stmt` `AssignStmt` handling — `cls.<attr>
= val` (resolved via the enclosing classmethod generator's own struct)
and `ClassName.<attr> = val` (resolved directly via `gen._class_attrs`)
both now redirect to the same mangled class-attribute global the
existing read path already uses, mirroring the `self.field = val`
case immediately above it. Verified via an isolated
`compile_to_gimple_with_cpp(..., do_imports=False)` call: the
`_cleaning` assignment no longer triggers any refusal.

**New blocker exposed, NOT fixed**: with that gap out of the way, the
isolated compile now fails on `raise cls.errors[0]` (test method body,
~line 68) — `unsupported \`raise\` value expression in generator body
(only \`raise ExcName(...)\`/\`raise ExcName\` with a statically known
exception class name is supported)`. `cls.errors[0]` is a previously
CAUGHT exception instance re-raised by value, not a fresh
`SomeException(...)` construction with a statically-known class name —
this codegen's coroutine `raise` lowering has no representation for
re-raising an arbitrary runtime exception VALUE (as opposed to
constructing a new instance of a statically-named class), which is a
separate, structural gap (dynamic exception-value re-raise, not
narrowly fixable the way the assignment-target gap was). Not attempted
here — file still does not build end-to-end.

Quality gate for the assignment-write fix: `test_gimple.py` 253/253,
`test_module_cache.py` 76/76, `make check-selfhost` clean, from-scratch
stdlib dylib rebuild 0 skips.

## Status (updated 2026-08-24 -- re-verified, unchanged)

Re-checked this session while triaging the C3 cluster. The blocker (inherited `test` classmethod generator reading `cls.del_calls`/etc. -- no class-level attribute-access story for compiled generators) is unaffected by this session's two landed fixes (stdin/stdout/stderr field-name escaping; more char* string methods in coroutine bodies). Still structural; untouched.


## Status (updated 2026-08-23 — STILL-OPEN)

Re-ran the repro: identical refusal on every inherited `test`
classmethod generator (`cls.del_calls` etc.) — no class-level attribute
access exists for compiled generators. Structural, unchanged. Gate verification (2026-08-23): `test_gimple.py` 250 passed / 0 failed;
`test_module_cache.py` 76 / 0; `make check-selfhost` clean; from-scratch
stdlib dylib rebuild EXIT=0 with **0** `skip <module>:` lines — matching
the pre-change baseline of exactly 0 skips.

## Status (re-verified 2026-08-09)

Re-verified against current master (fast-forwarded to `e5daa1d`, no
intervening commits touch generator classmethod/`cls` handling) via a
real `MOJO_DEBUG=1 python3 mojo.py build` run — reproduces identically
to 2026-08-07: every inherited `test` classmethod generator method is
refused with the exact same message (`"a @classmethod generator that
references `cls` in its body is not supported (no class-level attribute/
method access exists yet for compiled generators)"`), and the module
still hits the same whole-module `"cannot compile module: function(s)
test ..."` fallback. Confirmed structural, unchanged, no action taken.

## Status (updated 2026-08-07)

**Classification bug FIXED, this file STILL FAILS to compile (expected
— see below).** `bugs/hard/CODEGEN_generator_classmethod_first_param_
must_be_self.md` — the hard-bug doc this file was classified against —
is now fixed: `_gen_cpp_generator_unit`'s method-eligibility check (and
two related call sites with the identical bug pattern, found while
verifying the fix) now correctly recognize `cls` as a valid generator-
method receiver name, not just `self`.

That hard-bug doc's ORIGINAL text speculated that THIS file's `test`
method might newly compile once the check was widened, on the claim
that `test`'s body "doesn't actually touch `cls`". That claim was
**wrong** — `test`'s body (`Lib/test/test_finalization.py` ~line 54-70)
reads `cls.del_calls`, `cls.tp_del_calls`, `cls.errors` repeatedly. Since
this codegen has no class-level attribute-access story, `test` is
(correctly) STILL refused post-fix — just with an accurate message now
(`"a @classmethod generator that references `cls` in its body is not
supported"`) instead of the old, misleading `"must take `self` as its
first parameter"`. Confirmed via `MOJO_DEBUG=1 python3` against
`compile_to_gimple` on this file's real source: all 16 inherited-
subclass refusals now show the corrected message, and the module still
raises the same whole-module `"cannot compile module: function(s) test
..."` fallback as before the fix — no change in whether this SPECIFIC
file compiles, only in the accuracy of why `test` is refused (and, per
the hard-bug doc, eliminating a real C++-miscompile risk the old code
path had for any classmethod generator that DOES reference `cls`,
confirmed via a separate hand-built repro, not this file).

This file remains in `bugs/COMPILE_FAIL_*`-style "not yet compiling"
territory, but no longer because of a compiler bug in the eligibility
check — `test` is refused for the same fundamental reason a `self.
other_method()` call inside an ordinary generator is refused: this
narrow coroutine codegen step's attribute/method-access support is
intentionally scoped to `self.<scalar field>` reads only, and has no
class-level equivalent yet. That would be new, non-trivial scope (real
design, not a one-line fix), not a bug — out of scope for this pass.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/test/test_finalization.py
