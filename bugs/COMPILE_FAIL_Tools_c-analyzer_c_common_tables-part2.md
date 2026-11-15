# COMPILE_FAIL: Tools/c-analyzer/c_common/tables.py part 2 (callable-param generator-handle arg)

## Goal

Support a call through a callable-valued parameter in a compiled generator body
when an argument is a compiled-generator handle local, by materializing the
handle as needed so the callee can consume it (e.g. a tabled runtime like
`csv.reader` iterating produced lines).

This covers the `read_table` shape in
`/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/tables.py`
(`lines = strutil._iter_significant_lines(infile)` then
`for row in _get_reader(lines, delimiter=sep or '\t'):`).

## Acceptance

- A cpp-path generator that passes a generator-handle local as an argument to a
  callable-valued parameter compiles and runs with correct iteration/output (no
  refusal that the argument type is not statically a word/string/container).

## Done when

Quick test: run
`python3 tools/memslot.py --gb 8 --label tables-part2 -- python3 -c "import test_gimple_generator_runner as t; t._regression_tables_callable_param_generator_handle_arg()"`
from the worktree root and it passes (prints `PASS  tables_callable_param_generator_handle_arg`).
