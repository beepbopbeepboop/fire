# `tables.read_table` consumer sees string tuple slots as words (tuple_slot_ctypes typing)

Part 2 of `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_tables.md`.
Class: easy (self-contained generator/producer typing fix for tuple slot C types).

## Goal

When `c_common.tables.read_table` iterates `for line, filename in strutil.parse_entries(entries, ignoresep=sep):`, the producer's yielded tuple slot types must reflect the actual element types so that a consumer observes string elements as `char *` / string values (not as `int64_t` words). The behavioural result of consuming `read_table` over real string rows must match CPython.

## Acceptance

- For a module-qualified delegated generator `for` over `strutil.parse_entries(...)` yielding `(item, None)` where `item` is a string, the registered/propagated `tuple_slot_ctypes` (or equivalent element typing) for the string slot is the string/pointer C type, not `int64_t`.
- Unpacking the yielded tuple in the consumer binds `line` as a string value usable as `char *` in the generated code; it must not be read as a raw integer word.
- The fix is in the producer/typing path (how tuple slot types are inferred and recorded), not a consumer-side cast that papers over an incorrect slot type.

## Done when

File: `test_gimple_generator_runner.py` (repo root).

Command: `python3 -c "import test_gimple_generator_runner as t; t._regression_tables_module_qualified_tuple_for()"`

The existing regression `_regression_tables_module_qualified_tuple_for` must pass. (As of the 2026-11-13 re-split status recorded in the original doc, routing was fixed but this regression still failed on tuple slot typing, with the string element recorded as `int64_t` rather than `char *`.)

## Notes

Measured context from the original doc: end-to-end `fire.py build -o .tmp/ca/tables_out .tmp/ca/c_common/tables.py` exits 0 and the binary runs, but the PRODUCER's `tuple_slot_ctypes` for `strutil.parse_entries` recorded `int64_t` for a string element (`yield item, None` with `item` bound by `for item in subentries:`), so a consumer's `line` was a word, not `char *`. The behavioural regression above failed on that typing, not on routing.
