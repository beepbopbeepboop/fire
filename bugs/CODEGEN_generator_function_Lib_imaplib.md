# CODEGEN_generator_function: Lib/imaplib.py

## Status (updated 2026-08-09, re-verified with a direct minimal repro)

Re-verified against current master (post-merge `7df52a0`). The full
`mojo.py build` on the real `imaplib.py` is currently uninformative on
its own for this specific bug: the whole-transitive-graph build now
fails much earlier, in unrelated code (a severe `ssl.py`/`argparse`
symbol clash causing GCC to bail out early with "confused by earlier
errors") before the log gives a clean read on `Idler.burst`'s own
generated `.cpp`. So this pass isolated the method with a minimal
standalone repro (`Idler`/`IMAP4` classes reduced to just the shapes
`burst()` touches: `self._imap.sock`, `next(self)`, `self._pop(...)`)
and ran `MOJO_DEBUG=1 python3 mojo.py build` on that directly.

Result: no "not eligible" refusal (confirms the `raise self._imap.error
(...)` fix from `bugs/hard/CODEGEN_generator_raise_non_static_
exception_class.md` still holds — the generator reaches real coroutine
`.cpp` generation), and the generated `.cpp` reproduces all three
previously-documented blockers verbatim, unchanged:
```
imaplib_burst_repro_gen.cpp:120:23: error: request for member 'sock' in 'self->Idler::_imap', which is of non-class type 'int64_t' {aka 'long long int'}
imaplib_burst_repro_gen.cpp:126:18: error: 'next' was not declared in this scope
imaplib_burst_repro_gen.cpp:140:13: error: 'response' was not declared in this scope
imaplib_burst_repro_gen.cpp:140:34: error: too many arguments to function 'int64_t Idler__pop(Idler*)'
```
The 4th (`response`/arity) is one symptom, not two: `self._pop(interval,
None)` — a call to a `self`-method from inside a generator body — gets
silently codegen'd as a call to `Idler__pop(self)` (dropping both real
args, per the doc's original "self.<field> reads only, no method calls"
observation), so the `while response := ...` walrus assignment target
is left undeclared when the call shape mismatch cascades.

No change in classification or scope: these are the SAME structural
"coroutine-body expression emitter doesn't model nested struct-field
attribute chains, the `next()` builtin, or `self`-method calls" gaps as
before, not narrow, not attempted here — still worth a dedicated hard-
bug doc for `_cpp_expr`/`_cpp_stmt`'s silent-fallthrough-instead-of-
refusing behavior on unhandled generator-body constructs (a future
session's task, not this one).

## Status (updated 2026-08-07)

**Classification bug FIXED** (`bugs/hard/CODEGEN_generator_raise_
non_static_exception_class.md`, task #149) — `raise self._imap.error
(...)` no longer refuses at the eligibility gate; `_cpp_raise_stmt` now
emits a valid (untyped/lenient-match) `_MojoCppExc` throw for it.

**`Idler.burst` STILL does not compile end-to-end**, for OTHER,
unrelated pre-existing reasons in the same method body, confirmed via a
direct g++ compile of the generated `.cpp`:
- `self._imap` is itself a struct-typed field; `self._imap.sock` (a
  nested attribute chain through it) isn't representable in this
  narrow generator-body model (`self.<scalar field>` reads only) —
  g++: `request for member 'sock' in 'self->Idler::_imap', which is of
  non-class type 'int64_t'`.
- `yield next(self)` calls the builtin `next()`, not supported —
  g++: `'next' was not declared in this scope`.
- `self._pop(interval, None)` calls a method on `self` — also out of
  this narrow model's scope (self.<field> reads only, no method
  calls) — silently emitted as a call to an undeclared function rather
  than refused.

These are NOT new — they were always unsupported, just never reached
because the raise check refused `burst` FIRST. `imaplib.py`'s overall
build outcome is unchanged (still fails, same as before) — only the
internal blocker moved. Worth a dedicated hard-bug doc in a future
session on `_cpp_expr`/`_cpp_stmt`'s silent-fallthrough-instead-of-
refusing gap for unhandled generator-body constructs; not attempted as
part of the raise fix (see that hard-bug doc's own "Important finding"
section for the full analysis, including confirmation via the required
gate that this doesn't affect any currently-passing file).

## Status (updated 2026-08-06, superseded above)

**STILL FAILING**, confirmed reproducing identically against current
master (`2b0c4c5`) — the 2026-07-30 note's diagnosis was correct; this
elaborates it.

```
$ MOJO_DEBUG=1 python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/imaplib.py
[gimple_codegen] generator method Idler.'burst' not eligible (pass 2): unsupported `raise` value expression in generator body (only `raise ExcName(...)`/`raise ExcName` with a statically known exception class name is supported)
Error building: cannot compile module: function(s) burst (generator function(s), contain a `yield`/`yield from`) — ... falling back to interpreting this module from source instead
```

**Root cause:** `Idler.burst`:
```python
def burst(self, interval=0.1):
    if not self._imap.sock:
        raise self._imap.error('burst() requires a socket connection')
    try:
        yield next(self)
    except StopIteration:
        return
    while response := self._pop(interval, None):
        yield response
```
`raise self._imap.error(...)` raises an exception CLASS resolved via a
runtime member-expression (`self._imap.error`, a class stored as an
instance attribute) rather than a statically-known bare class name
(`raise ValueError(...)`). The coroutine codegen's `raise`-lowering
(Milestone D's real-C++-exceptions-in-the-generator's-own-translation-
-unit design) requires the exception class to be resolvable at compile
time to build the corresponding C++ exception object/type — a `raise
<MemberExpr>(...)` shape has no such static class name to work with, so
it's refused outright, and (same escalation pattern as
`bugs/hard/CODEGEN_generator_struct_typed_param_refused.md`) a single
module-level-reachable refusal like this hard-fails the WHOLE file's
`mojo.py build`, not just this one generator method.

**Now folded into `bugs/hard/CODEGEN_generator_raise_non_static_
exception_class.md`** — confirmed recurring twice more (`test.support`'s
`run_with_locale`/`subst_drive`, found while diagnosing
`Lib/test/_test_eintr.py`), so promoted from "single instance" to a full
hard-bug doc. See that doc for the shared root cause and fix-scope
notes.

Not fixed here — same reasoning as the sibling struct-param-refusal
gap: a genuine coroutine-codegen scope boundary (exception-type
resolution needs to happen at C++ compile time), not a narrow accidental
bug.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/imaplib.py
