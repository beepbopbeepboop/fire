# TEST_modcache_in_tu_instantiation_generic_source_text

## Summary
`python3 test_module_cache.py` aborts at `test_in_tu_instantiation(wd)` with
`AttributeError: '_G' object has no attribute '_generic_source_text'`. The
fake `_G` used by that test predates commit `ac924a1ef` ("codegen: a
module-local generic instantiates at its float literal's type"), which made
`elab_intu._module_src` read the template through the real
`GimpleGen._generic_source_text(path)` helper. The fake object was never
updated, so every call to `EI._protocol_only_overloads(_G(), ...)` now dies.

This is unrelated to free-function import qualification; it was hit while
running the file to verify SB-1 (`IMPORT_ambiguous_sibling_function`). It is
a whole-file abort: everything after it in `main()`, including the three
SB-1 tests, is silently not run.

## What was run / seen
```
$ python3 test_module_cache.py
...
PASS  mangle#10: every mangled suffix decodes back to its (key, value) pairs (4920 round-trips)
Traceback (most recent call last):
  ...
  File ".../test_module_cache.py", line 2100, in test_in_tu_instantiation
    all(EI._protocol_only_overloads(_G(), n)
  File ".../mojo/backend_gimple/elab_intu.py", line 323, in _module_src
    return gen._generic_source_text(path)
AttributeError: '_G' object has no attribute '_generic_source_text'
```
442 checks had PASSed before the abort; nothing reported FAIL.

## Expected
`python3 test_module_cache.py` runs to the end and reports
`Results: N passed, 0 failed` on master.

## Exact next step
Give the `_G` fake in `test_in_tu_instantiation`
(`test_module_cache.py`, around line 2085) the same two-argument contract the
real helper has — `_generic_source_text(self, path)` returning the module
source at `path` — e.g.:

```python
def _generic_source_text(self, path):
    return open(path).read() if _os.path.exists(path) else ''
```

(or, better, keep the fake in sync by delegating to a real `GimpleGen` if one
can be constructed cheaply). Then re-run `python3 test_module_cache.py` and
confirm the three SB-1 tests after `test_in_tu_instantiation` run.
