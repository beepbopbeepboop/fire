# HARD BUG: `raise <dynamic-expression>(...)` inside a generator body is refused, hard-failing the whole module

## Status

Unfixed. Root-caused 2026-08-06 while classifying the `CODEGEN_generator_
function_Lib_*.md` cluster (tasks #95-135) — found first in
`Lib/imaplib.py`, then confirmed recurring at least twice more in
`Lib/test/support/`'s helpers (`run_with_locale`, `subst_drive` —
transitively reached while diagnosing `Lib/test/_test_eintr.py`, not
itself one of this cluster's 41 target files but the concrete trigger
site). Not attempted — see "What a fix needs" below.

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
