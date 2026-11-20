# COMPILE_FAIL: Tools/c-analyzer/c_common/tables.py part 1 (tabled open in generator)

## Goal

Allow a compiled (cpp C++20-coroutine) generator body to use `with` over a
modeled tabled-open context manager (builtin `open` or a parameter whose
default is `open`), binding the file handle, honoring `newline`, and emitting
close on the normal path. Untabled managers must still be refused by name.

This covers the `read_table` shape in
`/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/tables.py`
(`with _open(infile, newline='') as infile:`).

## Acceptance

- A cpp-path generator using `with open(...)` / `with _open(...)` (defaulted to
  `open`) compiles and runs with the correct file iteration and close behavior.
- An untabled manager in the same position is refused by name (no silent
  miscompile).

## Done when

Quick test: run
`python3 tools/memslot.py --gb 8 --label tables-part1 -- python3 -c "import test_gimple_generator_runner as t; t._regression_with_tabled_open_in_generator()"`
from the worktree root and it passes (prints `PASS  cpp_with_tabled_open_in_generator`
and `PASS  cpp_with_tabled_open_in_generator_untabled_refusal`).
