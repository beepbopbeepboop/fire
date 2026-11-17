# COMPILE_FAIL: Tools/c-analyzer/c_common/tables.py part 3 (module-qualified tuple-target foreign generator)

## Goal

Support a tuple-target `for` loop in a compiled generator body over a
module-qualified call to a foreign module's compiled generator (including
keyword arguments), delegating via the generator protocol and unpacking tuple
elements with correct per-slot typing.

This covers the `parse_table` shape in
`/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/tables.py`
(`for line, filename in strutil.parse_entries(entries, ignoresep=sep):`).

## Acceptance

- A cpp-path consumer generator iterating `for a, b in mod.gen(..., kw=...)`
  over a foreign compiled generator that yields `(str, ...)` tuples compiles and
  runs with correct values and element types (no routing refusal, no word-vs-char
  slot mis-typing that breaks string use).

## Done when

Quick test: run
`python3 tools/memslot.py --gb 8 --label tables-part3 -- python3 -c "import test_gimple_generator_runner as t; t._regression_tables_module_qualified_tuple_for()"`
from the worktree root and it passes (prints `PASS  tables_module_qualified_tuple_for`).
