# COMPILE_FAIL: Lib/ctypes/util.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/ctypes/util.py`

## Status (updated 2026-08-06)

Investigated 2026-08-06. Root-caused; not fixed — traces back to an
already-tracked, broader cross-module resolution gap. Low priority: the
failing code is dead test-only code, never reached by any real import.

```
error: variable or field '_t21' declared void
error: invalid use of void expression
```

at:
```python
################################################################
# test code

def test():
    from ctypes import cdll
    if os.name == "nt":
        print(cdll.msvcrt)
        print(cdll.load("msvcrt"))   # <- here
        print(find_library("msvcrt"))
    ...
```

## Root cause

`from ctypes import cdll` pulls in `cdll`, which in the real
`ctypes/__init__.py` is a MODULE-LEVEL VALUE (a struct instance, not a
function or class): `cdll = LibraryLoader(CDLL)`. Cross-module import
resolution here can't determine `cdll`'s real type, so it falls back to
emitting a generic weak stub for the unresolved symbol:

```c
#ifndef cdll
__attribute__((weak)) int64_t cdll (...) { mojo_print ((char *)"cdll: unavailable in compiled mode"); return (int64_t)0; }  /* stub from ctypes */
```

i.e. `cdll` gets treated as an unresolved CALLABLE returning `int64_t`,
not as a struct instance with a `.load(name)` method. `cdll.load("msvcrt")`
then lowers to a dynamic-dispatch call on that broken stub value, whose
return type resolves to `void` — and `print(<void-typed-expr>)` is
invalid C, producing the two errors above.

This is a variant of the SAME underlying gap already tracked for
`ctypes/__init__.py` itself (bugs/COMPILE_FAIL_ctypes___init__.md, task
#39) — that file's own compile has multiple unresolved issues
(`__ctype_le__`/`__ctype_be__` dynamic attributes, the CFUNCTYPE varargs-
packing bug), any of which could be why `ctypes/__init__.py`'s own
`LibraryLoader`/`cdll` never gets far enough to be visible to
`util.py`'s cross-module import resolution as a real, typed value. Not
independently root-caused further than that — `cdll`'s resolution
failure is downstream of `ctypes/__init__.py`'s own compile health, not
a bug specific to `util.py`.

## Priority note

The failing code is `def test():`, explicitly dead test/demo code at the
bottom of the file (guarded `if os.name == "nt":`, and this `test()`
function itself is never called by anything outside itself — no
`__main__` guard even invokes it in this file). Low priority relative to
real, reachable code paths. Worth revisiting once `ctypes/__init__.py`
(task #39) has a real, resolvable `cdll`/`LibraryLoader` — this file may
simply compile clean once that upstream dependency does, without any
change needed here at all.
