# CODEGEN_generator_function: Lib/test/test_finalization.py

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
