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

## Status

### 2026-11-12 — partial fix landed (struct pointer read back through a local dict)

Root cause found by reproduction, not by the `:149` g++ signature: the dict
STORE was already correct (`mojo_dict_set_int(d, k, (int64_t)(b))`), but the
READ-BACK was typed as the int64 default. `got = allinfo['a']` declared `got`
as `int64_t`, so `got.x` lowered to `mojo_getattr_any((void*)got, "x")` on a
raw struct pointer word and the program printed nothing (crash, no g++ error).
Reproduced standalone with `test_gimple_generator_runner._FOREIGN_PKG_FILES`
(`box.py`) before the fix.

Landed:
- `mojo/backend_gimple/cpp_core.py`: `_cpp_prescan_dict_struct_values` seeds a
  per-unit `_cpp_local_dict_val_types` (local dict name -> `S *`) from the
  generator body before lowering. A dict qualifies when every store into it
  is a struct constructor call or a local provably bound only to `S(...)`
  constructors (every other binder, including tuple/for/with/walrus/augassign,
  poisons the name). The prescan runs before body lowering, so a read that
  textually precedes its store is still typed. SubscriptExpr read lowering
  emits `(S *)mojo_dict_get_int(...)` for such dicts.
- `mojo/middle/exprtypes.py`: `_infer_simple_expr_ctype`'s SubscriptExpr case
  returns the dict's `dict_val_types` entry when present (before: always int64).
- `mojo/backend_gimple/cpp_async.py`: seeds the registry for the generator unit.
- `test_gimple_generator_runner.py`: `run_struct_ptr_through_local_dict_tests`
  (two fixtures: a plain read-back, and the textual read-before-store shape of
  `_iter_source`). The read-before-store fixture FAILS on the pre-fix tree
  (`compiled stdout '' != CPython '9\n'`) and PASSES after.

Quick test: `python3 tools/memslot.py --gb 8 -- python3 test_gimple_generator_runner.py`
— before 23 FAIL, after 22 FAIL; the one difference is the new test passing.
No new failures. The 22 remaining failures are pre-existing and unrelated.

Not done (Done-when item 1 unverified):
- The real `c_parser/parser/__init__.py` rebuild was NOT run this session
  (heavy `fire.py build`; left to the integrator). The `:149:219` signature was
  not re-measured.
- Part 1 (the tuple-target / stubbed-statement prerequisite) is still
  unlanded, so the companion may still hit other g++ errors before this one
  is observable end-to-end.
- Scope limits of the prescan: only the generator unit seeds it (async units
  do not yet); a dict whose value type is only provable through a call or a
  method return is left as the int64 default.

Doc kept (not deleted): the named Done-when item 1 is not satisfied yet.
