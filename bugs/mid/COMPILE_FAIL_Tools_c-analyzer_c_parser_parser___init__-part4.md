# Import floor: `..info` — `rendered, = rendered` cannot materialize a generator (part 4 of 4)

Part 4 of 4 of `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_parser_parser___init__.md`
(SPLIT 2026-11-11). This part is the C-side import-floor refusal of
`c_parser/info.py` in `c_parser/parser/__init__.py`'s full import chain.
The sibling parts: part 1 (`bugs/mid/…-part1.md`, the companion's tuple-target
family) and part 2 (`bugs/…-part2.md`, the companion's dict-store slot) — the
companion `.cpp` work, independent of this one — and part 3
(`bugs/…-part3.md`, the `.iterutil` refusal, the other half of this floor).

## Summary

Building `c_parser/parser/__init__.py` from a copy of the upstream
`Python-3.14.6/Tools/c-analyzer/` tree refuses the imported module
`c_parser/info.py` before the companion `.cpp` step is reached:

```
# ERROR: compiling imported module '..info' from .../c_parser/info.py:
  cannot materialize a generator as a list: no known generator API for 'rendered'
```

The site is `HighlevelParsedItem._data_as_row`: `rendered =
cls._render_data_row_item(...)` then `rendered, = rendered`, where
`_render_data_row_item` returns `cls._format_data('row', data, extra)` and
`_format_data` IS a generator. `rendered` legitimately holds a generator, and
`a, = b` on a generator means "take its first yielded value". This refusal
decides whether the `_iter_source` module compiles at all under the full
import chain.

## Measurements (carried from the parent doc)

* 2026-10-29 (latest entry): "Imported-module floor unchanged (`.iterutil`'s
  `next(...)`, `..info`'s `rendered, = rendered`)" — the refusal above is
  still the `..info` line as of the parent doc's last measurement.
* 2026-10-02 entry: the SINGLE-FILE shape was measured compiling and running —
  `rendered = self._gen(x); a, = rendered` works for an instance method, a
  bare-name "classmethod", and a real `@classmethod` (prints 42 in all three),
  because `_generator_method_api` and the method-returns-a-generator
  counterpart exist on the coroutine path. So: measure the IN-CHAIN refusal
  first, and if a single-file repro of `c_parser/info.py`'s exact shape
  compiles cleanly, the defect is in what the chain adds (the import/inline
  path, the module-level context) — record the split in a Status entry
  before extending anything.

## Repro / measure

```
rm -rf .tmp/ca && cp -R /Users/mrs/net/Python-3.14.6/Tools/c-analyzer .tmp/ca
python3 tools/memslot.py --gb 8 --label ca-parser-build -- \
  python3 fire.py build -o .tmp/out/rNN .tmp/ca/c_parser/parser/__init__.py
```

arm64. Grep the build output for `compiling imported module '..info'`.
A cheaper companion check: build `c_parser/info.py` alone (`.tmp/ca/c_parser/
info.py`) and note whether it compiles — if the standalone build is GREEN but
the in-chain spelling refuses, that split is the defect and the fix belongs
in the import/inline path, not the single-file emitter.

## Root cause / next step

Parent doc's 2026-10-04 entry, item 1, is the analysis (read it before
starting): the ordinary C-side path types the local correctly but never
records the api. `_generator_var_api` is populated for a bare-name compiled
generator call (`_emit_generator_start_call`, `mojo/backend_gimple/emit_calls.
py`) and for a function that RETURNS a generator (the `_fn_returns_generator`
block, `emit_calls.py:5378`) — neither covers a call to a compiled GENERATOR
METHOD through `cls.`, nor a method that returns one. Fixing it needs:

1. the `cls.<genmethod>(...)` construction — the `__mgco_<Struct>_<method>
   _start` symbol is already registered in `_generator_method_api` (the
   coroutine path reads it; `cpp_core.py:5373` for the coroutine path); the
   ordinary path does not; and
2. the method-returns-a-generator counterpart of `_fn_returns_generator`.

**Downstream of this refusal, OUT OF SCOPE here** (record, do not chase): the
parent doc's 2026-10-23 row-14 measurement says once `c_parser.info` compiles
further, the next refusal in the module is `conflicting types for
'info_get_default_storage_9f63a2'` — `module_gen.py`'s `/* from .info */`
text-scan re-export block types the UNANNOTATED `def get_default_storage(decl)`
from the scanner's int64 default beside a same-TU definition typed `char *`
from the body's returns (the "type-mismatch hazard" documented in that
emitter's own comment; the `MojoTuple_` branch a few lines below already
consults the definition-side store via `_func_return_type_for_call`, and
extending that to the unannotated-return case is the documented fix shape).
That hazard is tracked under the `c_analyzer/__main__.py` doc's closure
(roadmap row 13, a sibling worker's territory) — if your work surfaces it,
note it in a Status entry and stop at the part-4 boundary.

## Regression

In `test_gimple_runner.py` (the shape is single-file C-side per the 2026-10-02
measurement): a `cls.<genmethod>(...)` call where the method RETURNS a
generator, followed by `a, = rendered`, compiled + run + compared against
CPython — using the parent doc's 2026-10-02 measured shapes (instance method,
bare-name "classmethod", real `@classmethod`; the 42-printing case). If the
re-measurement shows the defect is in the IMPORT/inline path rather than the
single-file emitter, the regression instead builds the minimal import chain
that triggers the in-chain refusal (a package fixture mirroring
`c_parser/info.py`'s `_data_as_row` shape), next to the existing package
fixtures; in that case `test_gimple_generator_runner.py`'s foreign-package
pattern is the model. Fails before the fix, passes after — verify both
directions by reverting the hunk.

## Done when

1. Rebuilding `.tmp/ca/c_parser/parser/__init__.py` reports NO
   `# ERROR: compiling imported module '..info'` line (the floor list, if
   any, contains only the `.iterutil` refusal tracked by part 3).
2. The new regression test fails before the fix and passes after; the one
   existing test file covering the touched code (`test_gimple_runner.py`, or
   `test_gimple_generator_runner.py` if the import-path fixture is what the
   re-measurement demands) run once in full shows no NEW failures.
