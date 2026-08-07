# CODEGEN_generator_function: Lib/test/test_exception_group.py

## Status (updated 2026-08-06)

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
