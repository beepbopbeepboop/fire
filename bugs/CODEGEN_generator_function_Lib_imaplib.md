# CODEGEN_generator_function: Lib/imaplib.py

## Status (updated 2026-08-06)

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
