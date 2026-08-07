# CODEGEN_generator_function: Lib/test/crashers/gc_inspection.py

## Status (updated 2026-08-06)

**STILL FAILING**, confirmed reproducing against current master
(`2b0c4c5`) with a specific, now fully root-caused reason.

```
$ MOJO_DEBUG=1 python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/test/crashers/gc_inspection.py
[gimple_codegen] generator 'g' not eligible for C++ coroutine path, falling back to honest refusal: only a plain identifier assignment target is supported
Error building: cannot compile module: function(s) g (generator function(s), ...) — falling back to interpreting this module from source instead
```

**Classification: `bugs/hard/CODEGEN_generator_non_plain_assignment_
target_refused.md`** (this file is the doc's primary confirmed
occurrence). `g`'s body:
```python
def g():
    marker = object()
    yield marker
    [tup] = [x for x in gc.get_referrers(marker) if type(x) is tuple]
    print(tup)
    print(tup[1])
```
`[tup] = [...]` is a list-pattern destructuring assignment — the
coroutine codegen's generator-body assignment lowering only supports a
bare identifier target, refusing any other shape (tuple/list unpack,
subscript, attribute) wholesale. See the hard-bug doc for full root
cause and fix-scope notes (2 more independent confirmations found
elsewhere in this cluster's pass).

Not fixed here — narrow-looking but inside the coroutine `.cpp`
statement-lowering path, which this task's guidance flags as warranting
its own dedicated verification pass.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/test/crashers/gc_inspection.py
