# Companion .cpp generator body: the `for` tuple target and the stubbed statements (part 1 of 4)

Part 1 of 4 of `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_parser_parser___init__.md`
(SPLIT 2026-11-11). This part is the tuple-target family of the companion's
generator-body lowering: **seven of the eight remaining g++ errors** plus the
silently-wrong stubbed statements. The sibling parts: part 2 (the companion
dict-store slot — FIXED 2026-11-12, its doc deleted with the fix; it was
downstream of this one), part 3 (the `.iterutil` import-floor refusal,
`bugs/…-part3.md`), part 4 (the `..info` import-floor refusal,
`bugs/mid/…-part4.md`) — the latter two independent of part 1.

## Summary

Building `c_parser/parser/__init__.py` from a copy of the upstream
`Python-3.14.6/Tools/c-analyzer/` tree fails in the C++20 companion
`__init___gen.cpp`'s `_mojogen__iter_source_impl` — the companion emitter's
residue around the `_iter_source` generator (`c_parser/parser/__init__.py:167-204`,
`def _iter_source(lines, *, maxtext=11_000, maxlines=200, showtext=False)`).
The C side is clean; the build's rc=1 is the g++ step. The companion emitter
does not lower the generator body's `for` loop over a tuple-valued iterable:
the loop target halves and the following element reads are emitted as
placeholders, and several method-call statements in the body are stubbed to
`0` instead of lowered.

## Measurements (2026-10-29, carried from the parent doc's latest entry)

Eight g++ errors in `__init___gen.cpp` (the 2026-10-29 constructor-call fix
took 11 → 8). This part owns seven of them, the tuple-target family:

* `:165`–`:169` — `filename = ({0, 0, 0})[0]` / `lno = ({0, 0, 0})[1]` /
  `text = ({0, 0, 0})[2]`: the `for fileinfo, line in lines` target and the
  following tuple unpack are emitted as placeholders, read as `int[int]`,
  plus `expected ';' before '}'` on each line (six errors).
* `:171:28` — `char*` → `int64_t` conversion on the `text` slot (same family).

Not errors, but the same feature and the real size of it: the body also
carries `0;` / `while (0)` / `if (0)` for the method-call statements
(`srcinfo._add_line`, `srcinfo.too_much`, `srcinfo._used()`) — the lowering
stubs whole statements to `0` (confirmed by `_debug_note` "stubbed operation"
output; re-confirm before choosing an order). Such a body COMPILES but is
silently wrong, so the regression must be a run comparison, not a compile.

Landed already (context, NOT this part): the companion's struct-constructor
call lowering (default-argument fill through `_cpp_pad_struct_method_call_args`
+ `->` for a constructor result via `_cpp_is_struct_ctor_call`, both in
`mojo/backend_gimple/cpp_core.py`), regression
`test_gimple_generator_runner.py::generator_struct_ctor_fills_a_trailing_default`
in `run_ctor_default_arg_in_generator_tests`.

## Repro / measure

```
rm -rf .tmp/ca && cp -R /Users/mrs/net/Python-3.14.6/Tools/c-analyzer .tmp/ca
python3 tools/memslot.py --gb 8 --label ca-parser-build -- \
  python3 fire.py build -o .tmp/out/rNN .tmp/ca/c_parser/parser/__init__.py
grep -n "error:" .tmp/out/rNN/build.log   # or however the g++ stage reports; count the g++ errors in __init___gen.cpp
```

arm64. The errors above are line:column in the generated `__init___gen.cpp`;
lines will drift if the tree's emitter output changes — identify them by the
signatures (the `({0, 0, 0})[N]` placeholders, the `expected ';' before '}'`
pairs, the `char*`→`int64_t` conversion on the `text` slot), not by number.

## Root cause / next step

The companion emitter's generator-body statement lowering in
`mojo/backend_gimple/cpp_core.py` (the `_cpp_stmt` / `_cpp_for_stmt` /
`_cpp_expr` paths; the "stubbed operation" `_debug_note` sites are where the
`0` stubs come from) does not lower, for a generator body of the `_iter_source`
shape:

1. the `for`-loop TUPLE target over a parameter that yields 2-tuples
   (`for fileinfo, line in lines:`) — the target halves must bind the
   iterator's element fields, and element reads off the first half
   (`fileinfo.filename`, `fileinfo.lno`) must read those fields, not
   `({0,0,0})[N]`;
2. the method calls on the stored struct instance: as an EXPRESSION statement
   (`srcinfo._add_line(line, fileinfo.lno)`), in an `if` condition
   (`if srcinfo.too_much(maxtext, maxlines):`) and in a `while` condition
   (`while srcinfo._used():`) — currently stubbed to `0`/`while (0)`/`if (0)`.

Parent doc's ordering (2026-10-29): do THIS first — it accounts for six of the
eight remaining errors (`:165`–`:169`) and the stubbed statements are the same
family. Do NOT start from the `:149:219` dict-store error (part 2); it is
downstream of the same generator body.

## Regression

In `test_gimple_generator_runner.py`, next to `run_ctor_default_arg_in_generator_tests`,
using the established package-fixture pattern: `_FOREIGN_PKG_FILES` gains the
struct (like `SourceInfo` is imported in the real case — a class with the
methods the body calls), and the consumer carries a keyword-only parameter
(`*, start=[]`) that forces the cpp path, because a single-file shape does NOT
reach the cpp path (the A3 backend takes simple generators) and would pass
before and after. The consumer's generator body must mirror the measured shape:
`for a, b in pairs:` over a parameter, element reads off the first half, and
method calls on a struct instance stored/used in the body as an expression
statement and in `if`/`while` conditions. The test compiles + runs + compares
stdout against CPython (run the CPython baseline first and assert on it, as
`_test_foreign_a3_generator_handle` does). It must FAIL before the fix (g++
error on the placeholder, or wrong output from the stubbed statements) and
pass after — verify both directions by reverting the `cpp_core.py` hunk.

## Done when

1. Rebuilding `.tmp/ca/c_parser/parser/__init__.py` shows the `:165`–`:171`
   family gone from `__init___gen.cpp`: no `({0, 0, 0})[N]` placeholders, no
   `expected ';' before '}'` pairs, no `char*`→`int64_t` on the `text` slot
   (the remaining g++ error, if any, is only the part-2 `:149` dict-store one).
2. The generated body lowers the three method-call statements for real (no
   `0;` / `while (0)` / `if (0)` where `srcinfo._add_line` / `too_much` /
   `_used()` belong).
3. The new regression test fails before the fix and passes after;
   `test_gimple_generator_runner.py` run once in full shows no NEW failures.
