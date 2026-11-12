# Companion .cpp dict-store: a struct pointer stored through an int64 slot (part 2 of 4)

Part 2 of 4 of `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_parser_parser___init__.md`
(SPLIT 2026-11-11). This part is ONE g++ error: the companion's dict-store
lowering stores a struct pointer through an int64 slot. The sibling parts:
part 1 (the companion's tuple-target/stubbed-statement family,
`bugs/mid/…-part1.md`, the PREREQUISITE — see below), part 3 (the `.iterutil`
import-floor refusal, `bugs/…-part3.md`), part 4 (the `..info` import-floor
refusal, `bugs/mid/…-part4.md`) — the latter two independent of parts 1-2.

## Summary

In the C++20 companion `__init___gen.cpp` for the `_iter_source` generator
(`c_parser/parser/__init__.py:167-204`), the line that stores the freshly
constructed `SourceInfo` into the `allinfo` dict — source `allinfo[filename] =
srcinfo`, where `srcinfo` is a `SourceInfo *` — is lowered with an int64
value slot, so g++ rejects it. This is the last of the eight 2026-10-29
g++ errors once part 1 lands.

## Measurement (2026-10-29, carried from the parent doc's latest entry)

* `__init___gen.cpp:149:219` — `invalid conversion from 'SourceInfo*' to
  'int64_t'`: a struct pointer stored into `allinfo` (a dict) through an
  int64 slot in the companion's dict-store lowering.
* The companion's DICT-LOOKUP of the same dict (`srcinfo = allinfo[filename]`
  on the `if fileinfo.filename in filestack:` branch) must agree with the
  store — check both directions in the generated code, not just the store.

Ordering (parent doc, 2026-10-29): "Do not start from the `:149` dict-store
error; it is downstream of the same generator body." **Prerequisite: part 1.**
If part 1 is not landed, a fixture for this shape still hits the stubbed
body-statement lowering and will not build end-to-end; the dict-store fix
itself is a separate lowering path and can be written independently, but its
Done-when measurement needs part 1's work in-tree. Re-measure first anyway:
if the error is already gone on current master, delete this doc in the same
commit with a pinning test.

## Repro / measure

```
rm -rf .tmp/ca && cp -R /Users/mrs/net/Python-3.14.6/Tools/c-analyzer .tmp/ca
python3 tools/memslot.py --gb 8 --label ca-parser-build -- \
  python3 fire.py build -o .tmp/out/rNN .tmp/ca/c_parser/parser/__init__.py
```

arm64. Identify the error by signature (`invalid conversion from 'SourceInfo*'
to 'int64_t'` on the `allinfo[...] = ...` line of the generated
`__init___gen.cpp`), not by line number — lines drift as the emitter changes.
After part 1 lands, this should be the ONLY g++ error left in the file; if it
is not, record the extra errors in a Status entry (they belong to the
corresponding sibling part).

## Root cause / next step

The companion's dict-store lowering (in `mojo/backend_gimple/cpp_core.py`,
the dict-store emission around `_cpp_expr`) types the value slot as `int64_t`
even when the stored value is a struct pointer (`StructName *`). Store the
value in the companion's struct-pointer representation and make the matching
dict-lookup read it back with the same type. Do not special-case the
`allinfo`/`filename` names: the fix is the slot typing, and the regression
fixture below exercises the same slot with different names.

## Regression

In `test_gimple_generator_runner.py`, next to `run_ctor_default_arg_in_generator_tests`,
using the established package-fixture pattern: `_FOREIGN_PKG_FILES` provides
the struct (as `box.py` does for the constructor regression — a class with a
method and/or a field so the read-back is observable), and the consumer
carries a keyword-only parameter (`*, start=[]`) that forces the cpp path.
The consumer's generator body: store a struct instance into a dict, read it
back, use a field/method of the read-back, and print something the stubbed or
int64-slot shape cannot produce. Compiles + runs + compares stdout against
CPython (assert the CPython baseline first, as the existing fixture tests do).
Fails before the fix (`invalid conversion from 'Box*' to 'int64_t'` class of
g++ error), passes after — verify both directions by reverting the hunk.

## Done when

1. Rebuilding `.tmp/ca/c_parser/parser/__init__.py` shows the `:149:219`
   signature gone from `__init___gen.cpp` (with part 1 landed: zero g++ errors
   in the file — if the file compiles clean, record the count in a Status entry).
2. The new regression test fails before the fix and passes after;
   `test_gimple_generator_runner.py` run once in full shows no NEW failures.
