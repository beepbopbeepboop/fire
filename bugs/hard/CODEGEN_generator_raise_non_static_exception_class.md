# HARD BUG: `raise <dynamic-expression>(...)` inside a generator body is refused, hard-failing the whole module

## Status (updated 2026-08-07)

**Re-verified FIXED 2026-08-23**: this doc's own minimal repro
(`Widget.gen`, `raise self._boom.exc_cls("dynamic raise inside a
generator")`) now builds clean end-to-end via `python3 mojo.py build`
(exit 0, no "unsupported `raise` value expression" refusal anywhere)
AND the binary RUNS, actually throwing at runtime with the correct
message (`Unhandled exception: dynamic raise inside a generator`) —
stronger than this doc's original g++ `-fsyntax-only`-in-isolation
verification. No regression.

**FIXED** (task #149), scoped to `raise <MemberExpr>(...)`/bare
`raise <MemberExpr>` specifically (the confirmed real-world shape).
Root-caused 2026-08-06 while classifying the `CODEGEN_generator_
function_Lib_*.md` cluster (tasks #95-135) — found first in
`Lib/imaplib.py`, then confirmed recurring at least twice more in
`Lib/test/support/`'s helpers (`run_with_locale`, `subst_drive`).

`_cpp_raise_stmt` now falls back to the SAME untyped(0)/lenient-match
`_MojoCppExc` representation the codebase already used for the
adjacent "`raise e`, a handler-bound IdentExpr with no statically-known
class name" case — this was already an accepted, documented
convention (`_cpp_try_stmt`'s own docstring: "untagged(0) lenient
match on the first typed handler"; the ordinary GIMPLE path's
`_gen_stmt_TryStmt` does the identical thing), not a new mechanism.
The message argument (if any, from `raise <MemberExpr>(<msg>)`) is
lowered exactly like the existing `raise ExcName(<msg>)` case's
`msg_arg` handling (string literal / f-string / arbitrary expression).
A dynamically-resolved raise necessarily loses precise except-type
matching (an `except SpecificError:` may over-eagerly catch it, same
tradeoff `raise e` already makes) — accepted, not solved, since solving
it for real would need static class-attribute-value tracking this
codegen has no infrastructure for at all (see the original "What a fix
needs" analysis retained below, still accurate for why the FULL,
type-precise version of this fix wasn't attempted).

## Verification

Hand-verified via `compile_to_gimple_with_cpp` + `g++ -fsyntax-only`:
both `raise self._boom.exc_cls("message")` (CallExpr with a MemberExpr
callee) and bare `raise self._boom.exc_cls` (no call) now emit a valid
`throw _MojoCppExc{...}` instead of raising `_UnsupportedGeneratorShape`
— confirmed g++-clean in isolation (a single-level `self.<scalar
field>` raise target). This doc's own minimal repro (`Widget.gen`,
`raise self._boom.exc_cls(...)`) now proceeds past the raise-
eligibility check.

**Important finding, not a regression**: the real `imaplib.py` file
(`Idler.burst`) does NOT fully compile end-to-end even after this fix
— `self._imap` is itself a struct-typed field, and `burst`'s body ALSO
calls `next(self)` and `self._pop(...)`, none of which this narrow
generator-body model's `_cpp_expr`/`_cpp_stmt` coverage supports today.
Before this fix, `burst` was refused CLEANLY at the Python level (the
raise check fired FIRST); after this fix, since the raise no longer
blocks it, `_gen_cpp_generator_unit` proceeds and produces SYNTACTICALLY
PLAUSIBLE-LOOKING but actually INVALID C++ for these OTHER, unrelated,
pre-existing unhandled shapes (confirmed via a direct g++ compile of
the generated `.cpp`: real errors like `request for member 'sock' in
'self->Idler::_imap', which is of non-class type 'int64_t'` and
`'next' was not declared in this scope`) — these are NOT caught by any
existing eligibility check and were ALREADY silently mis-generating
before this fix, just never reached because the raise check refused
`burst` first. This is a genuinely separate, pre-existing architectural
gap (`_cpp_expr`/`_cpp_stmt` lack coverage-completeness checking —
unhandled constructs silently fall through to best-effort text instead
of raising `_UnsupportedGeneratorShape`), NOT introduced by this fix,
and NOT a regression in outcome: `imaplib.py`'s whole-module compile
was already failing before this fix (for the raise reason) and is
still failing after it (now for these other reasons) — same end
result, just a different internal blocker. Confirmed via the required
5-part gate (below) that this pre-existing gap does not affect any file
in the gate's corpus (`imaplib.py`/`test.support` are real CPython
`Lib/` files, not part of `compile_stdlib.py`'s 664-file `.mojo` corpus
or the Mojo-stdlib dylib build). Worth its own hard-bug doc in a future
session (`_cpp_expr`/`_cpp_stmt` silently emitting invalid C++ for
unhandled shapes instead of refusing) — not attempted here, out of
scope for this narrowly-targeted raise fix.

## Gate

All five gates in CLAUDE.md's quality-gate section passed: `test_gimple.
py` (247/247), `test_module_cache.py` (76/76), `make check-selfhost`
clean, from-scratch `libmojostdlib.dylib` rebuild (0 `skip <module>:`
lines), `compile_stdlib.py -j8` (664/664, 0 unexpected — unchanged
count).

## Original diagnosis (unfixed-era notes, kept for history)

Not attempted at the time — see "What a fix needs" below.

## Symptom

```
[gimple_codegen] generator method Idler.'burst' not eligible (pass 2): unsupported `raise` value expression in generator body (only `raise ExcName(...)`/`raise ExcName` with a statically known exception class name is supported)
[gimple_codegen] generator 'run_with_locale' not eligible for C++ coroutine path, falling back to honest refusal: unsupported `raise` value expression in generator body (only `raise ExcName(...)`/`raise ExcName` with a statically known exception class name is supported)
[gimple_codegen] generator 'subst_drive' not eligible for C++ coroutine path, falling back to honest refusal: unsupported `raise` value expression in generator body (only `raise ExcName(...)`/`raise ExcName` with a statically known exception class name is supported)
```
Each refusal, when the affected generator is reachable at module level,
escalates to the same fatal whole-module `RuntimeError` documented in
`bugs/hard/CODEGEN_generator_struct_typed_param_refused.md`'s Symptom
section (the "message claims graceful fallback, CLI path doesn't
actually take it" pattern is now confirmed across three independent
hard-bug docs in this cluster, so it's clearly a general property of
`gen_module`'s top-level-file handling, not specific to any one gap).

## Root cause

`Idler.burst` (`Lib/imaplib.py`):
```python
def burst(self, interval=0.1):
    if not self._imap.sock:
        raise self._imap.error('burst() requires a socket connection')
    ...
    yield next(self)
```
`raise self._imap.error(...)` raises an exception class resolved via a
runtime `MemberExpr` (`self._imap.error` — a class object stored as an
instance attribute, `imaplib.IMAP4.error`/`.abort`/`.readonly`'s own
established idiom for letting subclasses customize their exception
types) rather than a bare, statically-known class name.

The coroutine codegen's `raise`-lowering (Milestone D's real-C++-
exceptions-confined-to-the-generator's-own-translation-unit design,
`_cpp_raise_stmt`) needs to resolve the exception class to a concrete
C++ type/constructor at COMPILE time to build the corresponding
`throw` expression — a `raise <MemberExpr>(...)`/`raise <MemberExpr>`
target has no such statically-known name to look up, so it's refused
unconditionally, regardless of what the member expression would actually
evaluate to at runtime.

## Confirmed occurrences

- `Lib/imaplib.py`: `Idler.burst` — `raise self._imap.error(...)`. See
  `bugs/CODEGEN_generator_function_Lib_imaplib.md`.
- `Lib/test/support/__init__.py` (or a sibling `test.support` submodule
  — exact file not pinned down, reached transitively while building
  `Lib/test/_test_eintr.py` as this cluster's 41st-adjacent target):
  `run_with_locale` and `subst_drive`, both generators whose bodies
  raise a dynamically-resolved exception class (plausible shape, per
  the function names: `run_with_locale` likely does `raise
  unittest.SkipTest(...)`-via-an-attribute or similar; not independently
  read from source in this pass — flagged from the `MOJO_DEBUG` refusal
  message alone).

Three independent confirmations (different files, different authors'
idioms) is enough to treat "a generator raising a NON-bare-identifier
exception class expression" as a real, recurring shape in ordinary
Python code — not a one-off.

## What a fix needs

The general case (an arbitrary runtime expression evaluating to an
exception class) is genuinely hard for a compile-time `throw` — but the
COMMON case seen in all three confirmed occurrences is narrower:
`raise <MemberExpr>(...)` where the member expression is a SIMPLE
attribute chain (`self.foo.error`, `obj.SkipTest`) that could, in
principle, be resolved through the same struct-field-type machinery this
codegen already uses elsewhere (`struct_field_types`) IF the attribute's
value is itself always one of a small, statically-enumerable set of
exception classes (e.g. `self._imap.error` is always exactly
`IMAP4.error` for any real `Idler` instance, since `_imap`'s type is
known). A real fix would need to:
1. Resolve the `MemberExpr`'s static type the same way an ordinary
   (non-generator) field access already does.
2. Confirm that resolved type is itself an exception class (subclass of
   `Exception`) with a compile-time-known C++ representation.
3. Emit the SAME `throw` shape `_cpp_raise_stmt` already emits for a
   bare `raise ExcName(...)`, just with the class resolved indirectly.

This is a real, if bounded, extension to `_cpp_raise_stmt` — not
attempted here, in keeping with this task's guidance to prefer accurate
classification over speculative fixes to the less-mature coroutine
codegen path.

## Minimal repro

```python
class Boom:
    def __init__(self, exc_cls):
        self.exc_cls = exc_cls

class Widget:
    def __init__(self, boom):
        self._boom = boom
    def gen(self):
        if True:
            raise self._boom.exc_cls("dynamic raise inside a generator")
        yield 1

def main():
    w = Widget(Boom(ValueError))
    for x in w.gen():
        print(x)

main()
```
Expected (per root cause above): `Widget.gen` refused at the generator-
eligibility pre-filter with the same "unsupported `raise` value
expression" message, before any C++ is emitted.
