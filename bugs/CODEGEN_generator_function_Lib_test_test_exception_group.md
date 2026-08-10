# CODEGEN_generator_function: Lib/test/test_exception_group.py

## Status (updated 2026-08-09)

Re-verified against current master (`42faf64`) with a real
`MOJO_DEBUG=1 python3 mojo.py build`. The recursive-`yield-from`
classification below (task #138, `bugs/hard/
CODEGEN_generator_recursive_yield_from_no_arg_forwarding.md`) is
confirmed to remain fixed — no cascade of malformed declarations.

The refusal `leaf_generator` now hits has changed and is cleaner than
what's described below: it's now refused up front, purely on the
tuple-valued `yield exc, tbs` at the very end of its body:
```
[gimple_codegen] generator 'leaf_generator' not eligible for C++ coroutine
path, falling back to honest refusal: leaf_generator: every `yield` must
carry a value, and all values must agree on one scalar type
(int64_t/double/_Bool)
```
This is a clean, honest, CORRECT refusal — not a miscompile or cascade —
from `_infer_generator_yield_ctype`'s `TupleExpr` branch in
`gimple_codegen.py` (currently ~line 2699-2724): a multi-element `yield
a, b` has no representation in this generator-body model's single-scalar
promise type, and the function deliberately returns `None` (triggering
the same graceful "not eligible" fallback every other unsupported shape
gets) rather than letting the tuple sail through to `_cpp_stmt` and emit
invalid C++.

This is the **single most common gap across the whole
`CODEGEN_generator_function_Lib_*` doc family** (per this task's
briefing) — also hit by, at least, `Lib/dis.py`, `Lib/ftplib.py`,
`Lib/pkgutil.py`, and `Lib/test/libregrtest/save_env.py`. It is
correctly classified as structural, not narrow: fixing it for real means
threading a real N-scalar (or boxed-tuple) `co_yield` payload type
through the whole coroutine promise/emission machinery
(`_infer_generator_yield_ctype`, the promise-type declaration, every
`_cpp_stmt` `YieldExpr` case, and the caller-side resume/value-extraction
API) — not a one-spot stub or missing-case fix. Not attempted here, per
this task's guidance to not force a fix on confirmed-structural gaps.

`leaf_generator`'s other previously-noted sibling gaps (`tbs.append(...)`
on an untyped param, `exc.__traceback__`/`exc.exceptions` attribute
access) are moot for this file now — the tuple-yield refusal fires
first, before those statements are ever reached by `_cpp_stmt`.

No code change made for this bug.

## Status (updated 2026-08-07)

**Classification bug FIXED for the reported symptom** (`bugs/hard/
CODEGEN_generator_recursive_yield_from_no_arg_forwarding.md`, task
#138) — the root cause (a self-recursive `yield from` can never find
itself in `self._generator_api` while its own body is still being
compiled, since registration only happens after the whole compile
succeeds) is fixed. Confirmed via a direct compile: the ~150-error
cascade of malformed declarations this doc reported (`type defaults to
'int'`, `conflicting types for 'mojo_list_append_int'`, etc.) is GONE
— the plain `.ci` output now compiles cleanly with `gcc -fgimple
-fsyntax-only` (0 errors, confirmed).

**`leaf_generator` STILL does not fully compile end-to-end**, for
OTHER, unrelated, pre-existing reasons in its own body (confirmed via
a direct g++ compile of the `.cpp`): `tbs.append(...)` (a method call
on an untyped param treated as a scalar `int64_t`), `exc.__traceback__`
/`exc.exceptions` (attribute access on the same), and `yield exc, tbs`
(a tuple yield, not a single scalar) are all out of this narrow
generator-body model's scope — separate, pre-existing gaps, not
introduced by this fix, and not attempted here. These now surface as
ordinary, LOCALIZED g++ errors rather than a cascading, hard-to-read
corruption — a real improvement in diagnosability even though the file
doesn't fully compile yet.

## Status (updated 2026-08-06, superseded above)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-30 `request for member 'append'` .cpp error no longer
reproduces, replaced by a much larger cascade of ~150 severely malformed
declaration errors directly in the plain `.ci` output (NOT a `_gen.cpp`
file):
```
/Users/mrs/net/Python-3.14.6/Lib/test/test_exception_group.py:576:3: error: type defaults to 'int' in declaration of 'mojo_list_append_int' [-Wimplicit-int]
/Users/mrs/net/Python-3.14.6/Lib/test/test_exception_group.py:576:3: error: conflicting types for 'mojo_list_append_int'; have 'int()'
/Users/mrs/net/Python-3.14.6/Lib/test/test_exception_group.py:593:3: error: type defaults to 'int' in declaration of '_mojogen_leaf_generator_destroy' [-Wimplicit-int]
```

**Classification: `bugs/hard/CODEGEN_generator_recursive_yield_from_no_
arg_forwarding.md`** (added as that doc's new "Additional real
occurrence" — its previous evidence was a synthetic minimal repro plus
one real file with a DIFFERENT failure mode; this is the first
confirmed REAL stdlib instance hitting a third, more severe failure
mode). Root cause: `leaf_generator(exc, tbs=None)`:
```python
def leaf_generator(exc, tbs=None):
    if tbs is None:
        tbs = []
    tbs.append(exc.__traceback__)
    if isinstance(exc, BaseExceptionGroup):
        for e in exc.exceptions:
            yield from leaf_generator(e, tbs)      # recursive yield from, extra param
    else:
        yield exc, tbs
    tbs.pop()
```
Exactly the hard-bug doc's own repro shape (recursive `yield from` to
itself, with a defaulted extra parameter `tbs`). Here it manifests as
the emission getting badly desynchronized around lines 574-598 — the
whole `_mojogen_leaf_generator_destroy`/runtime-helper declaration block
comes out with missing types/braces, cascading into unrelated-looking
errors against `mojo_list_append_int` and other runtime helpers.

Not fixed here — see the hard-bug doc's "What a real fix needs" section;
this is a substantial, pre-identified fix, not a narrow one.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/test/test_exception_group.py
